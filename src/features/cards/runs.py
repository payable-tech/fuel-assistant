# The card agent's live requests as a report (command card-runs): every request since a moment as one conversation, in
# the replay's view (features/cards/replay): the chat, what Claude thought, each tool with its answer, what went to the
# driver and the office, and the fuel the truck bought afterwards. Reads the database only; writes one HTML file.
import json
from datetime import datetime, timezone
from pathlib import Path

from base import config
from base.models import FuelLine
from base.store import db
from features.cards import replay, settings

REPORT = config.DATA_DIR / "card_runs.html"
MOST_FILLS = 5      # purchases shown after a request


# Writes the report of the requests since `since`, newest first, and returns its path.
def report(since: datetime) -> Path:
    with db.connect() as conn:
        runs = db.agent_runs_since(conn, since)
        fills = db.fuel_lines(conn, replay.central(since)[:10])
        jobs = db.agent_jobs_since(conn, settings.AGENT_JOBS_SINCE)
    limit = "no limit" if settings.AGENT_MAX_JOBS is None else f"{jobs} of {settings.AGENT_MAX_JOBS} jobs done"
    note = (f"The card agent's live requests since {since:%m-%d %H:%M} UTC ({limit}; a job is a request it used a tool "
            "for). These are real: what it wrote went to the drivers and the office, and the cards were changed. "
            "\"It thought\" is Claude's own summary of its thinking. The purchases under each request are the truck's, "
            "as Datatruck has them now; a fill shows up there some time after the pump.")
    REPORT.write_text(replay.page([as_case(run, fills) for run in runs], note), encoding="utf-8")
    return REPORT


# One run as the report's page takes a case: the row of agent_runs with its record opened, and the purchases of its
# truck after the request. A run kept without a record (Claude was not asked) shows the message alone.
def as_case(run: dict, fills: list[FuelLine]) -> dict:
    record = json.loads(run["record"] or "{}")
    woke = datetime.fromisoformat(run["woke_at"])
    talk = record.get("talk", [])
    bought = [f for f in fills if f.unit == run["unit"] and f.fueled_at >= replay.central(woke)][:MOST_FILLS]
    return {"unit": run["unit"] or "?", "at": woke.isoformat(), "age_days": (datetime.now(timezone.utc) - woke).days,
            "sender": record.get("sender", ""), "text": run["text"] or "",
            "chat": record.get("chat") or [{"at": woke.isoformat(), "sender": record.get("sender") or "the driver",
                                            "ours": False, "text": run["text"] or "", "photo": False}],
            "after": [{"at": "", "sender": "Bought", "text": bought_line(f)} for f in bought],
            "after_label": "Bought on this truck afterwards (Datatruck)",
            "outcome": run["outcome"] or "still being worked", "error": run["error"],
            "steps": json.loads(run["steps"] or "[]"), "talk": talk, "trace": record.get("trace", []),
            "given": record.get("given", ""), "said": record.get("said", ""), "problem": record.get("problem", ""),
            "cost": record.get("cost"), "office": record.get("office", []),
            "reply": next((t["asked"].get("text") for t in talk if t["tool"] == "reply_to_driver" and not t["refused"]), None)}


# One purchase in a line: when (Central), what, where, and what it cost at the pump.
def bought_line(fill: FuelLine) -> str:
    return (f"{fill.fueled_at} Central: {fill.gallons:.0f} gal {fill.product} at {fill.location}, {fill.city} "
            f"{fill.state}, ${fill.pump_total:.2f} at the pump")
