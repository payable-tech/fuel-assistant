# Fuel recommendations job: every few minutes, works out where each pilot truck should fuel next (core/recommend) and
# records what its driver is told. Only LIVE_UNITS trucks get it in their own group; the test group gets a copy of all.
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import httpx

import config
import db
from core import burn, geo, habits, loads, message, no_load, outcomes, recommend
from jobs import progress
from models import (NO_LOAD_ORDER, Decision, FuelLine, Order, Recommendation, Stop, Store, StoreOnRoute, TrackPoint, Trip,
                    Truck, TruckNow, TruckWatch, UsualLevel)
from rules import RULES, truck_now
from sources import google_places, google_routes, samsara, telegram

log = logging.getLogger(__name__)
_tracks: dict[str, tuple[datetime, list[TrackPoint]]] = {}  # unit -> (kept from, GPS track), between looks (see _track)
# A service not answering or answering with an error (OSError covers a lost connection and Telegram's ConnectionError)
NETWORK_ERRORS = (httpx.HTTPError, OSError)
# The reasons of a stop told by the truck's way, not by a road: no load, or off its load's road. Such a stop is judged by
# where the truck drives (core/no_load), whatever load it has, so the two rules never call off each other's stop.
BY_WAY = ("no_load", "heading")


# The road a look goes by: its line, when it was made, how far along it the truck is, the load's stops it was made
# through, and whether it was made anew at this look.
class Road(NamedTuple):
    line: list[geo.Point]
    made_at: datetime
    mile: float
    stops: tuple
    new: bool


# Looks at every pilot truck once. One truck failing doesn't stop the others: a network failure is one log line, any
# other failure (a fault in the code) its full trace. Each truck done ticks the watchdog. Returns how many it looked at.
def run() -> int:
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        trucks = db.pilot(conn)
        orders = db.orders(conn)
        stores = db.stores(conn)
        stops = db.fuel_stops(conn)
        drivers = db.dt_drivers(conn)
        factors = db.burn_factors(conn)
        lines = db.fuel_lines(conn, since_day=(now - timedelta(days=config.RECENT_FUEL_DAYS)).date().isoformat())
    for truck in trucks:
        try:
            ids = {d.driver_id for d in drivers if d.unit == truck.unit and d.employee_status == "active"}
            usual = habits.usual_level([s for s in stops if s.driver_id in ids], config.USUAL_MIN_STOPS)
            _look(truck, [o for o in orders if o.unit == truck.unit], stores, usual, factors.get(truck.unit), lines, now)
        except NETWORK_ERRORS as error:  # its full trace for every truck filled 72 MB of log in one night's outage
            log.error("Fuel recommendation for unit %s failed: %r", truck.unit, error)
        except Exception:
            log.exception("Fuel recommendation for unit %s failed", truck.unit)
        progress.tick()  # a long pass (the first after a restart: ~25 min) is moving, not hung
    return len(trucks)


# One truck's look: its load, its fuel, its road and MPG, what became of the stop told last, and what to tell now.
def _look(truck: Truck, orders: list[Order], stores: list[Store], usual: UsualLevel | None, factor: float | None,
          lines: list[FuelLine], now: datetime) -> None:
    with db.connect() as conn:
        last = db.truck_watch(conn, truck.unit)
        told = db.open_recommendation(conn, truck.unit)
    if told and outcomes.fueled_since(truck.unit, told.made_at, lines):
        _settle(told, "fueled", now)
        told = None
    if not truck.tank_gal or truck.lat is None:
        return _save(truck, "no tank or position", last, now)
    track, found = _load(truck, orders, now)
    position = (truck.lat, truck.lng)
    toward = _toward(track, position, now, truck.gps_at)
    load = loads.pick(found, position, toward, RULES.near_mi, config.BEHIND_DEG)
    if load is None:
        return _no_load(truck, track, stores, usual, told, last, lines, now)
    order, ahead = load
    # a stop told on another load (or with none) is judged on this load's road like any (_told_now): it stands while it
    # is on his way, so a load put right in Datatruck doesn't bring a second message for the same fill
    fresh =truck.fuel_at and now - truck.fuel_at <= timedelta(minutes=config.GAUGE_FRESH_MIN)
    if not fresh:
        return _save(truck, "no fresh gauge", last, now)
    fuel_pct = _steady_fuel(truck, now)
    filling = _filling(last, fuel_pct)
    fueled_at = now if filling else (last.fueled_at if last else None)  # no new message until a fill is surely over
    if told and filling:
        _settle(told, "fueled", now)  # the gauge knows before the fuel line comes
        told = None
    road = _road(truck, order, ahead, last, now)
    _keep_trip(truck, order, road.line if road.new else None, now)
    route_mi = geo.along(road.line)[-1]
    near = geo.stores_along(road.line, stores, config.NEARBY_MI, config.ROUTE_STEP_MI)
    candidates, off_road = recommend.split_by_road(near, config.CORRIDOR_MI, config.DETOUR_ROAD_FACTOR)
    live, used = _live_mpg(truck, order, ahead, track, factor, now)
    here = _here(truck, fuel_pct, road.mile, used, usual)
    stop_mi = _stop_mile(road, ahead)
    if told:
        ended = _told_now(told, candidates + off_road, road, stop_mi, here, position, toward)
        if ended:
            _settle(told, ended, now)
            told = None
    decision = recommend.decide(here, candidates, route_mi, RULES, off_road)
    parked = recommend.parked(track, position, now - timedelta(minutes=config.PARKED_MIN), config.PARKED_MI)
    regions = tuple(recommend.regions(here, candidates, route_mi, RULES))
    if _against(road, stop_mi, position, toward) or (decision.stop and _behind(decision.stop, stop_mi, position, toward)):
        # he drives away from this road (a load he isn't driving, or the road the wrong way): never a Love's behind
        # him; the nearest ahead in his direction, as with no load. A load put right in Datatruck makes a new road.
        decision, regions = _by_way(replace(here, mile=0.0), position, toward, stores), ()
        state = "told" if told else _act(truck, order, [], replace(here, mile=0.0), decision, [], fueled_at, parked, lines, now)
    else:
        state = "told" if told else _act(truck, order, ahead, here, decision, road.line, fueled_at, parked, lines, now)
    _save(truck, state, TruckWatch(
        unit=truck.unit, at=now, state=state, order_id=order.order_id, load_id=order.load_id, road_made_at=road.made_at,
        line=road.line, route_mi=route_mi, mile=road.mile, fuel_pct=fuel_pct, forecast_mpg=here.forecast_mpg,
        cautious_mpg=here.cautious_mpg, live_mpg=live, live_used=used is not None, usual_known=usual is not None,
        usual=here.usual, regions=regions, road_stops=road.stops, fueled_at=fueled_at), now, fuel_pct)


# A truck with no load (core/no_load): once its fuel is down to the driver's usual level, the nearest Love's it can reach
# in the direction it is going, told like any stop. A stop told on a load it no longer has ends with that load; a load
# that shows up later takes over, keeping a stop told here while that stop is on the load's road.
def _no_load(truck: Truck, track: list[TrackPoint], stores: list[Store], usual: UsualLevel | None,
             told: Recommendation | None, last: TruckWatch | None, lines: list[FuelLine], now: datetime) -> None:
    if told and told.order_id != NO_LOAD_ORDER and told.reason not in BY_WAY:
        _settle(told, "load ended", now)
        told = None
    if not (truck.fuel_at and now - truck.fuel_at <= timedelta(minutes=config.GAUGE_FRESH_MIN)):
        return _save(truck, "no fresh gauge", _without_road(truck, last, now), now)
    fuel_pct = _steady_fuel(truck, now)
    filling = _filling(last, fuel_pct)
    fueled_at = now if filling else (last.fueled_at if last else None)
    if told and filling:
        _settle(told, "fueled", now)
        told = None
    here = _here(truck, fuel_pct, 0.0, None, usual)  # its average MPG: an empty truck's live MPG says little of later
    position = (truck.lat, truck.lng)
    parked = recommend.parked(track, position, now - timedelta(minutes=config.PARKED_MIN), config.PARKED_MI)
    toward = _toward(track, position, now, truck.gps_at)
    if told:
        ended = no_load.told_now(told, position, toward, here, RULES, config.DETOUR_ROAD_FACTOR)
        if ended:
            _settle(told, ended, now)
            told = None
    decision = _by_way(here, position, toward, stores, "no load", "no_load")
    state = "told" if told else _act(truck, None, [], here, decision, [], fueled_at, parked, lines, now)
    _save(truck, state, TruckWatch(unit=truck.unit, at=now, state=state, fuel_pct=fuel_pct, forecast_mpg=here.forecast_mpg,
                                   cautious_mpg=here.cautious_mpg, usual_known=usual is not None, usual=here.usual,
                                   fueled_at=fueled_at), now, fuel_pct)


# The last look without its road (a truck with no load has none): only the level it judged by and when it last fueled.
def _without_road(truck: Truck, last: TruckWatch | None, now: datetime) -> TruckWatch | None:
    return TruckWatch(truck.unit, now, last.state, fuel_pct=last.fuel_pct, fueled_at=last.fueled_at) if last else None


# The truck's GPS track and its loads that still have stops ahead, with those stops (core/loads.loads_ahead; empty: no
# load). The track reaches back to the earliest load's first GPS visit that counts, and at least LIVE_MPG_HOURS for
# the live MPG.
def _load(truck: Truck, orders: list[Order], now: datetime) -> tuple[list[TrackPoint], list[tuple[Order, list[Stop]]]]:
    orders = loads.under_way(orders, timedelta(days=config.LOAD_MAX_DAYS), now)
    window = timedelta(hours=config.VISIT_WINDOW_H)
    since = min((loads.visits_from(o, window, now) for o in orders), default=now - timedelta(hours=config.LIVE_MPG_HOURS))
    track = _track(truck, min(since, now - timedelta(hours=config.LIVE_MPG_HOURS)), now)
    return track, loads.loads_ahead(orders, track, config.STOP_REACHED_MI, window, now) if orders else []


# The direction the truck drives (compass degrees), by its last HEADING_MI of GPS driven within HEADING_MAX_MIN and
# since its last stop (a pickup or delivery can turn him around). None while it is parked or hasn't driven that far
# since: then nothing is judged by its way. `seen_at`: when `position` was read; the GPS after it is left out, as it
# runs past the position (read once a pass, the track fresh at each look: 208033's was 27 min behind, 2026-11-22).
def _toward(track: list[TrackPoint], position: geo.Point, now: datetime, seen_at: datetime | None = None) -> float | None:
    track = [p for p in track if seen_at is None or p.at <= seen_at]
    if recommend.parked(track, position, now - timedelta(minutes=config.PARKED_MIN), config.PARKED_MI):
        return None
    since = now - timedelta(minutes=config.HEADING_MAX_MIN)
    left = no_load.set_off(track, config.PARKED_MI, timedelta(minutes=config.PARKED_MIN))
    return no_load.heading(track, position, config.HEADING_MI, max(since, left) if left else since)


# The road's mile at the load's next stop: there the road may turn back (a pickup, then the way to the delivery), so
# the truck's way says nothing of the road past it.
def _stop_mile(road: Road, ahead: list[Stop]) -> float:
    return geo.mile_on(road.line, (ahead[0].lat, ahead[0].lng), road.mile)


# True when the road runs against the truck: its point ROAD_AHEAD_MI on from his mile (or the load's next stop, if
# nearer) lies behind the way he drives (a road made for a load he isn't driving starts with a U-turn; a road driven
# the wrong way). False while his way isn't known.
def _against(road: Road, stop_mi: float, position: geo.Point, toward: float | None) -> bool:
    ahead = geo.point_at(road.line, min(road.mile + config.ROAD_AHEAD_MI, stop_mi))
    return geo.behind(position, toward, ahead, RULES.near_mi, config.BEHIND_DEG)


# True when a Love's on the road before the load's next stop lies behind the truck going `toward` (one past that stop
# may rightly be behind him: the road turns back there).
def _behind(stop: StoreOnRoute, stop_mi: float, position: geo.Point, toward: float | None) -> bool:
    return stop.miles < stop_mi and geo.behind(position, toward, (stop.store.lat, stop.store.lng), RULES.near_mi,
                                               config.BEHIND_DEG)


# The nearest Love's ahead in the truck's direction, once its fuel is down to the driver's usual level (core/no_load):
# for a truck with no load, and for one driving away from its load's road (`label` and `reason` say which).
def _by_way(here: TruckNow, position: geo.Point, toward: float | None, stores: list[Store],
            label: str = "off its road", reason: str = "heading") -> Decision:
    ahead = [] if toward is None else no_load.loves_ahead(position, toward, stores, config.AHEAD_CONE_DEG,
                                                          config.DETOUR_ROAD_FACTOR)
    return no_load.decide(here, toward, ahead, RULES, label, reason)


# True when the gauge rose like a fill since the last look: the truck is fueling, told or not.
def _filling(last: TruckWatch | None, fuel_pct: float) -> bool:
    return bool(last and last.fuel_pct is not None and fuel_pct - last.fuel_pct >= config.FILL_RISE_PCT)


# How the truck runs now (see _live), and that same figure again when the rules may count on it: not while the truck
# runs empty (a pickup ahead or just made, core/loads), as it says nothing of the loaded road ahead (None then).
def _live_mpg(truck: Truck, order: Order, ahead: list[Stop], track: list[TrackPoint], factor: float | None,
              now: datetime) -> tuple[float | None, float | None]:
    live = _live(truck, factor, track, now)
    empty = loads.empty_lately(order, ahead, track, config.STOP_REACHED_MI, timedelta(hours=config.LIVE_MPG_HOURS), now)
    return live, None if empty else live


# The truck as the rules see it now: the MPG expected and the cautious MPG from its average and its `live` MPG, if any.
def _here(truck: Truck, fuel_pct: float, mile: float, live: float | None, usual: UsualLevel | None) -> TruckNow:
    average = truck.mpg or config.DEFAULT_MPG
    return truck_now(fuel_pct, mile, truck.tank_gal, burn.forecast_mpg(average, live),
                     burn.cautious_mpg(average, live, RULES.worse), usual)


# What becomes of the stop told, judged by the rule that told it: one told by the truck's way as core/no_load judges
# it; one told on the road is "passed" once it lies behind him (unless it is past the load's next stop, where the road
# turns back: `stop_mi`), else judged on the road (core/recommend.told_now). None while it stands.
def _told_now(told: Recommendation, candidates: list[StoreOnRoute], road: Road, stop_mi: float, here: TruckNow,
              position: geo.Point, toward: float | None) -> str | None:
    if told.reason in BY_WAY:
        return no_load.told_now(told, position, toward, replace(here, mile=0.0), RULES, config.DETOUR_ROAD_FACTOR)
    stop = recommend.told_stop(told, candidates, road.line, road.mile, config.TRUCK_STOP_OFF_MI, config.ROUTE_STEP_MI)
    before_stop = stop is None or stop.miles < stop_mi
    if before_stop and told.lat is not None and geo.behind(position, toward, (told.lat, told.lng), RULES.near_mi,
                                                           config.BEHIND_DEG):
        return "passed"
    return recommend.told_now(told, stop, here, road.new, RULES)


# Acts on the rules' decision when no stop told stands: a stop or an emergency is told, unless now is the wrong moment
# for it (core/recommend.quiet; "parked" or "skipped" while that is why). An emergency is only shown as the truck's
# state while the low-fuel message is switched off (config.LOW_FUEL_ALARM). Returns the truck's state. A truck with no
# load has no `order`, stops `ahead` or road `line`.
def _act(truck: Truck, order: Order | None, ahead: list[Stop], here: TruckNow, d: Decision, line: list[geo.Point],
         fueled_at: datetime | None, parked: bool, lines: list[FuelLine], now: datetime) -> str:
    if d.kind not in ("stop", "urgent"):
        return d.kind
    if d.kind == "urgent" and not config.LOW_FUEL_ALARM:
        return "urgent"
    passed = _passed(truck, fueled_at, lines, now)
    if recommend.quiet(here, d, fueled_at, now, RULES, parked, passed):
        return "parked" if parked else "skipped" if recommend.skipped(d, passed, RULES) else "watch"
    _tell(truck, order, ahead, here, d, line, now)
    return d.kind


# How many stops told on this tank the driver drove past: those told since its last fill-up, seen by the gauge
# (`fueled_at`) or bought (`lines`), and no further back than the days the purchases are read for.
def _passed(truck: Truck, fueled_at: datetime | None, lines: list[FuelLine], now: datetime) -> int:
    fills = [t for t in (fueled_at, outcomes.last_fill(truck.unit, lines)) if t]
    since = max([*fills, now - timedelta(days=config.RECENT_FUEL_DAYS)])
    with db.connect() as conn:
        return db.passed_stops(conn, truck.unit, since)


# Keeps the load as a trip for the Recommend tab's history: started at its first look, ended at its last, with the latest
# road (passed only when made anew, thinned like the map's).
def _keep_trip(truck: Truck, order: Order, line: list[geo.Point] | None, now: datetime) -> None:
    stops = tuple((s.kind, s.city, s.state, s.lat, s.lng) for s in order.stops)
    with db.connect() as conn:
        db.save_trip(conn, Trip(truck.unit, order.order_id, order.load_id, stops, now, now,
                                geo.thin(line, config.MAP_STEP_MI) if line else None))


# The truck's GPS track from `since` to now: the one kept from earlier looks, topped up with only the points since its
# last, or fetched whole when it doesn't reach back that far (the first look, or a load that starts earlier).
def _track(truck: Truck, since: datetime, now: datetime) -> list[TrackPoint]:
    kept_from, kept = _tracks.get(truck.unit, (now, []))
    if kept_from <= since and kept:
        new = samsara.gps_history(truck.samsara_id, kept[-1].at, now)
        track = kept + [p for p in new if p.at > kept[-1].at]
    else:
        track = samsara.gps_history(truck.samsara_id, since, now)
    track = geo.thin_track([p for p in track if p.at >= since], config.LINE_STEP_MI)
    _tracks[truck.unit] = (since, track)
    return track


# The road in force: kept while the load, its stops and the truck's way stay the same; made anew from where the truck is
# for a new load, when the load's stops ahead change in Datatruck, or when it left the road (at most every REROUTE_MIN).
def _road(truck: Truck, order: Order, ahead: list[Stop], last: TruckWatch | None, now: datetime) -> Road:
    position = (truck.lat, truck.lng)
    stops = tuple((s.lat, s.lng) for s in ahead)
    if last and last.order_id == order.order_id and last.line:
        made_for = last.road_stops or stops  # a road saved before its stops were kept: taken as made for these
        line = list(last.line)
        # near the road ahead of the truck, not the miles behind it: driven back along them, it has gone another way
        # (its mile can't go back, 9606 was told "11 mi" for a Love's 88 mi off, 2026-11-16)
        from_mi = (last.mile or 0.0) - config.OFF_ROAD_MI
        on_road = min(geo.miles(p, position) for p, m in zip(line, geo.along(line)) if m >= from_mi) <= config.OFF_ROAD_MI
        if not loads.same_stops(stops, made_for):
            log.info("Unit %s: the load's stops ahead changed in Datatruck, new road", truck.unit)
        elif on_road or now - last.road_made_at < timedelta(minutes=config.REROUTE_MIN):
            return Road(line, last.road_made_at, geo.mile_on(line, position, last.mile or 0.0), made_for, new=False)
    line = google_routes.route([position, *stops])
    return Road(geo.thin(line, config.LINE_STEP_MI), now, 0.0, stops, new=True)


# The fuel now, calmed (core/burn); just the newest reading when the history can't be had.
def _steady_fuel(truck: Truck, now: datetime) -> float:
    span, lookback = timedelta(minutes=config.GAUGE_STEADY_MIN), timedelta(minutes=config.GAUGE_LOOKBACK_MIN)
    try:
        readings = samsara.fuel_history(truck.samsara_id, now - lookback, now)
    except Exception as error:
        log.warning("No gauge history for unit %s: %r", truck.unit, error)
        return truck.fuel_pct
    steady = burn.steady_gauge(readings, now, span, lookback, config.GAUGE_MIN_READINGS, config.FILL_RISE_PCT)
    return truck.fuel_pct if steady is None else steady


# How the truck runs now: its miles over the last hours against its engine meter. None without a factor or engine data.
def _live(truck: Truck, factor: float | None, track: list[TrackPoint], now: datetime) -> float | None:
    if not factor:
        return None
    start = now - timedelta(hours=config.LIVE_MPG_HOURS)
    recent = [(p.lat, p.lng) for p in track if p.at >= start]
    if len(recent) < 2:
        return None
    try:
        history = samsara.engine_history(truck.samsara_id, start, now)
    except Exception as error:
        log.warning("No engine data for unit %s: %r", truck.unit, error)
        return None
    return burn.live_mpg(burn.meter(history), factor, geo.along(recent)[-1], start, now, config.LIVE_MIN_MILES, config.MPG_RANGE)


# Records what the driver is told now, sends it to their group if the truck is live, and copies it to the test group.
def _tell(truck: Truck, order: Order | None, ahead: list[Stop], here: TruckNow, d: Decision, line: list[geo.Point], now: datetime) -> None:
    if d.kind == "urgent":  # no Love's in reach: the nearest real truck stop takes over if Google finds one before the next
        d = _with_backup(here, d, line)
    rec = message.record(truck, order, here, d, now)
    with db.connect() as conn:
        rec = replace(rec, rec_id=db.add_recommendation(conn, rec))
    log.info("Tell unit %s: %s", truck.unit, rec.text.replace("\n", " "))
    body = message.html_text(here, d, _link(d, ahead, line, here.mile))
    if send_to_driver(truck, body):
        rec = replace(rec, sent_at=datetime.now(timezone.utc))
        with db.connect() as conn:
            db.mark_sent(conn, rec.rec_id, rec.sent_at)
    copy_to_test_group(rec, body)


# Sends a message to the truck's own driver group: only for a truck the user put live, and never to the test group. True
# when it went out; a failed send is logged and the recommendation stays recorded as not sent.
def send_to_driver(truck: Truck, body: str) -> bool:
    if truck.unit not in config.LIVE_UNITS or not truck.chat_id or truck.chat_id == config.TEST_CHAT_ID:
        return False
    try:
        telegram.send(truck.chat_id, body)
    except Exception as error:
        log.warning("Sending to unit %s's group failed: %r", truck.unit, error)
        return False
    log.info("Sent to unit %s's group", truck.unit)
    return True


# The link of a message: from the phone through the fuel stop to the load's last stop (the load's other stops on the way).
def _link(d: Decision, ahead: list[Stop], line: list[geo.Point], mile: float) -> str | None:
    load = [(geo.mile_on(line, (s.lat, s.lng), mile), (s.lat, s.lng)) for s in ahead if s.lat is not None]
    return message.road_link(message.link_points([s for s in (d.stop, d.then) if s], load, config.LINK_MAX_VIA))


# Sends a copy of a recommendation to the test group, and only there: never when that chat is a truck's own group. A send
# that fails is only logged: the recommendation is recorded either way.
def copy_to_test_group(rec: Recommendation, body: str | None = None) -> None:
    if not config.TEST_CHAT_ID:
        return
    with db.connect() as conn:
        if any(t.chat_id == config.TEST_CHAT_ID for t in db.fleet(conn)):
            log.error("TEST_CHAT_ID is a truck's own group: nothing sent")
            return
    try:
        telegram.send(config.TEST_CHAT_ID, message.test_copy(rec, body))
    except Exception as error:
        log.warning("The test group copy failed: %r", error)


# The urgent decision with the nearest real truck stop in range, found by Google, in place of a Love's further on
# (core/recommend.with_backup). A search that fails leaves the decision as it was.
def _with_backup(here: TruckNow, d: Decision, line: list[geo.Point]) -> Decision:
    ahead = recommend.in_range(here, line)
    if len(ahead) < 2:
        return d
    try:
        found = geo.stores_along(ahead, google_places.truck_stops_along(ahead), config.TRUCK_STOP_OFF_MI, config.ROUTE_STEP_MI)
    except Exception as error:
        log.warning("Truck stop search failed: %r", error)
        return d
    return recommend.with_backup(here, d, found, RULES)


# Closes a recommendation.
def _settle(rec: Recommendation, status: str, now: datetime) -> None:
    with db.connect() as conn:
        db.settle_recommendation(conn, rec.rec_id, status, now)


# Saves the truck's row: the full look with its steady fuel, or just its new state on top of what was known. A look
# that couldn't judge the fuel (no fresh gauge) keeps the level the last full look judged by, so a fill-up in between
# shows as a rise at the next full look. Before, Samsara's newest reading was saved as known: 4482's 98% came late
# (truck off at the pump, Joplin, 2026-11-11), the next look saw no rise, and its stop told stayed open on a full tank.
def _save(truck: Truck, state: str, watch: TruckWatch | None, now: datetime, fuel_pct: float | None = None) -> None:
    if fuel_pct is None:
        fuel_pct = watch.fuel_pct if watch and watch.fuel_pct is not None else truck.fuel_pct
    row = replace(watch, state=state, at=now, fuel_pct=fuel_pct) if watch else TruckWatch(truck.unit, now, state, fuel_pct=fuel_pct)
    with db.connect() as conn:
        db.save_truck_watch(conn, row)
