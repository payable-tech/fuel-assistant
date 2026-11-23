# Scheduler: runs the jobs it is given on their own timetable in one background thread, one job at a time, so the
# dashboard stays live without anyone typing commands. Each run is recorded in the job_runs table. Which jobs there are
# and how often each runs is listed in src/timetable.py.
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from base import config
from base.fuel import CENTRAL
from base.runner import watchdog
from base.store import db

log = logging.getLogger(__name__)

NIGHTLY = None  # in place of the minutes between runs: once a night, in config.NIGHT_HOURS (see _due)
TICK_SEC = 30  # how often the scheduler looks for a job that is due


# Starts the scheduler in a background thread that ends with the program. `jobs`: (job name, minutes between runs or
# NIGHTLY, what to run) each, in the order they run when several are due.
def start(jobs: list[tuple]) -> threading.Thread:
    thread = threading.Thread(target=_loop, args=(jobs,), name="scheduler", daemon=True)
    thread.start()
    return thread


# Forever: run every job that is due, then wait a little. At most one night job per pass: the next pass starts again
# from the top, so the live jobs and the engine get their turn between two slow ones. Each step tells the watchdog the
# loop is alive.
def _loop(jobs: list[tuple]) -> None:
    while True:
        watchdog.tick()
        for name, every_min, job in jobs:
            try:
                if _due(name, every_min, datetime.now(timezone.utc)):
                    _run(name, job)
                    if every_min is NIGHTLY:
                        break
            except Exception:  # e.g. the database busy for a moment: try again next tick instead of stopping for good
                log.exception("Scheduler could not check or record: %s", name)
            watchdog.tick()  # a job done (or not due): the loop is alive
        watchdog.tick()
        time.sleep(TICK_SEC)


# True when a job should run `now`: it never ran, or its last run never finished, or its time came: `every_min` minutes
# after its last start, or for a NIGHTLY job, not yet started since tonight's window opened. A NIGHTLY job runs only in
# the window, so a night missed (the program down) or failed waits for the next night, never the day; one that never ran
# runs at once (a new database has nothing to work with). Jobs run one at a time, so a run not finished when this asks
# was cut off by a restart: it runs again now, not a day later (habits were skipped for a day that way, 2026-11-05).
def _due(name: str, every_min: int | None, now: datetime) -> bool:
    with db.connect() as conn:
        run = db.job_runs(conn).get(name)
    if run is None:
        return True
    opened = _night_opened(now) if every_min is NIGHTLY else None
    if every_min is NIGHTLY and opened is None:
        return False
    if run["finished_at"] is None:
        return True
    started = datetime.fromisoformat(run["started_at"])
    return started < opened if every_min is NIGHTLY else now - started >= timedelta(minutes=every_min)


# When tonight's window (config.NIGHT_HOURS, Central) opened, while `now` is inside it; None outside it.
def _night_opened(now: datetime) -> datetime | None:
    start, end = config.NIGHT_HOURS
    local = now.astimezone(CENTRAL)
    return local.replace(hour=start, minute=0, second=0, microsecond=0) if start <= local.hour < end else None


# Runs one job, recording its start and end; a crash is logged and recorded, and the scheduler carries on.
def _run(name: str, job) -> None:
    started = db.now()
    with db.connect() as conn:
        db.record_job(conn, name, started, None, None)
    error = None
    try:
        job()
    except Exception as exc:  # one failing job must not stop the others
        error = f"{type(exc).__name__}: {exc}"
        log.exception("Scheduled job failed: %s", name)
    with db.connect() as conn:
        db.record_job(conn, name, started, db.now(), error)
