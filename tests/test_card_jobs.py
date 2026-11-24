# Tests the Cards section's figures: the agent's state from its pulse, what became of each request, a request's row and
# its whole conversation, and that a request with no record (paused, still worked) still makes a row.
import json
from datetime import datetime, timedelta, timezone

from base import config
from base.models import FuelLine
from base.store import db
from features.dashboard import card_jobs, dashboard

NOW = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)   # 08:00 Central
SINCE = NOW - timedelta(hours=1)


# A row of agent_runs as the database gives it.
def run(outcome="opened c1, replied", steps=("declined_card: opened card …0001 for 1 fill",), opened=True, record=None,
        error=None, at=NOW) -> dict:
    return {"chat_id": -100, "message_id": 7, "unit": "3189", "woke_at": db._ts(at), "text": "card declined",
            "outcome": outcome, "steps": json.dumps(list(steps)), "opened_card": "c1" if opened else None,
            "opened_at": db._ts(at + timedelta(seconds=20)) if opened else None, "error": error,
            "record": json.dumps(record) if record else None}


# A diesel purchase of a unit at a Central time.
def fill(unit: str, at: str, station: str = "PILOT #1") -> FuelLine:
    return FuelLine(1, at, "fuel", "ULSD", 120.0, 480.0, 450.0, 0.0, True, station, "Hillsboro", "TX", "ALIF", unit,
                    None, None, None, None, None)


# The agent runs while its pulse is fresh; its batch is paused once the jobs done reach the most.
def test_agent_state():
    pulse = {"beat_at": db._ts(NOW - timedelta(seconds=40)), "emanager": 1, "emanager_since": db._ts(SINCE),
             "tag_at": db._ts(NOW), "tag_note": "unit 3189: taken"}
    state = card_jobs.agent_state(pulse, NOW, 120, 2, 5, SINCE)
    assert state["running"] and state["emanager"] is True and not state["paused"] and state["jobs_done"] == 2
    assert not card_jobs.agent_state(pulse, NOW + timedelta(minutes=5), 120, 5, 5, SINCE)["running"]
    assert card_jobs.agent_state(pulse, NOW, 120, 5, 5, SINCE)["paused"]
    never = card_jobs.agent_state(None, NOW, 120, 0, None, SINCE)
    assert not never["running"] and never["emanager"] is None and not never["paused"] and never["tag_at"] is None


# What became of a request, from how it ended.
def test_kind():
    assert card_jobs.kind(run()) == "opened"
    assert card_jobs.kind(run() | {"opened_at": None}) == "open_already"
    assert card_jobs.kind(run("replied, handed to the office", opened=False)) == "office"
    assert card_jobs.kind(run("replied", opened=False)) == "replied"
    assert card_jobs.kind(run("nothing to do: a thank-you", (), opened=False)) == "nothing"
    assert card_jobs.kind(run("paused after 5 jobs: left for the office", (), opened=False)) == "paused"
    assert card_jobs.kind(run("eManager not logged in: left for the office", (), opened=False)) == "logged_out"
    assert card_jobs.kind(run("failed", (), opened=False, error="RuntimeError()")) == "failed"
    assert card_jobs.kind(run(None, (), opened=False)) == "working"


# A row: the wait is from the driver's message to the opening; a job after the count began is in the batch; a request
# with no record still makes a row.
def test_row_and_detail():
    record = {"sender": "John Doe", "given": "Truck: unit 3189.\n\nThe chat, oldest first", "said": "Opened.", "cost": 0.03,
              "card": {"did": "opened", "name": "card …0001 (DT, unit 3189, JOHN DOE)", "status": "FRAUD", "own": True},
              "trace": [["thought", "he is at the pump"], ["used", "declined_card"]],
              "talk": [{"tool": "declined_card", "asked": {}, "answer": "The card is open.", "refused": False}],
              "office": ["Opened card …0001"],
              "chat": [{"at": (NOW - timedelta(seconds=25)).isoformat(), "sender": "John Doe", "ours": False,
                        "text": "card declined", "photo": False}]}
    seen = card_jobs.row(run(record=record), SINCE)
    assert seen["id"] == "-100_7" and seen["kind"] == "opened" and seen["job"] and seen["in_batch"] and seen["wait_s"] == 45
    assert seen["card"]["status"] == "FRAUD" and seen["sender"] == "John Doe"
    bare = card_jobs.row(run("paused after 5 jobs: left for the office", (), opened=False, at=SINCE - timedelta(hours=1)), SINCE)
    assert bare["kind"] == "paused" and not bare["job"] and not bare["in_batch"] and bare["card"] is None and bare["wait_s"] is None
    whole = card_jobs.detail(run(record=record), SINCE, [fill("3189", "2026-11-24 07:30"), fill("3189", "2026-11-24 08:20", "LOVES #220"),
                                                         fill("77", "2026-11-24 09:00")], 5)
    assert whole["facts"] == "Truck: unit 3189." and whole["trace"][0] == ["thought", "he is at the pump"]
    assert [(b["at"], b["loves"]) for b in whole["bought"]] == [("2026-11-24 08:20", True)]
    assert card_jobs.detail(run(None, (), opened=False), SINCE, [], 5)["chat"] == []


# The page's numbers from the database: the agent's state and its requests, and one request by its id.
def test_cards_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(dashboard.settings, "CARDS_FROM", SINCE)
    monkeypatch.setattr(dashboard.cards_settings, "AGENT_JOBS_SINCE", SINCE)
    monkeypatch.setattr(dashboard.cards_settings, "AGENT_MAX_JOBS", 5)
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        db.agent_beat(conn, now)
        db.agent_emanager(conn, True, now - timedelta(hours=2))
        db.agent_emanager(conn, True, now)                       # unchanged: "since" stays
        db.agent_tag(conn, now, "unit 3189: taken")
        db.claim_agent_run(conn, -100, 7, "3189", NOW, "card declined")
        db.finish_agent_run(conn, -100, 7, "opened c1, replied", json.dumps(["declined_card: opened"]), "c1", NOW, None, None)
    got = dashboard.cards_payload()
    assert got["agent"]["running"] and got["agent"]["emanager"] and got["agent"]["jobs_done"] == 1
    assert datetime.fromisoformat(got["agent"]["emanager_since"]) < now - timedelta(hours=1)
    assert [r["id"] for r in got["runs"]] == ["-100_7"] and dashboard.cards_run(-100, 7)["outcome"] == "opened c1, replied"
    try:
        dashboard.cards_run(-100, 8)
        raise AssertionError("a request that isn't there must be a LookupError")
    except LookupError:
        pass
