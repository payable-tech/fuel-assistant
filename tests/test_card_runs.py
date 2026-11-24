# Tests the report of the card agent's live requests: a run with its record becomes one conversation (the chat, the
# thought, the tool with its answer, the office post, the fuel bought afterwards), and a run without a record still
# shows its message.
import json
from datetime import datetime, timedelta, timezone

from base import config
from base.models import FuelLine
from base.store import db
from features.cards import runs

WOKE = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)   # 08:00 Central


# A diesel purchase of a unit at a Central time.
def fill(unit: str, at: str) -> FuelLine:
    return FuelLine(1, at, "fuel", "ULSD", 120.0, 480.0, 450.0, 0.0, True, "PILOT #1", "Hillsboro", "TX", "ALIF", unit,
                    None, None, None, None, None)


# A run with its record is the whole conversation; only the truck's own purchases after the request are shown.
def test_a_run_becomes_a_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(runs, "REPORT", tmp_path / "card_runs.html")
    record = {"sender": "John Doe", "given": "Truck: unit 3189.\n\nThe chat, oldest first", "said": "Opened it.", "cost": 0.03,
              "trace": [["thought", "he is at the <pump>"], ["used", "declined_card"], ["said", "Opened it."]],
              "talk": [{"tool": "declined_card", "asked": {}, "answer": "The card is open.", "refused": False}],
              "office": ["Opened card …0001 for unit 3189"],
              "chat": [{"at": WOKE.isoformat(), "sender": "John Doe", "ours": False, "text": "card declined", "photo": False}]}
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 1, "3189", WOKE, "card declined")
        db.finish_agent_run(conn, -100, 1, "opened c1", json.dumps(["declined_card: opened card …0001 for 1 fill"]), "c1",
                            WOKE, None, json.dumps(record))
        db.claim_agent_run(conn, -100, 2, "3189", WOKE + timedelta(minutes=5), "thanks")
    text = runs.report(WOKE - timedelta(hours=1)).read_text(encoding="utf-8")
    assert "he is at the &lt;pump&gt;" in text and "The card is open." in text and "Opened card …0001 for unit 3189" in text
    assert "opened: 1" in text and "still being worked" in text and text.index("thanks") < text.index("card declined")
    case = runs.as_case({"unit": "3189", "woke_at": db._ts(WOKE), "text": "x", "outcome": "o", "error": None, "steps": "[]",
                         "record": None},
                        [fill("3189", "2026-11-24 07:30"), fill("3189", "2026-11-24 08:20"), fill("77", "2026-11-24 09:00")])
    assert [a["text"][:16] for a in case["after"]] == ["2026-11-24 08:20"] and case["chat"][0]["text"] == "x"
