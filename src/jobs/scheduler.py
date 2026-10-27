# Scheduler: runs the refresh jobs on their own timetable in one background thread, one job at a time,
# so the dashboard stays live without anyone typing commands. Each run is recorded in the job_runs table.
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import config
import db
from jobs import (driver_habits, estimate_tanks, load_prices, plan_loads, refresh_fuel, refresh_live, refresh_market,
                  refresh_orders, sync_registry)

log = logging.getLogger(__name__)

# (job name, minutes between runs, what to run). Order matters on start-up: the quick, live-critical jobs go first.
JOBS = [
    ("Truck positions and fuel levels", config.EVERY_LIVE_MIN, refresh_live.run),
    ("Fuel purchases, last days", config.EVERY_RECENT_FUEL_MIN, refresh_fuel.run_recent),
    ("Active loads", config.EVERY_ORDERS_MIN, refresh_orders.run),
    ("Fuel plans for pilot loads", config.EVERY_PLAN_MIN, plan_loads.run),
    ("Love's prices", config.EVERY_PRICES_MIN, load_prices.run),
    ("Market diesel prices (EIA)", config.EVERY_MARKET_MIN, refresh_market.run),
    ("Trucks, drivers, Telegram", config.EVERY_SYNC_MIN, sync_registry.run),
    ("Fuel purchases, full copy", config.EVERY_FUEL_LINES_MIN, refresh_fuel.run),
    ("Tank estimates (pilot trucks)", config.EVERY_TANKS_MIN, estimate_tanks.run),
    ("Driver habits (fuel stops with the gauge)", config.EVERY_HABITS_MIN, driver_habits.run),
]
TICK_SEC = 30  # how often the scheduler looks for a job that is due
_last_progress = time.monotonic()  # when the loop last finished a job or a pass; the watchdog reads it


# Starts the scheduler in a background thread that ends with the program, and its watchdog.
def start() -> threading.Thread:
    thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    thread.start()
    threading.Thread(target=_watch, name="watchdog", daemon=True).start()
    return thread


# Forever: when the loop has made no progress for STUCK_MIN (a job hanging, e.g. on a network call that never
# answers), ends the whole program, so run.bat starts it again fresh. A crash ends it anyway; a hang wouldn't.
def _watch() -> None:
    while True:
        time.sleep(60)
        if stuck(time.monotonic() - _last_progress):
            log.error("The refreshes made no progress for %d min: restarting the program", config.STUCK_MIN)
            logging.shutdown()  # the line above reaches the log file before the program ends
            os._exit(1)


# True when the loop has gone this many seconds without progress: far longer than any job takes (~5 min at most).
def stuck(seconds_since_progress: float) -> bool:
    return seconds_since_progress > config.STUCK_MIN * 60


# Forever: run every job that is due, then wait a little.
def _loop() -> None:
    global _last_progress
    while True:
        _last_progress = time.monotonic()
        for name, every_min, job in JOBS:
            try:
                if _due(name, every_min):
                    _run(name, job)
            except Exception:  # e.g. the database busy for a moment: try again next tick instead of stopping for good
                log.exception("Scheduler could not check or record: %s", name)
            _last_progress = time.monotonic()  # a job done (or not due): the loop is alive
        time.sleep(TICK_SEC)


# True when a job has never run, or its last start was at least `every_min` minutes ago.
def _due(name: str, every_min: int) -> bool:
    with db.connect() as conn:
        run = db.job_runs(conn).get(name)
    if run is None:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(run["started_at"]) >= timedelta(minutes=every_min)


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
