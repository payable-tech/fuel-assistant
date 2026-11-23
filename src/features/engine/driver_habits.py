# Driver habits job: every driver's diesel stops of the last HABIT_DAYS days with the Samsara gauge of the truck they
# drove, into `fuel_stops`. Habits are worked out from these rows when the dashboard asks.
import logging
from datetime import datetime, timedelta, timezone

from base import config, fuel
from base.fleet import mirror
from base.models import FuelReading, FuelStop
from base.sources import samsara
from base.store import db
from features.engine import habits

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
    failed = sum(r is None for r in readings.values())
    if failed > len(units) * config.HABIT_MAX_FAILED:  # Samsara down: stops without gauges must not replace good ones
        raise RuntimeError(f"No gauge readings for {failed} of {len(units)} trucks")
    readings = {unit: r or [] for unit, r in readings.items()}
    return habits.fuel_stops(lines, readings, window)


# One truck's gauge readings; None when the call failed, which leaves that truck's stops without a gauge instead of
# stopping every truck.
def _gauge(samsara_id: str, start: datetime, end: datetime) -> list[FuelReading] | None:
    try:
        return samsara.fuel_history(samsara_id, start, end)
    except Exception as error:
        log.warning("No gauge readings for Samsara vehicle %s: %r", samsara_id, error)
        return None
