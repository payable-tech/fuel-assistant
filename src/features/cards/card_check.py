# The card checker (the user's go, 2026-11-26): for each ACTIVE EFS card, reads its truck's Telegram group (the latest
# CHECK_MESSAGES messages, whatever their age) with what the data says of the card, and lets Claude say what the card
# should be (on, off, unsure), why, and how sure. Each answer is saved in card_checks, for the All cards view. It only
# reads: it writes in no group and changes no card. Windows' Task Scheduler runs it three times a day (run_checker.bat).
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from base import config
from base.store import db
from features.cards import card_check_rules as rules, claude, settings, telegram_agent

log = logging.getLogger(__name__)
WORKSPACE = config.DATA_DIR / "checker"  # where the Claude runs keep their conversations


# One round: every ACTIVE card (or only those on `unit`, at most `most`), each checked in turn. A card that fails
# (Telegram or Claude) is logged and keeps its last check. Returns how many cards got a new check, of how many.
def run(most: int | None = None, unit: str | None = None) -> tuple[int, int]:
    return asyncio.run(_run(most, unit))


# The round itself: the cards and what the data says of them read once, then one card at a time.
async def _run(most: int | None, unit: str | None) -> tuple[int, int]:
    with db.connect() as conn:
        cards = [dict(c) for c in db.efs_card_list(conn) if c["status"] == "ACTIVE"]
        trucks = {t.unit: t for t in db.fleet(conn)}
        groups = db.tg_groups(conn)
        loads = defaultdict(list)
        for order in db.orders(conn):
            loads[order.unit].append(order)
    cards = [c for c in cards if unit in (None, c["dt_unit"], c["unit"])][:most]
    client = await telegram_agent.checker()
    checked = 0
    try:
        for card in cards:
            try:
                checked += await _check(client, card, trucks, loads, groups)
            except Exception:
                log.exception("Card …%s (%s) not checked", card["last4"], card["account"])
    finally:
        await client.disconnect()
    log.info("Cards checked: %d of %d", checked, len(cards))
    return checked, len(cards)


# Checks one card: its unit is the one Datatruck has it on, else the one on the card; the group read is the card's
# driver's own, else the truck's (card_check_rules.group_of). With no group the answer is "unsure, no group" without
# asking Claude. Returns 1 when a check was saved, 0 when Claude recorded none.
async def _check(client, card: dict, trucks: dict, loads: dict, groups: list) -> int:
    unit = card["dt_unit"] or card["unit"]
    truck = trucks.get(unit)
    group, closed = rules.group_of(card, truck.chat_id if truck else None, groups)
    if group is None:
        _save(card, *rules.NO_GROUP)
        return 1
    lines = await telegram_agent.latest(client, group.chat_id, settings.CHECK_MESSAGES, settings.CHECK_SCAN)
    recorded = []

    # The one tool: saves the answer once it can be saved, else tells Claude what to fix.
    async def record(args: dict) -> dict:
        problem = rules.problem(args)
        if problem:
            return claude.answer(problem, error=True)
        if not recorded:
            _save(card, args["should_be"], args["why"].strip(), args["sure"], str(args.get("evidence") or "").strip())
            recorded.append(args)
        return claude.answer("Recorded.")

    text = rules.facts(card, unit, truck, loads.get(unit, []), lines, datetime.now(timezone.utc), group.title, tuple(closed))
    answer = await claude.run(rules.INSTRUCTIONS, text, [], [claude.Tool("record_check", rules.RECORD_TOOL,
                                                                        rules.RECORD_INPUT, record)],
                              WORKSPACE, model=settings.CHECK_MODEL, effort=settings.CHECK_EFFORT)
    if not recorded:
        log.warning("Card …%s (%s): no check recorded (%s)", card["last4"], card["account"], answer.problem or answer.text[:200])
        return 0
    log.info("Card …%s (%s), unit %s: %s, %s (%s)", card["last4"], card["account"], unit, recorded[0]["should_be"],
             recorded[0]["why"], recorded[0]["sure"])
    return 1


# Saves one check of a card.
def _save(card: dict, should_be: str, why: str, sure: str, evidence: str) -> None:
    with db.connect() as conn:
        db.save_card_check(conn, card["account"], card["card_id"], should_be, why, sure, evidence)
