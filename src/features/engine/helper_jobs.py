# The jobs that feed the engine, each on its own line of the timetable: every pilot truck's tank size and its engine's
# fuel factor (for the live MPG), every driver's fuel stops with the gauge (for his usual level), and the highway exit
# of each Love's (for the message). Each asks Samsara or Love's, runs one calculation and saves the result.
import logging
import time
from datetime import datetime, timedelta, timezone

from base import fuel
from base.fleet import copies
from base.models import BurnFactor, FuelReading, FuelStop, TankEstimate
from base.sources import loves, samsara
from base.store import db
from features.engine import habits, mpg, settings, tank

log = logging.getLogger(__name__)
MAX_FAILS = 5  # this many Love's pages in a row that can't be read: the site is down or changed, the rest waits for the next run


# Tank helper job: estimates each pilot truck's tank size from its recent fill-ups into `tank_estimates`. Returns True
# when they were refreshed (a failure keeps the previous ones).
def tank_sizes() -> bool:
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


# Engine fuel factors job: calibrates each pilot truck's engine as a fuel meter (features/engine/mpg) from its recent gauge
# drops, into `burn_factors`. A truck without enough clear stretches gets none: its live MPG just stays unknown. Returns
# True when they were refreshed (a failure keeps the previous ones).
def mpg_factors() -> bool:
    return copies.refresh("Engine fuel factors", factors, db.replace_burn_factors)


# Calibrates every pilot truck with a known tank (two Samsara calls per truck).
def factors() -> list[BurnFactor]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=settings.BURN_DAYS)
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
        got = mpg.gal_per_unit(mpg.meter(history), history, gauge, truck.tank_gal, settings.BURN_STRETCH_MI,
                               settings.FILL_RISE_PCT, settings.BURN_MIN_STRETCHES)
        if got:
            found.append(BurnFactor(unit=truck.unit, gal_per_unit=got[0], stretches=got[1]))
    return found


# Driver habits job: every driver's diesel stops of the last HABIT_DAYS days with the Samsara gauge of the truck they
# drove, into `fuel_stops`. Habits are worked out from these rows when the dashboard asks. Returns True when they were
# refreshed (a failure keeps the previous ones).
def driver_stops() -> bool:
    return copies.refresh("Driver fuel stops", _stops, db.replace_fuel_stops)


# Every driver's stops with the gauge around them (one Samsara call per truck that bought diesel).
def _stops() -> list[FuelStop]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=settings.HABIT_DAYS)
    window = timedelta(minutes=settings.TANK_WINDOW_MIN)
    with db.connect() as conn:
        lines = db.fuel_lines(conn, since_day=start.date().isoformat())
        samsara_ids = {t.unit: t.samsara_id for t in db.fleet(conn)}
    units = sorted({l.unit for l in lines if fuel.is_diesel(l) and l.unit in samsara_ids})
    readings = {unit: _gauge(samsara_ids[unit], start - window, now) for unit in units}
    failed = sum(r is None for r in readings.values())
    if failed > len(units) * settings.HABIT_MAX_FAILED:  # Samsara down: stops without gauges must not replace good ones
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


# Love's exits job: reads the own page of each Love's store not read yet (base/sources/loves) and keeps its highway and
# exit in `store_exits`, for the driver's message ("📍 In 34 mi, I-90 (Exit 34)"). A store is read once: after the first
# run (all stores, ~10 min) only new stores are. A page that can't be read is tried again at the next run. Returns how
# many were kept.
def loves_exits() -> int:
    with db.connect() as conn:
        todo = db.stores_without_exit(conn)
    kept = fails = 0
    for store_no in todo:
        try:
            way = loves.exit_of(store_no)
        except Exception as error:
            log.warning("Love's page of store %s not read: %r", store_no, error)
            fails += 1
            if fails >= MAX_FAILS:
                break
        else:
            fails = 0
            with db.connect() as conn:
                db.save_store_exit(conn, store_no, way)
            kept += 1
        time.sleep(settings.EXITS_PAUSE_SEC)
    if todo:
        log.info("Love's exits read: %d of %d stores", kept, len(todo))
    return kept
