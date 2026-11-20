# Tests the heartbeat: its rules (core/health), that every source refresh is recorded (jobs/mirror), and that an alert
# goes out once when a part breaks and once when it works again (jobs/heartbeat).
from datetime import datetime, timedelta, timezone

import pytest

import config
import db
from core import health
from core.fuel import CENTRAL
from jobs import heartbeat, mirror
from models import Problem, SourceHealth

NOW = datetime(2026, 11, 19, 16, 0, tzinfo=timezone.utc)  # Thursday 10:00 Central


# A source failing for half an hour is down; one failed try after a good copy 10 min ago is a blip; one that never
# worked is down at once; one that works isn't.
def test_source_problems():
    ago = lambda m: NOW - timedelta(minutes=m)
    sources = [SourceHealth("Late", ago(1), ago(40), "login refused"), SourceHealth("Blip", ago(1), ago(10), "timeout"),
               SourceHealth("Never", ago(1), None, "no rows"), SourceHealth("Fine", ago(1), ago(1), None)]
    found = health.source_problems(sources, NOW, 30)
    assert [p.component for p in found] == ["Late", "Never"] and found[0].since == ago(40) and "login refused" in found[0].text


# A crashed job, a 5-min job not started for an hour and a nightly one not for 30 h are problems; a job started 20 min
# ago, and a job the scheduler doesn't run, aren't.
def test_job_problems():
    runs = [("Crash", NOW - timedelta(minutes=2), "KeyError: 'x'"), ("Five", NOW - timedelta(minutes=60), None),
            ("Fresh", NOW - timedelta(minutes=20), None), ("Night", NOW - timedelta(hours=30), None),
            ("Heartbeat", NOW - timedelta(days=9), None)]
    found = health.job_problems(runs, {"Crash": 15, "Five": 5, "Fresh": 15, "Night": None}, NOW, 45)
    assert [p.component for p in found] == ["Crash", "Five", "Night"] and "crashed" in found[0].text


# Samsara silent for 40 min, no purchase for 5 h in the day, and no price sheet of today after 9:00 on a weekday are
# problems; the same purchase gap at night and no sheet on a Sunday aren't.
def test_data_problems():
    args = (30, 4, (7, 23), 9)
    found = health.data_problems(NOW - timedelta(minutes=40), "2026-11-19 05:00", "2026-11-18", NOW, *args)
    assert [p.component for p in found] == ["Samsara positions", "Fuel purchases coming in", "Love's price sheet"]
    night = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)  # 02:00 Central
    assert health.data_problems(night, "2026-11-18 20:00", "2026-11-18", night, *args) == []
    sunday = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)
    assert health.data_problems(sunday, "2026-11-22 10:30", "2026-11-21", sunday, *args) == []


# Unsent fuel messages are a Telegram problem; none isn't.
def test_send_problems():
    assert health.send_problems(0, 60) == [] and health.send_problems(2, 60)[0].component == "Telegram sending"


# A problem still found keeps whether it was told and when it began; one no longer found has ended.
def test_changes_keep_told_and_find_the_ended():
    began = NOW - timedelta(hours=2)
    stored = {"A": Problem("A", "old words", began, True), "B": Problem("B", "gone", began, True)}
    kept, ended = health.changes([Problem("A", "new words"), Problem("C", "new")], stored)
    assert kept == [Problem("A", "new words", began, True), Problem("C", "new")] and ended == [stored["B"]]


# The alerts' words: what broke, that it works again and how long it was down, and the program's own downtime.
def test_alert_texts():
    p = Problem("Datatruck fuel lines, last days", "not refreshing", NOW - timedelta(hours=15, minutes=10))
    assert health.down_text(p).startswith("🔴") and "Datatruck fuel lines" in health.down_text(p)
    assert health.up_text(p, NOW).endswith("(down 15 h 10 min)")
    assert "(42 min)" in health.gap_text(NOW - timedelta(minutes=42), NOW)


# A temporary database for each test, and every Telegram send caught (a False in `fail` makes the next sends fail).
@pytest.fixture
def sent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "TEST_CHAT_ID", -100)
    monkeypatch.setattr(config, "ALERT_CHAT_ID", None)
    calls = Calls()

    def send(chat, text):
        if calls.fail:
            raise ConnectionError("Telegram down")
        calls.append((chat, text))

    monkeypatch.setattr(heartbeat.telegram, "send", send)
    return calls


# The sends caught by the fixture, and `fail`: while it holds anything, sending fails.
class Calls(list):
    def __init__(self):
        super().__init__()
        self.fail = []


# Every refresh is recorded: a failed one keeps the last good time and its error, a good one clears the error.
def test_mirror_records_each_try(sent):
    assert not mirror.refresh("Src", lambda: (_ for _ in ()).throw(RuntimeError("login refused")), lambda c, r: None)
    with db.connect() as conn:
        first = db.source_health(conn)[0]
    assert first.last_ok_at is None and "login refused" in first.error
    assert mirror.refresh("Src", lambda: [1], lambda c, r: None)
    with db.connect() as conn:
        ok = db.source_health(conn)[0]
    assert ok.error is None and ok.last_ok_at is not None


# A source failing: one alert to the alert chat; the next check sends nothing new; once it works, one "working again".
# An alert that can't go out is tried again at the next check.
def test_alert_once_down_once_up(sent):
    with db.connect() as conn:
        db.record_source(conn, "Datatruck fuel lines", NOW - timedelta(hours=2), None)
        db.record_source(conn, "Datatruck fuel lines", NOW - timedelta(minutes=1), "RuntimeError: login refused")
    sent.fail.append(True)
    heartbeat.run({}, NOW)
    assert sent == []                                        # Telegram down: kept, not told
    sent.fail.clear()
    heartbeat.run({}, NOW)
    assert len(sent) == 1 and sent[0][0] == -100 and "🔴" in sent[0][1]
    heartbeat.run({}, NOW + timedelta(minutes=5))
    assert len(sent) == 1                                    # told once
    with db.connect() as conn:
        db.record_source(conn, "Datatruck fuel lines", NOW + timedelta(minutes=8), None)
        assert list(db.health_alerts(conn)) == ["Datatruck fuel lines"]
    heartbeat.run({}, NOW + timedelta(minutes=10))
    assert len(sent) == 2 and "working again" in sent[1][1]
    with db.connect() as conn:
        assert db.health_alerts(conn) == {}


# On start, a heartbeat silent for longer than DOWN_GAP_MIN means the program was down: that is told once.
def test_gap_is_told(sent, monkeypatch):
    with db.connect() as conn:
        db.record_job(conn, heartbeat.NAME, db.now(), db._ts(NOW - timedelta(hours=1)), None)
    heartbeat._tell_gap(NOW)
    assert len(sent) == 1 and "was down" in sent[0][1]
    heartbeat._tell_gap(NOW - timedelta(minutes=50))  # 10 min after the last sign: no gap
    assert len(sent) == 1
