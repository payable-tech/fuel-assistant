# Scheduler: runs the refresh jobs on their own timetable in one background thread, one job at a time,
# so the dashboard stays live without anyone typing commands. Each run is recorded in the job_runs table.
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import config
import db
from core.fuel import CENTRAL
from jobs import (driver_habits, estimate_burn, estimate_tanks, fill_lookups, heartbeat, load_prices, progress, read_statements,
                  recommend, refresh_fuel, refresh_live, refresh_market, refresh_orders, statement_evidence, store_exits,
                  sync_registry)

log = logging.getLogger(__name__)

NIGHTLY = None  # in place of the minutes between runs: once a night, in config.NIGHT_HOURS (see _due)
# (job name, minutes between runs, what to run). Order matters on start-up: the quick, live-critical jobs go first.
# The slow daily ones come last and run at night: each holds the engine up for minutes while it runs (one job at a
# time), and in the morning that paused it for 28 min (2026-11-05). The user's go the same day.
JOBS = [
    ("Truck positions and fuel levels", config.EVERY_LIVE_MIN, refresh_live.run),
    ("Fuel purchases, last days", config.EVERY_RECENT_FUEL_MIN, refresh_fuel.run_recent),
    ("Active loads", config.EVERY_ORDERS_MIN, refresh_orders.run),
    ("Love's prices", config.EVERY_PRICES_MIN, load_prices.run),
    ("Fuel recommendations (silent)", config.EVERY_RECOMMEND_MIN, recommend.run),
    ("Market diesel prices (EIA)", config.EVERY_MARKET_MIN, refresh_market.run),
    ("EFS statements (data/efs)", config.EVERY_STATEMENTS_MIN, read_statements.run),
    ("Statement evidence (Samsara)", config.EVERY_EVIDENCE_MIN, statement_evidence.run),
    ("Engine fuel factors", config.EVERY_BURN_MIN, estimate_burn.run),
    ("Fill lookups (place, gauge)", config.EVERY_LOOKUP_MIN, fill_lookups.run),
    ("Trucks, drivers, Telegram", NIGHTLY, sync_registry.run),
    ("Fuel purchases, full copy", NIGHTLY, refresh_fuel.run),
    ("Driver habits (fuel stops with the gauge)", NIGHTLY, driver_habits.run),
    ("Tank estimates (pilot trucks)", NIGHTLY, estimate_tanks.run),
    ("Love's exits (new stores)", NIGHTLY, store_exits.run),
]
TICK_SEC = 30  # how often the scheduler looks for a job that is due


# Starts the scheduler in a background thread that ends with the program, its watchdog, and the heartbeat (in a thread
# of its own, so it still checks and alerts while the refreshes are busy or stuck).
def start() -> threading.Thread:
    thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    thread.start()
    threading.Thread(target=_watch, name="watchdog", daemon=True).start()
    schedule = {name: every for name, every, _ in JOBS}
    threading.Thread(target=heartbeat.loop, args=(schedule,), name="heartbeat", daemon=True).start()
    return thread


# Forever: when the refreshes have made no progress for STUCK_MIN (a job hanging, e.g. on a network call that never
# answers), ends the whole program, so run.bat starts it again fresh. A crash ends it anyway; a hang wouldn't.
def _watch() -> None:
    while True:
        time.sleep(60)
        if stuck(progress.idle_sec()):
            # ends the program even if the lines below can't be written (a stuck console blocks every log line)
            threading.Timer(10, os._exit, args=(1,)).start()
            log.error("The refreshes made no progress for %d min: restarting the program", config.STUCK_MIN)
            logging.shutdown()  # the line above reaches the log file before the program ends
            os._exit(1)


# True when the refreshes have gone this many seconds without progress: far longer than any job runs without a tick
# (~17 min at most; the engine ticks after each truck, so its slow first pass after a restart counts as moving).
def stuck(seconds_since_progress: float) -> bool:
    return seconds_since_progress > config.STUCK_MIN * 60


# Forever: run every job that is due, then wait a little. At most one night job per pass: the next pass starts again
# from the top, so the live jobs and the engine get their turn between two slow ones.
def _loop() -> None:
    while True:
        progress.tick()
        for name, every_min, job in JOBS:
            try:
                if _due(name, every_min, datetime.now(timezone.utc)):
                    _run(name, job)
                    if every_min is NIGHTLY:
                        break
            except Exception:  # e.g. the database busy for a moment: try again next tick instead of stopping for good
                log.exception("Scheduler could not check or record: %s", name)
            progress.tick()  # a job done (or not due): the loop is alive
        progress.tick()
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
