# Turning cards off in eManager (the user's go, 2026-11-26: "deactivate all cards that should be inactive"): every
# ACTIVE card whose latest check says off, each as features/cards/card_off_rules says. Each card is read again first
# (still ACTIVE, the same unit and driver name as when it was checked, not in override mode) and logged as it was
# before the first change, in data/card-off/log.csv; then INACTIVE (at once: the card is stopped first), the X-Ref,
# and for a terminated driver the three parked prompts. `card-off` lists them; `--send` makes the changes.
import csv
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from base import config
from base.fuel import CENTRAL
from base.models import EfsCard, EfsCardRow
from base.store import db
from features.cards import card_off_rules as rules, settings
from features.cards.emanager import fuel_cards, window

LOG = config.DATA_DIR / "card-off" / "log.csv"   # under data/: never pushed
LOG_COLUMNS = ("at", "event", "account", "card_id", "number", "status", "unit", "driver_id", "driver_name", "xref",
               "kind", "dt_driver_id", "why")
CHECKS_HOURS = 24   # only checks this recent count
GIVE_WAY_S = 0.5    # after each eManager call, so a card agent waiting for the window gets it first


# The cards due now, each with what it gets: (card as the copy has it, kind, X-Ref).
def plan() -> list[tuple[dict, str, str]]:
    with db.connect() as conn:
        cards = [dict(c) for c in db.efs_card_list(conn)]
    since = datetime.now(timezone.utc) - timedelta(hours=CHECKS_HOURS)
    day = datetime.now(CENTRAL).date()
    return [(c, *rules.action(c["dt_driver_status"], c["dt_driver_id"], day)) for c in rules.due(cards, since)]


# Turns the planned cards off (at most `most`), and counts what became of them. Any eManager error stops the run where
# it is; the card it was on is in the log.
def run(most: int | None = None) -> Counter:
    done = Counter()
    planned = plan()[:most]
    rows = {}
    for account in {c["account"] for c, _, _ in planned}:
        rows.update({(account, r.card_id): r for r in _in_window(fuel_cards.cards, account, "all")})
    for card, kind, xref in planned:
        row = rows.get((card["account"], card["card_id"]))
        done[_off_one(card, row, kind, xref) if row else "gone from EFS"] += 1
    return done


# Turns one card off, after reading its page: only while it is still as it was checked. Returns what became of it.
def _off_one(card: dict, row: EfsCardRow, kind: str, xref: str) -> str:
    page = _in_window(fuel_cards.card, card["account"], row)
    changed = page.status != "ACTIVE" or (row.unit or "").strip() != (card["unit"] or "") or \
        (row.driver_name or "").strip().upper() != (card["driver_name"] or "").upper()
    if changed or page.override:
        why = "in override mode" if page.override and not changed else "changed since it was checked"
        _log(f"skipped: {why}", card, row, page, kind)
        return "skipped"
    _log("before", card, row, page, kind)
    _in_window(fuel_cards.set_status, card["account"], row, "INACTIVE")
    with db.connect() as conn:
        db.set_efs_card_status(conn, card["account"], card["card_id"], "INACTIVE")
    _in_window(fuel_cards.set_xref, card["account"], row, xref)
    if kind == rules.QUIT:
        missing = [p for p in ("Unit Number", "Driver ID", "Driver Name") if p not in page.own_prompts]
        if missing:  # a stock card's prompts come from its policy: nothing on it to park
            _log(f"off, not parked: {', '.join(missing)} from its policy", card, row, None, kind, xref)
            return "off, not parked"
        for prompt, value in settings.PARKED_PROMPTS.items():
            _in_window(fuel_cards.set_prompt, card["account"], row, prompt, value)
        _log("off and parked", card, row, None, kind, xref)
        return "off and parked"
    _log("off", card, row, None, kind, xref)
    return "off"


# One eManager call while holding the window, then a pause that lets a waiting card agent in first.
def _in_window(call, *args):
    try:
        with window.held():
            return call(*args)
    finally:
        time.sleep(GIVE_WAY_S)


# Adds one line to the log at once (a crash after it keeps it): the card as its page showed it for "before" and
# "skipped", else what it became.
def _log(event: str, card: dict, row: EfsCardRow, page: EfsCard | None, kind: str, xref: str = "") -> None:
    prompts = {label: value for label, _, value in page.prompts} if page else {}
    new = not LOG.exists()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as file:
        writer = csv.writer(file)
        if new:
            writer.writerow(LOG_COLUMNS)
        writer.writerow((datetime.now(timezone.utc).isoformat(timespec="seconds"), event, card["account"],
                         card["card_id"], row.number, page.status if page else "INACTIVE",
                         prompts.get("Unit Number", ""), prompts.get("Driver ID", ""), prompts.get("Driver Name", ""),
                         page.xref if page else xref, kind, card["dt_driver_id"] or "", card["why"] or ""))
