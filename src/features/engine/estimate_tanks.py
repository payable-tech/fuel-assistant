# Tank helper job: estimates each pilot truck's tank size from its recent fill-ups into `tank_estimates`.
import logging
from datetime import datetime, timedelta, timezone

from base.fleet import copies
from base.models import TankEstimate
from base.sources import samsara
from base.store import db
from features.engine import settings, tank

log = logging.getLogger(__name__)


# Replaces the estimates. Returns True when they were refreshed (a failure keeps the previous ones).
def run() -> bool:
    return copies.refresh("Tank estimates", estimates, db.replace_tank_estimates)


# Estimates every pilot truck it can; one without enough clear fill-ups is left out, so it shows in `holes`.
def estimates() -> list[TankEstimate]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=settings.TANK_DAYS)
    with db.connect() as conn:
        trucks = db.pilot(conn)
        lines = db.fuel_lines(conn, since_day=start.date().isoformat())
    found = []
    for truck in trucks:
        try:
            readings = samsara.fuel_history(truck.samsara_id, start, end)
        except Exception as error:  # one truck's Samsara trouble mustn't stop the others' estimates
            log.warning("No gauge history for unit %s: %r", truck.unit, error)
            continue
        estimate = tank.estimate(truck.unit, [line for line in lines if line.unit == truck.unit], readings,
                                 timedelta(minutes=settings.TANK_WINDOW_MIN), settings.TANK_MIN_RISE_PCT,
                                 settings.TANK_MIN_FILLS)
        if estimate:
            found.append(estimate)
    return found
