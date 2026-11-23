# The timetable: every automatic job, how often it runs and what runs it. With main.py, the only file that knows every
# feature; the scheduler (base/runner/scheduler) just runs this list.
from base.fleet import copies, link_trucks, price_sheets
from base.runner.scheduler import NIGHTLY
from features.accounting import read_statements, statement_evidence
from features.dashboard import fill_lookups
from features.engine import helper_jobs, job as engine

# (job name, minutes between runs, what to run). Order matters on start-up: the quick, live-critical jobs go first.
# The slow daily ones come last and run at night: each holds the engine up for minutes while it runs (one job at a
# time), and in the morning that paused it for 28 min (2026-11-05). The user's go the same day.
JOBS = [
    ("Truck positions and fuel levels", 5, copies.live),
    ("Fuel purchases, last days", 15, copies.recent_fuel),
    ("Active loads", 15, copies.orders),
    ("Love's prices", 30, price_sheets.run),
    ("Fuel recommendations (silent)", 5, engine.run),
    ("EFS statements (data/efs)", 30, read_statements.run),
    ("Statement evidence (Samsara)", 15, statement_evidence.run),
    ("Engine fuel factors", 24 * 60, helper_jobs.mpg_factors),
    ("Fill lookups (place, gauge)", 15, fill_lookups.run),
    ("Trucks, drivers, Telegram", NIGHTLY, link_trucks.run),
    ("Fuel purchases, full copy", NIGHTLY, copies.fuel),
    ("Driver habits (fuel stops with the gauge)", NIGHTLY, helper_jobs.driver_stops),
    ("Tank estimates (pilot trucks)", NIGHTLY, helper_jobs.tank_sizes),
    ("Love's exits (new stores)", NIGHTLY, helper_jobs.loves_exits),
]


# Each job's minutes between runs (NIGHTLY for a nightly one), by its name: what the heartbeat tells a late job by.
def schedule() -> dict[str, int | None]:
    return {name: every for name, every, _ in JOBS}
