# The Cards section's figures (pure): the card agent's state from its pulse, each of its requests as a row of the list,
# and one request as its whole conversation. A request kept before a field existed, one still being worked, and one
# Claude was never asked about (paused, eManager logged out) all lack parts of the record: every part is optional.
import json
from datetime import datetime, timedelta

from base import fuel
from base.models import FuelLine

# What became of a request, in one word each (the page has their names and colors).
WORKING, FAILED, PAUSED, LOGGED_OUT, OPENED, OPEN_ALREADY, OFFICE, REPLIED, NOTHING = (
    "working", "failed", "paused", "logged_out", "opened", "open_already", "office", "replied", "nothing")


# The agent's state for the status strip: running (its pulse beat within `silent_s`), eManager, the last tag heard,
# and its batch of jobs (`done` of `most` since `since`; paused once done reaches most).
def agent_state(pulse: dict | None, now: datetime, silent_s: int, done: int, most: int | None, since: datetime) -> dict:
    pulse = pulse or {}
    beat = _moment(pulse.get("beat_at"))
    return {"running": bool(beat and now - beat < timedelta(seconds=silent_s)), "beat_at": _iso(beat),
            "emanager": None if pulse.get("emanager") is None else bool(pulse["emanager"]),
            "emanager_since": _iso(_moment(pulse.get("emanager_since"))),
            "tag_at": _iso(_moment(pulse.get("tag_at"))), "tag_note": pulse.get("tag_note"),
            "jobs_done": done, "jobs_most": most, "jobs_since": since.isoformat(),
            "paused": most is not None and done >= most}


# What became of a request (one of the words above), from its row: how it ended, and whether a card was opened.
def kind(run: dict) -> str:
    outcome = run["outcome"]
    if outcome is None:
        return WORKING
    if run["error"] or outcome.startswith("stopped:"):
        return FAILED
    if outcome.startswith("paused"):
        return PAUSED
    if outcome.startswith("eManager not logged in"):
        return LOGGED_OUT
    if run["opened_card"]:  # found open already: nothing was changed, so no time of opening was kept
        return OPENED if run["opened_at"] else OPEN_ALREADY
    if "handed to the office" in outcome:
        return OFFICE
    return REPLIED if "replied" in outcome else NOTHING


# One request as a row of the list: who, when, what was written, what became of it, the card, and how long the driver
# waited for the opening. `in_batch`: it is one of the jobs counted since `since`.
def row(run: dict, since: datetime) -> dict:
    record = json.loads(run["record"] or "{}")
    woke = _moment(run["woke_at"])
    job = bool(json.loads(run["steps"] or "[]"))
    return {"id": f"{run['chat_id']}_{run['message_id']}", "unit": run["unit"], "at": woke.isoformat(),
            "sender": record.get("sender"), "text": run["text"] or "", "kind": kind(run), "job": job,
            "in_batch": job and woke >= since, "card": record.get("card"), "wait_s": wait_s(run, record)}


# One request as its whole conversation: its row, the chat it read, what it thought and each tool with its answer, what
# went to the office, its own words at the end, what it was told about the truck, and the truck's purchases since (as
# Datatruck has them, newest `most_fills`).
def detail(run: dict, since: datetime, lines: list[FuelLine], most_fills: int) -> dict:
    record = json.loads(run["record"] or "{}")
    woke = _moment(run["woke_at"])
    from_central = f"{woke.astimezone(fuel.CENTRAL):%Y-%m-%d %H:%M}"
    bought = [l for l in lines if l.unit == run["unit"] and l.fueled_at >= from_central]
    return row(run, since) | {
        "outcome": run["outcome"], "error": run["error"], "steps": json.loads(run["steps"] or "[]"),
        "chat": record.get("chat") or [], "trace": record.get("trace") or [], "talk": record.get("talk") or [],
        "office": record.get("office") or [], "said": record.get("said") or "", "cost": record.get("cost"),
        "facts": (record.get("given") or "").split("\n\nThe chat,")[0],
        "bought": [{"at": l.fueled_at, "gallons": l.gallons, "product": l.product, "station": l.location, "city": l.city,
                    "state": l.state, "pump_total": l.pump_total, "loves": fuel.is_loves(l)} for l in bought[:most_fills]]}


# Seconds from the driver's message to the card's opening; None when no card was opened, or the message's time wasn't
# kept (the chat is read only when Claude is asked).
def wait_s(run: dict, record: dict) -> int | None:
    chat, opened = record.get("chat") or [], _moment(run["opened_at"])
    if not chat or not opened:
        return None
    waited = (opened - datetime.fromisoformat(chat[-1]["at"])).total_seconds()
    return int(waited) if waited >= 0 else None


# A stored time ("2026-11-24 13:05:00+00:00") as a moment; None for none.
def _moment(stored: str | None) -> datetime | None:
    return datetime.fromisoformat(stored) if stored else None


# A moment as ISO text for the page; None for none.
def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None
