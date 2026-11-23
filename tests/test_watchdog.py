# Tests the watchdog: when the jobs count as stuck, and that a tick starts its clock afresh.
from base.runner import watchdog


# A long job (10 min) isn't stuck; nothing moving for over half an hour is.
def test_stuck_only_after_half_an_hour():
    assert not watchdog.stuck(10 * 60) and not watchdog.stuck(29 * 60) and watchdog.stuck(31 * 60)


# A tick starts the clock afresh: the watchdog counts from the last one.
def test_tick_restarts_the_clock(monkeypatch):
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 1000.0)
    watchdog.tick()
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 1600.0)
    assert watchdog.idle_sec() == 600
