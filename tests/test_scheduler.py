# Tests the scheduler's rules: when a job is due (by its interval, or once a night) and when the loop counts as stuck.
from datetime import datetime, timedelta, timezone

import config
import db
from jobs import progress, scheduler


# A long job (10 min) isn't stuck; no progress for over half an hour is.
def test_stuck_only_after_half_an_hour():
    assert not scheduler.stuck(10 * 60) and not scheduler.stuck(29 * 60) and scheduler.stuck(31 * 60)


# A tick starts the progress clock afresh: the watchdog counts from the last one.
def test_tick_restarts_the_progress_clock(monkeypatch):
    monkeypatch.setattr(progress.time, "monotonic", lambda: 1000.0)
    progress.tick()
    monkeypatch.setattr(progress.time, "monotonic", lambda: 1600.0)
    assert progress.idle_sec() == 600


# A job is due when it never ran, when its last run was cut off before finishing (a restart), or once its interval passed.
def test_due(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    now = datetime.now(timezone.utc)
    assert scheduler._due("Hourly", 60, now)
    _record("Hourly", now - timedelta(minutes=5), None)
    assert scheduler._due("Hourly", 60, now)                                       # cut off: runs again
    _record("Hourly", now - timedelta(minutes=5), now)
    assert not scheduler._due("Hourly", 60, now)                                   # finished, not an hour yet
    assert scheduler._due("Hourly", 60, now + timedelta(minutes=56))


# A night job runs once a night inside the window (03:00-06:00 Central), never in the day: not even after a night
# missed or a run cut off. Only one that never ran goes at once.
def test_due_tonight(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "NIGHT_HOURS", (3, 6))
    day = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)                        # 09:00 Central
    night = datetime(2026, 11, 6, 9, 30, tzinfo=timezone.utc)                       # 03:30 Central
    nightly = scheduler.NIGHTLY
    assert scheduler._due("Nightly", nightly, day)                                 # never ran: at once
    _record("Nightly", day - timedelta(days=3), day - timedelta(days=3))
    assert not scheduler._due("Nightly", nightly, day)                             # days late: still waits for the night
    assert scheduler._due("Nightly", nightly, night)
    _record("Nightly", night, night + timedelta(minutes=10))
    assert not scheduler._due("Nightly", nightly, night + timedelta(hours=1))      # once a night
    assert scheduler._due("Nightly", nightly, night + timedelta(days=1))            # the next night
    _record("Nightly", night, None)
    assert scheduler._due("Nightly", nightly, night + timedelta(minutes=20))       # cut off at night: again that night
    assert not scheduler._due("Nightly", nightly, night + timedelta(hours=4))      # ... but not once the window closed


# The window opens at 03:00 Central (daylight saving included) and is None outside it.
def test_night_opened(monkeypatch):
    monkeypatch.setattr(config, "NIGHT_HOURS", (3, 6))
    assert scheduler._night_opened(datetime(2026, 11, 6, 9, 30, tzinfo=timezone.utc)).hour == 3     # 03:30 CST
    assert scheduler._night_opened(datetime(2026, 7, 6, 8, 59, tzinfo=timezone.utc)).hour == 3      # 03:59 CDT
    assert scheduler._night_opened(datetime(2026, 11, 6, 8, 59, tzinfo=timezone.utc)) is None      # 02:59 CST
    assert scheduler._night_opened(datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)) is None      # 06:00 CST


# Every job's interval is minutes or NIGHTLY, and the night jobs come after all the others (the loop stops a pass after
# one of them, so a job listed later would wait behind it).
def test_night_jobs_last():
    kinds = [every is scheduler.NIGHTLY for _, every, _ in scheduler.JOBS]
    assert kinds == sorted(kinds) and sum(kinds) == 5


# Records a run of a job in the test database.
def _record(name: str, started: datetime, finished: datetime | None) -> None:
    stamp = lambda d: d.isoformat(sep=" ", timespec="seconds") if d else None  # noqa: E731
    with db.connect() as conn:
        db.record_job(conn, name, stamp(started), stamp(finished), None)
