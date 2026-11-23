# The timetable: every automatic job, how often it runs and what runs it. With main.py, the only file that knows every
# feature; the scheduler (base/runner/scheduler) just runs this list.
from base import config
from base.fleet import copies, link_trucks, price_sheets
from base.runner.scheduler import NIGHTLY
from features.accounting import read_statements, statement_evidence
from features.dashboard import fill_lookups
from features.engine import driver_habits, estimate_burn, estimate_tanks, job as engine, store_exits

# (job name, minutes between runs, what to run). Order matters on start-up: the quick, live-critical jobs go first.
# The slow daily ones come last and run at night: each holds the engine up for minutes while it runs (one job at a
# time), and in the morning that paused it for 28 min (2026-11-05). The user's go the same day.
JOBS = [
    ("Truck positions and fuel levels", config.EVERY_LIVE_MIN, copies.live),
    ("Fuel purchases, last days", config.EVERY_RECENT_FUEL_MIN, copies.recent_fuel),
    ("Active loads", config.EVERY_ORDERS_MIN, copies.orders),
    ("Love's prices", config.EVERY_PRICES_MIN, price_sheets.run),
    ("Fuel recommendations (silent)", config.EVERY_RECOMMEND_MIN, engine.run),
    ("EFS statements (data/efs)", config.EVERY_STATEMENTS_MIN, read_statements.run),
    ("Statement evidence (Samsara)", config.EVERY_EVIDENCE_MIN, statement_evidence.run),
    ("Engine fuel factors", config.EVERY_BURN_MIN, estimate_burn.run),
    ("Fill lookups (place, gauge)", config.EVERY_LOOKUP_MIN, fill_lookups.run),
    ("Trucks, drivers, Telegram", NIGHTLY, link_trucks.run),
    ("Fuel purchases, full copy", NIGHTLY, copies.fuel),
    ("Driver habits (fuel stops with the gauge)", NIGHTLY, driver_habits.run),
    ("Tank estimates (pilot trucks)", NIGHTLY, estimate_tanks.run),
    ("Love's exits (new stores)", NIGHTLY, store_exits.run),
]


# Each job's minutes between runs (NIGHTLY for a nightly one), by its name: what the heartbeat tells a late job by.
def schedule() -> dict[str, int | None]:
    return {name: every for name, every, _ in JOBS}
