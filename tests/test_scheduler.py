# Tests the scheduler's watchdog rule: only a loop with no progress for far longer than any job counts as stuck.
from jobs import scheduler


# A long job (10 min) isn't stuck; no progress for over half an hour is.
def test_stuck_only_after_half_an_hour():
    assert not scheduler.stuck(10 * 60) and not scheduler.stuck(29 * 60) and scheduler.stuck(31 * 60)
