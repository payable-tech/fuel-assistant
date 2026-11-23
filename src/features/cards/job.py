# The card agent (the user's go, 2026-11-23), built the way bob-agent's Telegram agent works: wakes when the assistant's
# account is tagged in a truck's group, reads the chat before the tag (photos too) with what we know of the truck, and
# lets Claude (this PC's Claude Code login) decide. A declined card is settled by the owner's rule in code
# (features/cards/rules: the driver's own card, opened for one fill when active, anything else to a person); Claude calls it
# and passes its line to the driver. Every opening is reported to the office and kept in `agent_runs`.
import asyncio
import json
import re
import logging
from datetime import datetime, timedelta, timezone

from base import config
from base.fuel import is_diesel
from base.models import ChatLine, DatatruckDriver, EfsCardRow, Truck
from base.store import db
from features.cards import claude, efs_cards, efs_chrome, efs_fake, efs_web, rules, settings, telegram_agent
from features.cards.claude import Tool, answer
from features.cards.efs_chrome import EfsError
from features.cards.rules import NeedsPerson

log = logging.getLogger(__name__)
ACCOUNTS = tuple(settings.EMANAGER_USERS)   # the eManager accounts a card can be in ("ALIF", "DT")
WORKSPACE = config.DATA_DIR / "agent"     # where the Claude runs keep their conversations
JOIN_MINUTES = 10                         # a bare tag this soon after a request in the same group joins it: no new run
_one_run = asyncio.Lock()                 # one request at a time, in the order they came
_efs = asyncio.Lock()                     # one eManager window: one call at a time (the runs and the login keeper)


# Forever: opens the eManager window, keeps its login alive, and answers every tag in the truck groups.
def run() -> None:
    if not settings.AGENT_TEST_ONLY:  # the test group's card is a pretend one: no eManager needed
        efs_chrome.start()
    asyncio.run(_main())


# The listener and the login keeper side by side; either stopping ends the program (run_agent.bat starts it again).
async def _main() -> None:
    await asyncio.gather(telegram_agent.listen(on_tag), *([] if settings.AGENT_TEST_ONLY else [_keep_login()]))


# A tag heard. Not in its own office or test chat, only in a group linked to a truck, worth waking for, not a bare tag
# right after a request there, and never the same message twice; then the chat is read and the request worked.
async def on_tag(client, message, named: bool) -> None:
    text = message.message or ""
    test = message.chat_id == settings.AGENT_TEST_CHAT_ID
    if (settings.AGENT_TEST_ONLY and not test) or not rules.woken(text, named):
        return
    if not test and message.chat_id in (settings.AGENT_OFFICE_CHAT_ID, config.TEST_CHAT_ID):
        return  # its reports go there: a reply in them is the office's, not a driver's
    truck, drivers = _truck_of(message.chat_id)
    if truck is None:
        return  # a group linked to no truck: its chat is never sent anywhere
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        if rules.only_a_tag(text) and db.agent_run_since(conn, message.chat_id, now - timedelta(minutes=JOIN_MINUTES)):
            return  # "@desk" again while the request just taken there is worked: it joins that one
        if not db.claim_agent_run(conn, message.chat_id, message.id, truck.unit, now, text[:2000]):
            return
    chat = await telegram_agent.chat_before(client, message.chat_id, message.id, settings.AGENT_HISTORY,
                                            settings.AGENT_MAX_PHOTOS)
    async with _one_run:
        await work(Task(client, message.chat_id, message.id, text, chat[-1].sender if chat else "", truck, drivers), chat)


# Works one request to its end and records it. Without eManager no card can be fixed: the office is told and Claude
# isn't asked. A failure of Claude or Telegram goes to the office too.
async def work(task: "Task", chat: list[ChatLine]) -> None:
    outcome, error = "", None
    try:
        if not task.test and not await _emanager_alive():
            await task.office(f"🙋 Unit {task.unit}: tagged, but eManager is not logged in, so no card can be opened. "
                              f"Log in in its window. Driver wrote: {task.text[:300]}")
            outcome = "eManager not logged in: left for the office"
        else:
            said = await claude.run(rules.SYSTEM, prompt(task, chat), [c.photo for c in chat if c.photo], task.tools(),
                                    WORKSPACE)
            outcome = task.outcome() or (f"stopped: {said.problem}" if said.problem else
                                         f"nothing to do: {said.text[:200]}")
    except Exception as failure:
        error, outcome = repr(failure)[:500], "failed"
        log.exception("Card agent failed on %s / %s", task.chat_id, task.message_id)
        await task.office(f"🙋 Unit {task.unit}: the card agent could not finish this request "
                          f"({type(failure).__name__}). Driver wrote: {task.text[:300]}")
    with db.connect() as conn:
        db.finish_agent_run(conn, task.chat_id, task.message_id, outcome, json.dumps(task.steps), task.opened,
                            task.opened_at, error)
    log.info("Card agent, unit %s: %s", task.unit, outcome)


# What Claude is told: the facts about the truck, the chat oldest first, and which message woke it. The photos go with
# it as pictures (features/cards/claude), in the order they were sent.
def prompt(task: "Task", chat: list[ChatLine]) -> str:
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        watch = db.truck_watch(conn, task.unit)
        loves = db.stores(conn)
        fills = [l for l in db.fuel_lines(conn, (now - timedelta(days=3)).date().isoformat())
                 if l.unit == task.unit and is_diesel(l)]
    return (f"{rules.facts(task.truck, task.drivers, watch.state if watch else None, loves, fills, now)}\n\n"
            f"The chat, oldest first (the photos above are its [photo] messages, in order):\n"
            f"{rules.transcript(chat)}\n\n"
            f"The message that woke you is the last one, from {task.sender or 'the driver'}. Now: {now:%m-%d %H:%M} UTC.")


# The truck whose group this is, and its active drivers in Datatruck; (None, []) for a group linked to no truck.
def _truck_of(chat_id: int) -> tuple[Truck | None, list[DatatruckDriver]]:
    if chat_id == settings.AGENT_TEST_CHAT_ID:
        return efs_fake.TRUCK, efs_fake.DRIVERS
    with db.connect() as conn:
        truck = next((t for t in db.fleet(conn) if t.chat_id == chat_id), None)
        drivers = [d for d in db.dt_drivers(conn) if truck and d.unit == truck.unit and d.employee_status == "active"]
    return truck, drivers


# Whether eManager has someone logged in right now (Chrome closed or not answering counts as no).
async def _emanager_alive() -> bool:
    try:
        async with _efs:
            return await asyncio.to_thread(efs_web.heartbeat)
    except Exception:
        return False


# Forever: asks eManager every few minutes whether someone is logged in, which also keeps the login from timing out
# (90 idle minutes); logs when that changes.
async def _keep_login() -> None:
    was = None
    while True:
        alive = await _emanager_alive()
        if alive != was:
            (log.info if alive else log.warning)("eManager %s", "logged in" if alive else
                                                 "NOT logged in: log in in its window")
            was = alive
        await asyncio.sleep(settings.EMANAGER_HEARTBEAT_SECONDS if alive else 60)


# One request being worked: where it came from, who wrote it, the truck, and what was done. Its tools are what Claude
# may call; each checks what it may do itself, so no chat text can make it act on another truck or open a card twice.
class Task:
    # The request: the Telegram client, the group and message, its text, who wrote it, the group's truck and that
    # truck's active drivers.
    def __init__(self, client, chat_id: int, message_id: int, text: str, sender: str, truck: Truck,
                 drivers: list[DatatruckDriver]):
        self.client, self.chat_id, self.message_id, self.text, self.sender = client, chat_id, message_id, text, sender
        self.truck, self.drivers, self.unit = truck, drivers, truck.unit
        self.test = chat_id == settings.AGENT_TEST_CHAT_ID
        self.efs = efs_fake if self.test else efs_cards  # the test group's card is a pretend one
        self.steps: list[str] = []
        self.opened: str | None = None
        self.opened_at: datetime | None = None
        self.replied = self.handed = False

    # The tools Claude may call, with what each does as Claude reads it.
    def tools(self) -> list[Tool]:
        return [
            Tool("declined_card", "A driver's fuel card was declined or does not work, or he asks to open it. The fuel "
                 "desk's code finds the driver's own card and does what the company's rule says: opens it for one fill "
                 "now, or hands it to a person. It says what happened and what to tell the driver.",
                 {"type": "object", "properties": {}}, self.declined_card),
            Tool("look_up_card", "How this truck's fuel card(s) stand in eManager: status, whether open now, last used. "
                 "Read only; for questions other than a declined card.", {"type": "object", "properties": {}},
                 self.look_up_card),
            Tool("reply_to_driver", "Answer in the driver's group, as a reply to the message that woke you. Once.",
                 {"type": "object", "properties": {"text": {"type": "string", "description": "one short line"}},
                  "required": ["text"]}, self.reply_to_driver),
            Tool("hand_to_office", "Pass the request to a person in the office with a note of what the driver needs.",
                 {"type": "object", "properties": {"note": {"type": "string", "description": "one or two lines"}},
                  "required": ["note"]}, self.hand_to_office),
        ]

    # How the request ended, in words, when a tool did something; "" when nothing was done.
    def outcome(self) -> str:
        done = (["opened " + self.opened] if self.opened else []) + (["replied"] if self.replied else []) + \
            (["handed to the office"] if self.handed else [])
        return ", ".join(done)

    # Tool: the owner's rule for a declined card (features/cards/rules), made in code. Claude only passes its line on.
    async def declined_card(self, args: dict) -> dict:
        if self.opened:
            return answer("The card was already opened for this request. Tell the driver to try again now.")
        try:
            driver = rules.whose(self.drivers, self.sender)
            account, row, card = await self._card_of(driver)
            kind, ask_first = rules.rule(card, account, row)
            with db.connect() as conn:
                soon = rules.too_soon(db.agent_last_opened(conn, row.card_id), datetime.now(timezone.utc),
                                      settings.AGENT_REOPEN_HOURS)
            if soon:
                raise NeedsPerson(f"{rules.named(account, row)}: {soon}")
        except (NeedsPerson, EfsError) as why:
            self.steps.append(f"declined_card: needs a person, {why}")
            await self.hand_to_office({"note": f"Declined card, needs a person: {why}."})
            return answer(f"Needs a person: {why}. The office has it. Tell the driver the office will check the card "
                          "shortly.")
        if ask_first:  # HOLD or INACTIVE: activating is a person's yes (no approvals here yet)
            self.steps.append(f"declined_card: {rules.named(account, row)} is {card.status}, asked the office")
            await self.hand_to_office({"note": f"Declined card: {rules.named(account, row)} is {card.status}. The rule "
                                               "is to activate it, then open it for 1 fill; a person decides."})
            return answer("The card is not active; the office decides. Tell the driver the card is being checked and "
                          "the office will write when it is ready.")
        if not settings.AGENT_ACT:
            self.steps.append(f"declined_card: would open {rules.named(account, row)} (AGENT_ACT is off)")
            await self.office(f"🔍 Would open {rules.named(account, row)} for unit {self.unit}: 1 fill, all locations. "
                              f"Driver wrote: {self.text[:300]}")
            return answer("Watch-only: the card was not opened. Tell the driver the office will check it shortly.")
        return await self._open(account, row)

    # Tool: this truck's cards as eManager shows them now; read only.
    async def look_up_card(self, args: dict) -> dict:
        try:
            found = await self._lookup()
            on_unit = [(a, r) for a, r in found if r.unit.strip() == self.unit]
            async with _efs:
                lines = [rules.card_view(a, r, await asyncio.to_thread(self.efs.card, a, r)) for a, r in on_unit]
        except EfsError as error:
            return answer(f"eManager can't be reached right now ({error}).", error=True)
        self.steps.append(f"look_up_card: {len(lines)} card(s)")
        return answer("\n".join(lines) or f"No card on unit {self.unit} in eManager.")

    # Tool: the one answer in the driver's group; never a long number, never "open"/"ready" unless a card was opened.
    async def reply_to_driver(self, args: dict) -> dict:
        text = (args.get("text") or "").strip()
        if self.replied:
            return answer("You already replied to this request.", error=True)
        if not text or re.search(r"\d{5,}", text):
            return answer("Not sent: a reply never carries card numbers or IDs.", error=True)
        if not self.opened and re.search(r"\b(open|ready|try again)\b", text, re.IGNORECASE):
            return answer("Not sent: no card was opened for this request; don't say it is ready.", error=True)
        self.replied = True
        self.steps.append(f"reply_to_driver: {text[:200]}")
        if not settings.AGENT_ACT:
            await self.office(f"🔍 Would reply in unit {self.unit}'s group: {text}")
            return answer("Watch-only: the reply went to the office, not the driver.")
        await telegram_agent.write(self.client, self.chat_id, text, reply_to=self.message_id)
        return answer("Sent.")

    # Tool: passes the request to a person in the office chat.
    async def hand_to_office(self, args: dict) -> dict:
        self.handed = True
        note = re.sub(rf"^\s*unit {re.escape(self.unit)}\s*:\s*", "", args.get("note") or "", flags=re.IGNORECASE)
        self.steps.append(f"hand_to_office: {note[:200]}")
        await self.office(f"🙋 Unit {self.unit}: {note}\nDriver wrote: {self.text[:300]}")
        return answer("The office has it.")

    # Posts to the office's chat (the test group when none is set); a post that fails is logged, never raised.
    async def office(self, text: str) -> None:
        chat = settings.AGENT_OFFICE_CHAT_ID or config.TEST_CHAT_ID
        if not chat:
            log.warning("No office chat for the card agent: %s", text)
            return
        try:
            await telegram_agent.write(self.client, chat, text)
        except Exception:
            log.exception("Card agent could not post to the office: %s", text)

    # The cards Card Lookup finds on this truck's unit, in both accounts.
    async def _lookup(self) -> list[tuple[str, EfsCardRow]]:
        async with _efs:
            return [(a, r) for a in ACCOUNTS for r in await asyncio.to_thread(self.efs.cards, a, "unit", self.unit)]

    # The driver's own card and its page, read now (features/cards/rules.their_card).
    async def _card_of(self, driver: DatatruckDriver):
        account, row = rules.their_card(await self._lookup(), self.unit, driver)
        async with _efs:
            return account, row, await asyncio.to_thread(self.efs.card, account, row)

    # Opens the card for one fill at all locations, records it the moment eManager confirms, and reports it.
    async def _open(self, account: str, row: EfsCardRow) -> dict:
        try:
            async with _efs:
                after = await asyncio.to_thread(self.efs.set_override, account, row, settings.AGENT_OPEN_FILLS)
        except EfsError as error:
            self.steps.append(f"declined_card: eManager did not open it, {error}")
            await self.hand_to_office({"note": f"Opening {rules.named(account, row)} failed in eManager: {error}"})
            return answer("Opening failed; the office has it. Tell the driver the office will check it shortly.")
        if not after.override:
            await self.hand_to_office({"note": f"eManager did not confirm {rules.named(account, row)} is open."})
            return answer("Not confirmed; the office has it. Tell the driver the office will check it shortly.")
        self.opened, self.opened_at = row.card_id, datetime.now(timezone.utc)
        with db.connect() as conn:  # at once: the audit and the cooldown survive a crash after this
            db.record_agent_open(conn, self.chat_id, self.message_id, row.card_id, self.opened_at)
        self.steps.append(f"declined_card: opened {rules.named(account, row)} for {settings.AGENT_OPEN_FILLS} fill")
        await self.office(f"🔓 Opened {rules.named(account, row)} for unit {self.unit}: {settings.AGENT_OPEN_FILLS} fill, "
                          f"all locations. Driver wrote: {self.text[:300]}")
        return answer("The card is open for one fill at any station. Tell the driver: card is ready, try again now.")
