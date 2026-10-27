# Tank helper job: estimates each pilot truck's tank size from its recent fill-ups into `tank_estimates`.
from datetime import datetime, timedelta, timezone

import config
import db
from core import tank
from jobs import mirror
from models import TankEstimate
from sources import samsara


# Replaces the estimates. Returns True when they were refreshed (a failure keeps the previous ones).
def run() -> bool:
    return mirror.refresh("Tank estimates", estimates, db.replace_tank_estimates)


# Estimates every pilot truck it can; one without enough clear fill-ups is left out, so it shows in `holes`.
def estimates() -> list[TankEstimate]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=config.TANK_DAYS)
    with db.connect() as conn:
        trucks = db.pilot(conn)
        lines = db.fuel_lines(conn, since_day=start.date().isoformat())
    found = []
    for truck in trucks:
        readings = samsara.fuel_history(truck.samsara_id, start, end)
        estimate = tank.estimate(truck.unit, [line for line in lines if line.unit == truck.unit], readings,
                                 timedelta(minutes=config.TANK_WINDOW_MIN), config.TANK_MIN_RISE_PCT,
                                 config.TANK_MIN_FILLS)
        if estimate:
            found.append(estimate)
    return found
