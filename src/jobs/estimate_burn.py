# Engine fuel factors job: calibrates each pilot truck's engine as a fuel meter (core/burn) from its recent gauge
# drops, into `burn_factors`. A truck without enough clear stretches gets none: its live MPG just stays unknown.
import logging
from datetime import datetime, timedelta, timezone

import config
import db
from core import burn
from jobs import mirror
from models import BurnFactor
from sources import samsara

log = logging.getLogger(__name__)


# Replaces the factors. Returns True when they were refreshed (a failure keeps the previous ones).
def run() -> bool:
    return mirror.refresh("Engine fuel factors", factors, db.replace_burn_factors)


# Calibrates every pilot truck with a known tank (two Samsara calls per truck).
def factors() -> list[BurnFactor]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=config.BURN_DAYS)
    with db.connect() as conn:
        trucks = db.pilot(conn)
    found = []
    for truck in trucks:
        if not truck.tank_gal:
            continue
        try:
            history = samsara.engine_history(truck.samsara_id, start, end)
            gauge = samsara.fuel_history(truck.samsara_id, start, end)
        except Exception as error:  # one truck's Samsara trouble mustn't stop the others' factors
            log.warning("No engine or gauge history for unit %s: %r", truck.unit, error)
            continue
        got = burn.gal_per_unit(burn.meter(history), history, gauge, truck.tank_gal, config.BURN_STRETCH_MI,
                                config.FILL_RISE_PCT, config.BURN_MIN_STRETCHES)
        if got:
            found.append(BurnFactor(unit=truck.unit, gal_per_unit=got[0], stretches=got[1]))
    return found
