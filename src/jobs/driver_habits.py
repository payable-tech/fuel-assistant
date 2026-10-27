# Driver habits job: every driver's diesel stops of the last HABIT_DAYS days with the Samsara gauge of the truck they
# drove, into `fuel_stops`. Habits are worked out from these rows when the dashboard asks.
import logging
from datetime import datetime, timedelta, timezone

import config
import db
from core import fuel, habits
from jobs import mirror
from models import FuelReading, FuelStop
from sources import samsara

log = logging.getLogger(__name__)


# Replaces the fuel stops. Returns True when they were refreshed (a failure keeps the previous ones).
def run() -> bool:
    return mirror.refresh("Driver fuel stops", _stops, db.replace_fuel_stops)


# Every driver's stops with the gauge around them (one Samsara call per truck that bought diesel).
def _stops() -> list[FuelStop]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=config.HABIT_DAYS)
    window = timedelta(minutes=config.TANK_WINDOW_MIN)
    with db.connect() as conn:
        lines = db.fuel_lines(conn, since_day=start.date().isoformat())
        samsara_ids = {t.unit: t.samsara_id for t in db.fleet(conn)}
    units = sorted({l.unit for l in lines if fuel.is_diesel(l) and l.unit in samsara_ids})
    readings = {unit: _gauge(samsara_ids[unit], start - window, now) for unit in units}
    return habits.fuel_stops(lines, readings, window)


# One truck's gauge readings; a failed call gives none (its stops get no gauge) instead of stopping every truck.
def _gauge(samsara_id: str, start: datetime, end: datetime) -> list[FuelReading]:
    try:
        return samsara.fuel_history(samsara_id, start, end)
    except Exception as error:
        log.warning("No gauge readings for Samsara vehicle %s: %r", samsara_id, error)
        return []
