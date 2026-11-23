# What Claude may do for one request: four tools. Each gathers what it needs, asks the rules (features/cards/rules) and
# only then acts, so no chat text can make it act on another truck, open a card twice, or send a number. The words it
# answers and reports are in features/cards/wording. Every opening is reported to the office and kept in `agent_runs`.
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
        self.opened: str | None = None
        self.opened_at: datetime | None = None
        self.replied = self.handed = False

    # The tools Claude may call, with what each does as Claude reads it.
    def tools(self) -> list[Tool]:
        return [Tool("declined_card", wording.DECLINED_CARD_TOOL, wording.NO_INPUT, self.declined_card),
                Tool("look_up_card", wording.LOOK_UP_CARD_TOOL, wording.NO_INPUT, self.look_up_card),
                Tool("reply_to_driver", wording.REPLY_TOOL, wording.REPLY_INPUT, self.reply_to_driver),
                Tool("hand_to_office", wording.HAND_TO_OFFICE_TOOL, wording.NOTE_INPUT, self.hand_to_office)]

    # How the request ended, in words, when a tool did something; "" when nothing was done.
    def outcome(self) -> str:
        done = (["opened " + self.opened] if self.opened else []) + (["replied"] if self.replied else []) + \
            (["handed to the office"] if self.handed else [])
        return ", ".join(done)

    # Tool: a declined card. Gathers (whose card it is, the cards on the truck's unit, the card's page, when the agent
    # last opened it), lets the rules decide (rules.verdict), then acts: opens it, asks the office first, only reports
    # what it would do, or hands it to a person. Claude only passes its line on.
    async def declined_card(self, args: dict) -> dict:
        if self.opened:
            return answer(wording.ALREADY_OPENED)
        try:
            driver = rules.whose(self.drivers, self.sender)  # settled before eManager is asked anything
            account, row = rules.their_card(await self._lookup(), self.unit, driver)
            card = await emanager(self.efs.card, account, row)
            with db.connect() as conn:
                last_opened = db.agent_last_opened(conn, row.card_id)
            verdict = rules.verdict(card, account, row, last_opened, datetime.now(timezone.utc),
                                    settings.AGENT_REOPEN_HOURS, settings.AGENT_ACT)
        except (NeedsPerson, EfsError) as why:
            self.steps.append(f"declined_card: needs a person, {why}")
            await self.hand_to_office({"note": wording.note_needs_person(why)})
            return answer(wording.needs_person(why))
        card_name = rules.named(account, row)
        if verdict == rules.ASK_FIRST:  # HOLD or INACTIVE: activating is a person's yes (no approvals here yet)
            self.steps.append(f"declined_card: {card_name} is {card.status}, asked the office")
            await self.hand_to_office({"note": wording.note_not_active(card_name, card.status)})
            return answer(wording.NOT_ACTIVE)
        if verdict == rules.WATCH_ONLY:
            self.steps.append(f"declined_card: would open {card_name} (AGENT_ACT is off)")
            await self.office(wording.would_open(card_name, self.unit, self.text))
            return answer(wording.WATCH_ONLY_CARD)
        return await self._open(account, row)

    # Tool: this truck's cards as eManager shows them now; read only.
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

    # Opens the card for one fill at all locations, records it the moment eManager confirms, and reports it.
    async def _open(self, account: str, row: EfsCardRow) -> dict:
        card_name = rules.named(account, row)
        try:
            after = await emanager(self.efs.set_override, account, row, settings.AGENT_OPEN_FILLS)
        except EfsError as error:
            self.steps.append(f"declined_card: eManager did not open it, {error}")
            await self.hand_to_office({"note": wording.note_open_failed(card_name, error)})
            return answer(wording.OPEN_FAILED)
        if not after.override:
            await self.hand_to_office({"note": wording.note_not_confirmed(card_name)})
            return answer(wording.NOT_CONFIRMED)
        self.opened, self.opened_at = row.card_id, datetime.now(timezone.utc)
        with db.connect() as conn:  # at once: the audit and the cooldown survive a crash after this
            db.record_agent_open(conn, self.chat_id, self.message_id, row.card_id, self.opened_at)
        self.steps.append(f"declined_card: opened {card_name} for {settings.AGENT_OPEN_FILLS} fill")
        await self.office(wording.opened_report(card_name, self.unit, settings.AGENT_OPEN_FILLS, self.text))
        return answer(wording.OPENED)
