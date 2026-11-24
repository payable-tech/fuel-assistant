# What Claude may do for one request: three tools. Each gathers what it needs, asks the rules (features/cards/rules)
# and only then acts, so no chat text can make it act on another truck, open a card twice, or send a number. The words it
# answers and reports are in features/cards/wording. Every opening is reported to the office and kept in `agent_runs`,
# and every use of a tool is noted with its answer (`talk`), for the run's record.
import asyncio
import logging
import re
from datetime import datetime, timezone

from base import config
from base.models import DatatruckDriver, EfsCardRow, Truck
from base.store import db
from features.cards import rules, settings, telegram_agent, wording
from features.cards.claude import Tool, answer
from features.cards.emanager import fake_cards, fuel_cards
from features.cards.emanager.window import EfsError
from features.cards.rules import NeedsPerson

log = logging.getLogger(__name__)
ACCOUNTS = tuple(settings.EMANAGER_USERS)   # the eManager accounts a card can be in ("ALIF", "DT")
_efs = asyncio.Lock()                     # one eManager window: one call at a time (the tools and the login keeper)


# Makes one call to eManager, never two at once.
async def emanager(call, *args):
    async with _efs:
        return await asyncio.to_thread(call, *args)


# One request being worked: where it came from, who wrote it, the truck, and what was done. Its tools are what Claude
# may call.
class Request:
    # The request: the Telegram client, the group and message, its text, who wrote it, the group's truck and that
    # truck's active drivers.
    def __init__(self, client, chat_id: int, message_id: int, text: str, sender: str, truck: Truck,
                 drivers: list[DatatruckDriver]):
        self.client, self.chat_id, self.message_id, self.text, self.sender = client, chat_id, message_id, text, sender
        self.truck, self.drivers, self.unit = truck, drivers, truck.unit
        self.test = chat_id == settings.AGENT_TEST_CHAT_ID
        self.efs = fake_cards if self.test else fuel_cards  # the test group's card is a pretend one
        self.steps: list[str] = []
        self.talk: list[dict] = []   # each use of a tool by Claude: what it asked and what it was answered
        self.posts: list[str] = []   # what was posted to the office for this request
        self.opened: str | None = None
        self.opened_at: datetime | None = None
        self.replied = self.handed = False

    # The tools Claude may call, with what each does as Claude reads it. look_up_card is not among them for now (the
    # user, 2026-11-24: its one job is opening the card; looking first only made it hesitate).
    def tools(self) -> list[Tool]:
        given = (("declined_card", wording.DECLINED_CARD_TOOL, wording.NO_INPUT, self.declined_card),
                 ("reply_to_driver", wording.REPLY_TOOL, wording.REPLY_INPUT, self.reply_to_driver),
                 ("hand_to_office", wording.HAND_TO_OFFICE_TOOL, wording.NOTE_INPUT, self.hand_to_office))
        return [Tool(name, described, takes, self._noted(name, run)) for name, described, takes, run in given]

    # A tool's run that also notes each use in `talk`: what Claude asked of it and what it was answered.
    def _noted(self, name: str, run):
        # The tool's own run, then the note.
        async def noted(args: dict) -> dict:
            reply = await run(args)
            self.talk.append({"tool": name, "asked": args, "answer": reply["content"][0]["text"],
                              "refused": bool(reply.get("is_error"))})
            return reply

        return noted

    # How the request ended, in words, when a tool did something; "" when nothing was done.
    def outcome(self) -> str:
        done = (["opened " + self.opened] if self.opened else []) + (["replied"] if self.replied else []) + \
            (["handed to the office"] if self.handed else [])
        return ", ".join(done)

    # Tool: the driver asks about using his card. Gathers (whose card it is, the cards on the truck's unit, the card's
    # page), lets the rules decide (rules.verdict), then acts: opens it (activating it first when it is inactive),
    # finds it open already, only reports what it would do, or hands it to a person when no one card can be told.
    # Claude only passes its line on.
    async def declined_card(self, args: dict) -> dict:
        if self.opened:
            return answer(wording.ALREADY_OPENED)
        try:
            driver = rules.whose(self.drivers, self.sender)  # settled before eManager is asked anything
            account, row, own = rules.their_card(await self._lookup(), self.unit, driver)
            card = await emanager(self.efs.card, account, row)
            verdict = rules.verdict(card, account, row, own, settings.AGENT_ACT)
        except (NeedsPerson, EfsError) as why:
            self.steps.append(f"declined_card: needs a person, {why}")
            await self.hand_to_office({"note": wording.note_needs_person(why)})
            return answer(wording.needs_person(why))
        card_name = rules.named(account, row)
        if verdict == rules.WATCH_ONLY:
            self.steps.append(f"declined_card: would open {card_name} (AGENT_ACT is off)")
            await self.office(wording.would_open(card_name, self.unit, self.text))
            return answer(wording.WATCH_ONLY_CARD)
        if verdict == rules.ALREADY_OPEN:  # nothing to change in eManager; the driver may be told to try again
            self.opened = row.card_id
            self.steps.append(f"declined_card: {card_name} was opened already (override on), nothing changed")
            await self.office(wording.already_open_report(card_name, self.unit, self.text))
            return answer(wording.OPEN_ALREADY)
        return await self._open(account, row, card.status, verdict == rules.ACTIVATE_AND_OPEN, own)

    # This truck's cards as eManager shows them now; read only. Not among Claude's tools for now (see tools()).
    async def look_up_card(self, args: dict) -> dict:
        try:
            found = await self._lookup()
            on_unit = [(a, r) for a, r in found if r.unit.strip() == self.unit]
            async with _efs:
                lines = [wording.card_view(a, r, await asyncio.to_thread(self.efs.card, a, r)) for a, r in on_unit]
        except EfsError as error:
            return answer(wording.emanager_down(error), error=True)
        self.steps.append(f"look_up_card: {len(lines)} card(s)")
        return answer("\n".join(lines) or wording.no_card(self.unit))

    # Tool: the one answer in the driver's group, when the rules let it out (rules.reply_refused: never a long number,
    # never "open"/"ready" unless a card was opened).
    async def reply_to_driver(self, args: dict) -> dict:
        text = (args.get("text") or "").strip()
        refused = rules.reply_refused(text, self.replied, bool(self.opened))
        if refused:
            return answer(wording.REPLY_REFUSED[refused], error=True)
        self.replied = True
        self.steps.append(f"reply_to_driver: {text[:200]}")
        if not settings.AGENT_ACT:
            await self.office(wording.would_reply(self.unit, text))
            return answer(wording.WATCH_ONLY_REPLY)
        await telegram_agent.write(self.client, self.chat_id, text, reply_to=self.message_id)
        return answer(wording.SENT)

    # Tool: passes the request to a person in the office chat.
    async def hand_to_office(self, args: dict) -> dict:
        self.handed = True
        note = re.sub(rf"^\s*unit {re.escape(self.unit)}\s*:\s*", "", args.get("note") or "", flags=re.IGNORECASE)
        self.steps.append(f"hand_to_office: {note[:200]}")
        await self.office(wording.handed(self.unit, note, self.text))
        return answer(wording.OFFICE_HAS_IT)

    # Posts to the office's chat (the test group when none is set); a post that fails is logged, never raised.
    async def office(self, text: str) -> None:
        chat = settings.AGENT_OFFICE_CHAT_ID or config.TEST_CHAT_ID
        self.posts.append(text)
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

    # Opens the card for one fill at all locations (`activate`: it is inactive, so it is set ACTIVE first), records it
    # the moment eManager confirms, and reports it with what a person should know: the status it was in, whether it
    # is in the driver's name (`own`), and whether the agent opened it not long ago.
    async def _open(self, account: str, row: EfsCardRow, status: str, activate: bool, own: bool) -> dict:
        card_name = rules.named(account, row)
        activated = False
        try:
            if activate:
                await emanager(self.efs.set_status, account, row, "ACTIVE")
                activated = True
            after = await emanager(self.efs.set_override, account, row, settings.AGENT_OPEN_FILLS)
        except EfsError as error:
            self.steps.append(f"declined_card: eManager did not open it, {error}")
            await self.hand_to_office({"note": wording.note_open_failed(card_name, error, activated)})
            return answer(wording.OPEN_FAILED)
        if not after.override:
            await self.hand_to_office({"note": wording.note_not_confirmed(card_name)})
            return answer(wording.NOT_CONFIRMED)
        self.opened, self.opened_at = row.card_id, datetime.now(timezone.utc)
        with db.connect() as conn:  # at once: the audit survives a crash after this
            again = rules.repeat(db.agent_last_opened(conn, row.card_id), self.opened_at, settings.AGENT_REPEAT_HOURS)
            db.record_agent_open(conn, self.chat_id, self.message_id, row.card_id, self.opened_at)
        self.steps.append(f"declined_card: opened {card_name} for {settings.AGENT_OPEN_FILLS} fill"
                          f"{' (activated first)' if activated else ''}")
        await self.office(wording.opened_report(card_name, self.unit, settings.AGENT_OPEN_FILLS,
                                                wording.remarks(status, activated, own, again), self.text))
        return answer(wording.OPENED)
