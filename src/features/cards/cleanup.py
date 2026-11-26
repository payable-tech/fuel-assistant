# The card cleanup (the user, 2026-11-24): every Datatruck unit keeps its card and every other EFS card is parked on
# 99999 / ALIF UZ CORP (features/cards/cleanup_rules). First the plan, read only, from the copies of EFS's and
# Datatruck's lists, for the user to look over; then parking the plan's cards in eManager, a few at a time, each one
# decided again on what eManager shows at that moment; and putting one card back from the log. Files are in
# data/efs-cleanup.
import csv
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from base import config
from base.models import EfsCardRow
from base.store import db
from features.cards import cleanup_rules as rules
from features.cards.emanager import fuel_cards, window

PLAN_DIR = config.DATA_DIR / "efs-cleanup"   # under data/: never pushed (driver names, driver IDs)
COLUMNS = ("action", "why", "account", "card_id", "last4", "status", "unit", "driver_name")
ORDER = {rules.LEAVE: 0, rules.PARK: 1, rules.KEEP: 2, rules.PARKED: 3}   # the plan file, what needs a look first
# Every card the parking touched, oldest first: its prompts before ("before", written before the first change), then
# "parked" or why it was skipped. Putting a card back reads its first "before" line.
LOG = PLAN_DIR / "log.csv"
LOG_COLUMNS = ("at", "event", "account", "card_id", "number", "status", "last_used", "unit", "driver_id", "driver_name")
LABELS = {prompt: label for prompt, (_, label) in fuel_cards.PROMPTS.items()}   # "unit": "Unit Number", ...
# After each eManager call the cleanup waits this long before taking the window again, so a card agent waiting for it
# (it looks every window.WAIT_S) gets it first: a driver at the pump never waits behind the whole cleanup.
GIVE_WAY_S = 0.5
# Why a stock card is skipped: its unit or driver ID is its policy's, not on the card. That doesn't change, so later
# runs leave it without reading it again.
POLICY_PROMPTS = "not on the card (its policy's)"


# Decides every card of the copy and writes the plan file. Returns its path, the count of each action, the units
# that end with no card, and when the copy of EFS's list was taken.
def plan() -> tuple[Path, Counter, list[str], str]:
    with db.connect() as conn:
        cards = [dict(row) for row in db.efs_cards(conn)]
    drivers, listed = _datatruck()
    if not cards:
        raise RuntimeError("The copy of EFS's cards is empty; the card agent copies it every 30 minutes.")
    for card in cards:
        card["action"], card["why"] = rules.decide(card["status"], card["unit"], card["last4"], card["driver_name"],
                                                   None, drivers, listed)
    cards.sort(key=lambda c: (ORDER[c["action"]], c["account"], c["unit"] or "", c["card_id"]))
    kept = {(c["unit"] or "").strip() for c in cards if c["action"] == rules.KEEP}
    path = PLAN_DIR / f"plan-{datetime.now(timezone.utc):%Y-%m-%d-%H%M}.csv"
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:   # utf-8-sig: Excel reads it right
        writer = csv.DictWriter(file, COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cards)
    return (path, Counter(c["action"] for c in cards), rules.left_without_card(drivers, kept),
            min(c["synced_at"] for c in cards))


# Parks at most `most` of the plan's "park" cards that eManager still shows as cards to park, and counts what became
# of them. A card that changed since the plan (in use now, Datatruck's card, in the unit driver's name) is left, and
# so is a card put back by hand or skipped for its policy's prompts. Any error from eManager stops the run where it
# is: the next run carries on.
def park(plan_path: Path, most: int) -> Counter:
    with plan_path.open(encoding="utf-8-sig") as file:
        planned = [(r["account"], r["card_id"]) for r in csv.DictReader(file) if r["action"] == rules.PARK]
    set_aside = {card_id for card_id, event in _logged() if event == "put back" or event.endswith(POLICY_PROMPTS)}
    planned = [(a, c) for a, c in planned if c not in set_aside]
    drivers, listed = _datatruck()
    live = {}
    for account in sorted({a for a, _ in planned}):
        live |= {(account, row.card_id): row for row in _in_window(fuel_cards.cards, account, "all")}
    done = Counter()
    for account, card_id in planned:
        if done["parked"] >= most:
            break
        row = live.get((account, card_id))
        if row is None:
            done["gone from eManager"] += 1
            continue
        action, why = rules.decide(row.status, row.unit, row.number[-4:], row.driver_name, row.driver_id, drivers,
                                   listed)
        if action == rules.PARK:
            done[_park_one(account, row)] += 1
        elif action == rules.PARKED:
            done["parked already"] += 1
        else:
            _log(f"left: now {why}", account, row)
            done["left: changed since the plan"] += 1
    return done


# Puts one parked card's prompts back as its first "before" line in the log says. A prompt that was empty stays
# parked (eManager takes no empty value): it is named in the answer.
def undo(card_id: str) -> str:
    with LOG.open(encoding="utf-8-sig") as file:
        before = next((r for r in csv.DictReader(file) if r["card_id"] == card_id and r["event"] == "before"), None)
    if before is None:
        raise RuntimeError(f"No card {card_id} in {LOG}.")
    account = before["account"]
    parked = _in_window(fuel_cards.cards, account, "unit", rules.PARKED_PROMPTS["unit"])
    row = next((r for r in parked if r.card_id == card_id), None)
    if row is None:
        raise RuntimeError(f"Card {card_id} is not on unit {rules.PARKED_PROMPTS['unit']} in {account} any more.")
    empty = []
    for prompt, column in (("unit", "unit"), ("driver-id", "driver_id"), ("driver", "driver_name")):
        if not before[column]:
            empty.append(LABELS[prompt])
            continue
        _in_window(fuel_cards.set_prompt, account, row, prompt, before[column])
    _log("put back", account, row)
    left = f"; left at 99999: {', '.join(empty)} (empty before)" if empty else ""
    return f"Card …{row.number[-4:]} put back{left}"


# Parks one card, prompt by prompt, after reading its page: only an INACTIVE card, not in override mode, with all
# three prompts set on the card itself (a stock card's come from its policy: nothing on it to park). Its prompts as
# they were are logged before the first change. Returns what became of it.
def _park_one(account: str, row: EfsCardRow) -> str:
    card = _in_window(fuel_cards.card, account, row)
    prompts = {label: value for label, _, value in card.prompts}
    missing = [label for label in LABELS.values() if label not in card.own_prompts]
    if card.status != "INACTIVE" or card.override or missing:
        why = (f"status {card.status}" if card.status != "INACTIVE" else "in override mode" if card.override
               else f"{', '.join(missing)} {POLICY_PROMPTS}")
        _log(f"skipped: {why}", account, row, card)
        return "skipped"
    _log("before", account, row, card, prompts)
    for prompt, value in rules.PARKED_PROMPTS.items():
        # one call per prompt: a card opening waits behind one change at most
        _in_window(fuel_cards.set_prompt, account, row, prompt, value)
    _log("parked", account, row)
    return "parked"


# Each Datatruck unit with its active drivers' names, and every (unit, last 4) of a card Datatruck lists on a unit.
def _datatruck() -> tuple[dict[str, list[str]], set[tuple[str, str]]]:
    with db.connect() as conn:
        units = db.units(conn)
        active = [d for d in db.dt_drivers(conn) if d.employee_status == "active"]
    if len(units) < 100:   # a short copy of Datatruck's trucks would only add cards to park
        raise RuntimeError(f"Only {len(units)} Datatruck units in the copy; sync first.")
    drivers = {u.unit: [d.full_name for d in active if d.unit == u.unit] for u in units}
    return drivers, {(u.unit, last4) for u in units for last4 in u.cards}


# One eManager call while holding the window, then the pause that lets a waiting card agent in first.
def _in_window(call, *args):
    try:
        with window.held():
            return call(*args)
    finally:
        time.sleep(GIVE_WAY_S)


# The log's lines as (card id, event); none before the first run.
def _logged() -> list[tuple[str, str]]:
    if not LOG.exists():
        return []
    with LOG.open(encoding="utf-8-sig") as file:
        return [(r["card_id"], r["event"]) for r in csv.DictReader(file)]


# Adds one line to the log, at once (a crash after it keeps it). `prompts`: the card's prompts, for a "before" line.
def _log(event: str, account: str, row: EfsCardRow, card=None, prompts: dict | None = None) -> None:
    prompts = prompts or {}
    new = not LOG.exists()
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", newline="", encoding="utf-8-sig" if new else "utf-8") as file:
        writer = csv.writer(file)
        if new:
            writer.writerow(LOG_COLUMNS)
        writer.writerow((datetime.now(timezone.utc).isoformat(timespec="seconds"), event, account, row.card_id,
                         row.number, card.status if card else row.status, card.last_used if card else "",
                         prompts.get(LABELS["unit"], ""), prompts.get(LABELS["driver-id"], ""),
                         prompts.get(LABELS["driver"], "")))
