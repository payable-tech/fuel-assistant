# Fill lookups job: for each diesel fill outside Love's (its fuel line has no place), where Samsara had the truck and the
# gauge just before, looked up once into `fill_lookups`, for the Live view's "paid above the cheapest Love's nearby".
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from base import fuel, geo
from base.models import FillLookup, FuelLine, FuelReading, TrackPoint
from base.sources import samsara
from base.store import db
from features.dashboard import settings
from features.engine import gauge, settings as engine_settings

log = logging.getLogger(__name__)

SETTLE = timedelta(minutes=15)      # a fill this new waits: Samsara may not have its readings yet
GPS_WINDOW = timedelta(minutes=20)  # a fill is where the truck's GPS point nearest its time was, within this


# Looks up the fills not looked up yet. A truck whose Samsara call fails is tried again next run; a truck not in
# Samsara is never looked up.
def run() -> None:
    window = timedelta(minutes=engine_settings.TANK_WINDOW_MIN)
    settled = datetime.now(timezone.utc) - SETTLE
    with db.connect() as conn:
        done = db.fill_lookups(conn)
        lines = [l for l in db.fuel_lines(conn, settings.LOOKUPS_FROM) if fuel.is_diesel(l) and l.line_id not in done
                 and not fuel.is_loves(l) and fuel.utc(l.fueled_at) < settled]
        samsara_ids = {t.unit: t.samsara_id for t in db.fleet(conn)}
    by_unit = defaultdict(list)
    for l in lines:
        by_unit[l.unit].append(l)
    found = [f for unit, mine in by_unit.items() if unit in samsara_ids for f in _truck(samsara_ids[unit], mine, window)]
    with db.connect() as conn:
        db.add_fill_lookups(conn, found)
    log.info("Fills looked up: %d of %d waiting", len(found), len(lines))


# One truck's fills, with one Samsara gauge call for all of them; none when a Samsara call fails.
def _truck(samsara_id: str, lines: list[FuelLine], window: timedelta) -> list[FillLookup]:
    times = [fuel.utc(l.fueled_at) for l in lines]
    try:
        readings = samsara.fuel_history(samsara_id, min(times) - window, max(times))
        return [_fill(samsara_id, l, at, readings, window) for l, at in zip(lines, times)]
    except Exception as error:  # Samsara down or slow: this truck waits for the next run, the others go on
        log.warning("Fills of Samsara vehicle %s not looked up: %r", samsara_id, error)
        return []


# One fill outside Love's: the truck's GPS point nearest it and the lowest gauge reading in the window before it.
def _fill(samsara_id: str, line: FuelLine, at: datetime, readings: list[FuelReading], window: timedelta) -> FillLookup:
    near = _place(samsara_id, at)
    return FillLookup(line_id=line.line_id, lat=near.lat if near else None, lng=near.lng if near else None,
                      gauge_before=gauge.before(at, readings, window))


# Where the truck was at a moment: its GPS point nearest it in time; None when Samsara has none close.
def _place(samsara_id: str, at: datetime) -> TrackPoint | None:
    return geo.where_at(samsara.gps_history(samsara_id, at - GPS_WINDOW, at + GPS_WINDOW), at)
