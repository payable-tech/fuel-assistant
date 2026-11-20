# Dashboard glue: reads the DB (and, for what a truck really did, Samsara) and returns each view's numbers as JSON-ready
# dicts. The figures themselves are worked out in core/.
import json
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import config
import db
from core import accounting, evidence, fill_checks, fuel, geo, habits, message, nearby, outcomes, recommend
from models import (FuelLine, FuelStop, Order, Picture, Recommendation, Store, StoreOnRoute, TrackPoint, Trip, Truck, TruckNow,
                    TruckWatch, Zone)
from rules import RULES, truck_now
from sources import samsara

DRIVEN_CACHE_S = 60  # a truck's road driven and gauge are asked of Samsara at most this often, however often the page asks
_driven_cache: dict[str, tuple[float, dict]] = {}  # unit -> (when built, payload)
PAST_CACHE_S = 600  # a past trip changes little: built at most this often
_past_cache: dict[tuple[str, int], tuple[float, dict]] = {}  # (unit, order) -> (when built, payload)


# Today on the company's clock (US Central), so the dashboard's days and weeks turn over at Central midnight
# whatever this PC's time zone.
def today() -> date:
    return datetime.now(fuel.CENTRAL).date()


# The Trends view: weekly numbers, breakdowns of the recent weeks, data freshness and data holes.
def baseline_payload(day: date) -> dict:
    since = (date.fromisoformat(fuel.week_of(day.isoformat())) - timedelta(weeks=config.BASELINE_WEEKS)).isoformat()
    with db.connect() as conn:
        lines = db.fuel_lines(conn, since)
        network = fuel.network_by_week(db.network_discounts(conn, since))
        linked_units = {t.unit for t in db.fleet(conn)}
        sources = _sources(conn)
        holes = Counter(row["hole"] for row in db.holes(conn))
    payload = fuel.baseline(lines, network, day, linked_units, config.BASELINE_WEEKS, config.BREAKDOWN_WEEKS)
    payload["sources"] = sources
    payload["holes"] = [{"hole": hole, "count": n} for hole, n in sorted(holes.items())]
    payload["today"] = day.isoformat()
    return payload


# The Live view: this week so far, today, the last days, the newest purchases, who bought outside Love's, the messages
# sent to drivers and the discount chart. The fuel lines are read once, from the earliest day any of these needs.
def live_payload(day: date) -> dict:
    since = day - timedelta(days=config.LIVE_DAYS + 14)  # enough for last week's same hours too
    with db.connect() as conn:
        lines = db.fuel_lines(conn, min(since.isoformat(), config.LIVE_FROM, _discount_since(since.isoformat())))
        recs = db.recommendations(conn, config.LIVE_FROM)
        sheets = db.price_sheets(conn, (since - timedelta(days=config.SHEET_MAX_AGE_DAYS)).isoformat())
        stores = {s.store_no: s for s in db.stores(conn)}
        lookups = db.fill_lookups(conn)
        sources = _sources(conn)
        jobs = [dict(row) for row in db.job_runs(conn).values()]
        problems = [_plain(p) for p in db.health_alerts(conn).values()]  # what the heartbeat found down (jobs/heartbeat)
        refreshes = [_plain(s) for s in db.source_health(conn)]  # how each source's last refresh went
    recent = _from(lines, since.isoformat())
    # the fills outside Love's: what each paid above the cheapest Love's near it
    above = {l.line_id: nearby.paid_above(l, sheets, stores, lookups, config.NEAR_MI, config.SHEET_MAX_AGE_DAYS)
             for l in recent if fuel.is_diesel(l) and not fuel.is_loves(l)}
    payload = fuel.live(recent, above, config.LIVE_FEED_SIZE, config.LIVE_DAYS, config.LIVE_OUTSIDE_LIMIT)
    payload["sources"] = sources
    payload["jobs"] = jobs
    payload["health"] = problems
    payload["source_health"] = refreshes
    payload["near_mi"] = config.NEAR_MI
    payload["plans"] = _messages_sent(recs, _from(lines, config.LIVE_FROM))  # the page reads them as "plans"
    payload["discount"] = discount_payload(lines, payload["plans"]["by_day"], payload["latest"])
    return payload


# The Live tab's discount chart: kept (the fleet on its own, the part at stops we sent, `ours` by day) and missed outside
# Love's, by day, week and month, up to the newest purchase's day (`latest`).
def discount_payload(lines: list[FuelLine], ours: dict[str, float], latest: str | None) -> dict:
    if not latest:
        return {}
    last = latest[:10]
    diesel = [l for l in _from(lines, _discount_since(last)) if fuel.is_diesel(l)]
    return {period: fuel.discount_periods(diesel, ours, last, period, n) for period, n in _discount_periods().items()}


# The discount chart's periods, and how many of each it shows.
def _discount_periods() -> dict[str, int]:
    return {"day": config.DISCOUNT_DAYS, "week": config.DISCOUNT_WEEKS, "month": config.DISCOUNT_MONTHS}


# The first day the discount chart needs when its newest purchase is on `last` ("YYYY-MM-DD"). An earlier `last` never
# needs a later day, so the live window's first day gives a safe start for the one read.
def _discount_since(last: str) -> str:
    first = {period: fuel.period_keys(last, period, n)[0] for period, n in _discount_periods().items()}
    return min(first["day"], first["week"], first["month"] + "-01")


# The fuel lines fueled on or after a local day ("YYYY-MM-DD"), as db.fuel_lines would give them.
def _from(lines: list[FuelLine], day: str) -> list[FuelLine]:
    return [l for l in lines if l.fueled_at >= day]


# The messages sent to drivers since the first one, and what came of them (core/outcomes.messages_sent), with the
# live trucks and the goal.
def _messages_sent(recs: list[Recommendation], lines: list[FuelLine]) -> dict:
    head = {"units": list(config.LIVE_UNITS), "since": config.LIVE_FROM, "target": config.LOVES_TARGET}
    return head | outcomes.messages_sent(recs, _outcomes(recs, lines), lines)


# The Drivers view: each driver's fueling habits over the last HABIT_DAYS days (pilot trucks' drivers marked), and
# every stop's gauge before and after, for the charts.
def drivers_payload() -> dict:
    with db.connect() as conn:
        stops = db.fuel_stops(conn)
        pilot_units = {t.unit for t in db.pilot(conn)}
    found = habits.habits(stops, config.RAN_LOW_PCT, config.TOP_OFF_GAL)
    return {"days": config.HABIT_DAYS, "low_pct": config.RAN_LOW_PCT, "top_off_gal": config.TOP_OFF_GAL,
            "habits": [asdict(h) | {"pilot": h.unit in pilot_units} for h in found],
            "stops": [[s.gauge_before, s.gauge_after, s.loves] for s in stops if s.gauge_before is not None]}


# The Recommend view's list: each pilot truck's latest look with the stop told, if any, and how the silent test stands.
def recommend_payload() -> dict:
    since = _shown_from().isoformat()
    with db.connect() as conn:
        watches = {w.unit: w for w in db.truck_watches(conn)}
        pilot = db.pilot(conn)
        recs = db.recommendations(conn, since)
        lines = db.fuel_lines(conn, since)
        newest_sheet = max((s.price_date for s in db.stores(conn)), default=None)
    told = {r.unit: r for r in reversed(recs) if r.status == "open"}
    came = list(_outcomes(recs, lines).values())
    return {"days": config.RECOMMEND_DAYS, "price_date": newest_sheet, "count": len(recs), "fueled": len(came),
            "live": list(config.LIVE_UNITS), "fueled_there": sum(o["there"] for o in came), "saved": sum(o["saved"] for o in came),
            "trucks": [_truck_row(t, watches.get(t.unit), told.get(t.unit)) for t in pilot]}


# One pilot truck in the list: its fuel, its state, where it is (for the map of all trucks), and where it would be told
# to go.
def _truck_row(t: Truck, watch: TruckWatch | None, told: Recommendation | None) -> dict:
    return {"unit": t.unit, "live": t.unit in config.LIVE_UNITS, "driver": t.driver, "fuel_pct": _fuel_pct(t, watch),
            "where": [t.lat, t.lng] if t.lat is not None and t.lng is not None else None, "place": t.place,
            "state": watch.state if watch else "not looked at yet",
            "load_id": watch.load_id if watch else None, "at": watch.at.isoformat() if watch else None,
            "told": told.station if told else None, "told_gallons": told.gallons if told and told.then_station else None,
            "regions": len(watch.regions) if watch else 0}


# A truck's fuel as the engine last saw it (steadied), else Samsara's latest reading.
def _fuel_pct(truck: Truck, watch: TruckWatch | None) -> float | None:
    return watch.fuel_pct if watch and watch.fuel_pct is not None else truck.fuel_pct


# One truck's plan to draw: its road, every Love's on it as the rules see them now, its regions and fuel forecast, the
# stop told, and what it would have been told so far. Without a road (no load), its place and history only.
def recommend_truck(unit: str) -> dict:
    since = _shown_from().isoformat()
    with db.connect() as conn:
        truck = _pilot(conn, unit)
        watch = db.truck_watch(conn, unit)
        stores = db.stores(conn)
        orders = db.orders(conn)
        recs = [r for r in db.recommendations(conn, since) if r.unit == unit]
        lines = db.fuel_lines(conn, since)
        stops = [s for s in db.fuel_stops(conn) if s.unit == unit]
        kept = db.trips(conn, unit, since)
    told = next((r for r in recs if r.status == "open"), None)
    came, own = _results(unit, recs, lines, stops)
    return {"unit": unit, "live": unit in config.LIVE_UNITS, "driver": truck.driver, "fuel_pct": _fuel_pct(truck, watch),
            "fuel_at": truck.fuel_at.isoformat() if truck.fuel_at else None, "tank_gal": truck.tank_gal, "place": truck.place,
            "at": [truck.lat, truck.lng] if truck.lat is not None else None,
            "state": watch.state if watch else "not looked at yet", "looked_at": watch.at.isoformat() if watch else None,
            "reserve_pct": config.RESERVE_PCT, "told": _plain(told) if told else None,
            "recommendations": [_plain(r) | {"outcome": came.get(r.rec_id)} for r in recs],
            "own_fills": [p for p in own if p["at"] >= config.RECOMMEND_FROM],
            "trips": [_trip_item(t, recs, watch) for t in kept], "road": _road_view(truck, watch, told, stores, orders)}


# The plan drawn on a truck's road: every Love's as the rules see them now, what the truck is told or would be, the fuel
# zones, and its MPG and level. None without a road (no load) or the figures to judge it by.
def _road_view(truck: Truck, watch: TruckWatch | None, told: Recommendation | None, stores: list[Store],
               orders: list[Order]) -> dict | None:
    if not watch or not watch.line or watch.fuel_pct is None or not truck.tank_gal or not watch.forecast_mpg:
        return None
    line = list(watch.line)
    here = truck_now(watch.fuel_pct, watch.mile or 0.0, truck.tank_gal, watch.forecast_mpg, watch.cautious_mpg, watch.usual)
    near = geo.stores_along(line, stores, config.NEARBY_MI, config.ROUTE_STEP_MI)
    stops, off_road = recommend.split_by_road(near, config.CORRIDOR_MI, config.DETOUR_ROAD_FACTOR)
    seen = recommend.picture(here, stops, watch.route_mi, RULES, _told_plan(told, stops + off_road, line, here.mile), off_road)
    order = next((o for o in orders if o.order_id == watch.order_id), None)
    return {"line": geo.thin(line, config.MAP_STEP_MI), "made_at": watch.road_made_at.isoformat(), "load_id": watch.load_id,
            "route_mi": watch.route_mi, "mile": here.mile, "live_mpg": watch.live_mpg, "live_used": watch.live_used,
            "forecast_mpg": here.forecast_mpg, "cautious_mpg": here.cautious_mpg, "usual": _plain(here.usual),
            "usual_known": watch.usual_known, "price_date": max((s.store.price_date for s in stops), default=None),
            "stops": _stops((s.kind, s.city, s.state, s.lat, s.lng) for s in (order.stops if order else ())),
            **_choice(here, told, seen), "told": told is not None, "look_mi": config.LOOK_MI, "corridor_mi": config.CORRIDOR_MI,
            "above_usual": config.ABOVE_USUAL_PTS,
            "loves": [_plain(v) for v in seen.views], "nearby": _nearby(off_road, here),
            "zones": [_zone(line, z) for z in seen.zones]}


# The stop told and the gallons it said to buy there (None: a fill-up), for the plan to start from; None when there is
# no stop told, or it isn't on the road ahead any more.
def _told_plan(told: Recommendation | None, stops: list[StoreOnRoute], line: list[geo.Point],
               mile: float) -> tuple[StoreOnRoute, float | None] | None:
    if not told:
        return None
    stop = recommend.told_stop(told, stops, line, mile, config.TRUCK_STOP_OFF_MI, config.ROUTE_STEP_MI)
    return (stop, told.gallons if told.then_station else None) if stop else None


# What the truck is told, or would be: the rules' decision now, then the stop told (its reason, words and part fill),
# else the rules' own pick.
def _choice(here: TruckNow, told: Recommendation | None, seen: Picture) -> dict:
    d = seen.decision
    if told:
        return {"decision": d.kind, "reason": told.reason, "would_say": told.text, "chosen": told.store_no,
                "then": recommend.then_of(told, seen)}
    return {"decision": d.kind, "reason": d.reason, "would_say": message.text(here, d) if d.kind in ("stop", "urgent") else None,
            "chosen": d.stop.store.store_no if d.stop else None, "then": recommend.then_of(None, seen)}


# A fuel zone for the map, with its safe and its risky stretch of road.
def _zone(line: list[geo.Point], z: Zone) -> dict:
    return _plain(z) | {"safe": geo.thin(geo.stretch(line, z.start_mi, z.reserve_mi), config.MAP_STEP_MI),
                        "risky": geo.thin(geo.stretch(line, z.reserve_mi, z.end_mi), config.MAP_STEP_MI)}


# A load's stops for the map, from (kind, city, state, lat, lng) each; those without a place are left out.
def _stops(stops) -> list[dict]:
    return [dict(zip(("kind", "city", "state", "lat", "lng"), s)) for s in stops if s[3] is not None]


# The Love's ahead close to the road but off it (their miles counting the way there): the rules take one only when no
# Love's on the road is in reach.
def _nearby(off_road: list[StoreOnRoute], here: TruckNow) -> list[dict]:
    return [_plain(s) | {"arrive_pct": recommend.arrive_pct(here, s.miles), "worst_pct": recommend.worst_pct(here, s.miles)}
            for s in off_road if recommend.is_ahead(s, here.mile)]


# What a truck really did lately, from Samsara: the road driven and its gauge since its road was made or its last message
# (core/outcomes.watch_from), and its fill-ups, placed where its GPS was when it paid.
def recommend_driven(unit: str) -> dict:
    cached = _driven_cache.get(unit)
    if cached and time.monotonic() - cached[0] < DRIVEN_CACHE_S:
        return cached[1]
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        truck = _pilot(conn, unit)
        watch = db.truck_watch(conn, unit)
        recs = [r for r in db.recommendations(conn, _shown_from().isoformat()) if r.unit == unit]
        start = outcomes.watch_from(watch.road_made_at if watch else None, recs, now, _within())
        since = min(start.date(), _shown_from()).isoformat()
        lines = [l for l in db.fuel_lines(conn, since) if l.unit == unit]
    track, driven = _driven(truck, start, now)
    fills = outcomes.fills(lines, track, start, now, _outcomes(recs, lines), _window())
    payload = {"since": start.isoformat(), **driven, "fills": fills}
    _driven_cache[unit] = (time.monotonic(), payload)
    return payload


# One past trip of a truck for the Recommend tab: its load, the road planned (the latest kept), what the truck really did
# over the trip (the road driven and the gauge from Samsara, its fill-ups), and the load's messages with what came of them.
def recommend_past(unit: str, order_id: int) -> dict:
    cached = _past_cache.get((unit, order_id))
    if cached and time.monotonic() - cached[0] < PAST_CACHE_S:
        return cached[1]
    with db.connect() as conn:
        truck = db.pilot_truck(conn, unit)
        trip = next((t for t in db.trips(conn, unit, "2000-01-01") if t.order_id == order_id), None) if truck else None
        if trip is None:
            raise LookupError(f"Unit {unit} has no trip for order {order_id}")
        since = (trip.started_at - timedelta(days=1)).date().isoformat()
        lines = [l for l in db.fuel_lines(conn, since) if l.unit == unit]
        recs = [r for r in db.recommendations(conn, since) if r.unit == unit]
        stops = [s for s in db.fuel_stops(conn) if s.unit == unit]
        stores = {s.store_no: s for s in db.stores(conn)}
    payload = _past(truck, trip, lines, recs, stops, stores)
    _past_cache[(unit, order_id)] = (time.monotonic(), payload)
    return payload


# A past trip as the page draws it, from what was read for it; the road driven and the gauge are asked of Samsara.
def _past(truck: Truck, trip: Trip, lines: list[FuelLine], recs: list[Recommendation], stops: list[FuelStop],
          stores: dict[str, Store]) -> dict:
    start, end = trip.started_at, trip.ended_at
    came, own = _results(truck.unit, recs, lines, stops)
    track, driven = _driven(truck, start, end)
    return {"unit": truck.unit, "order_id": trip.order_id, "load_id": trip.load_id, "started_at": start.isoformat(),
            "ended_at": end.isoformat(), "stops": _stops(trip.stops), "line": trip.line or [], "since": start.isoformat(),
            **driven, "fills": outcomes.fills(lines, track, start, end, came, _window()),
            "recommendations": [_plain(r) | {"outcome": came.get(r.rec_id), "where": _pin(r, stores)}
                                for r in recs if r.order_id == trip.order_id],
            "own_fills": [p for p in own if start <= datetime.fromisoformat(p["at"]) <= end]}


# Where a message's stop is, for its pin on the map: a Love's by its store, a truck stop by its place; None if unknown.
def _pin(rec: Recommendation, stores: dict[str, Store]) -> list | None:
    s = stores.get(rec.store_no or "")
    return [s.lat, s.lng] if s else [rec.lat, rec.lng] if rec.lat is not None else None


# What came of a truck's messages (by id) and its own fill-ups no message asked for, each with the gauge around it
# from the driver's fuel `stops` (core/outcomes.with_gauge).
def _results(unit: str, recs: list[Recommendation], lines: list[FuelLine],
             stops: list[FuelStop]) -> tuple[dict[int, dict], list[dict]]:
    found = _outcomes(recs, lines)
    came = {rec_id: outcomes.with_gauge(o, stops, _window()) for rec_id, o in found.items()}
    return came, [outcomes.with_gauge(p, stops, _window()) for p in outcomes.own_fills(unit, found, lines, _window())]


# What a truck really did between two moments, from Samsara: its GPS track, and the road driven and its gauge as the
# page draws them.
def _driven(truck: Truck, start: datetime, end: datetime) -> tuple[list[TrackPoint], dict]:
    track = samsara.gps_history(truck.samsara_id, start, end)
    gauge = samsara.fuel_history(truck.samsara_id, start, end)
    return track, {"track": geo.thin([(p.lat, p.lng) for p in track], config.MAP_STEP_MI) if track else [],
                   "gauge": [[r.at.isoformat(), r.pct] for r in gauge]}


# A trip in a truck's list: its load, from where to where, when, how many messages it got, whether it is the one now.
def _trip_item(t: Trip, recs: list[Recommendation], watch: TruckWatch | None) -> dict:
    return {"order_id": t.order_id, "load_id": t.load_id, "from": f"{t.stops[0][1]}, {t.stops[0][2]}" if t.stops else None,
            "to": f"{t.stops[-1][1]}, {t.stops[-1][2]}" if t.stops else None, "started_at": t.started_at.isoformat(),
            "ended_at": t.ended_at.isoformat(), "current": bool(watch and watch.order_id == t.order_id),
            "messages": sum(1 for r in recs if r.order_id == t.order_id and r.status != "repeat")}


# What became of each recommendation: the truck's first diesel stop after it (core/outcomes).
def _outcomes(recs: list[Recommendation], lines: list) -> dict[int, dict]:
    return outcomes.outcomes(recs, lines, _window(), _within())


# Purchases this close together are one fill-up, and a driver's stop this close to one holds its gauge.
def _window() -> timedelta:
    return timedelta(minutes=config.TANK_WINDOW_MIN)


# A purchase this soon after a message is what became of it.
def _within() -> timedelta:
    return timedelta(hours=config.RESULT_WINDOW_H)


# The first day the Recommend tab lists messages from.
def _shown_from() -> date:
    return today() - timedelta(days=config.RECOMMEND_DAYS)


# A pilot truck by its unit; LookupError (a 404 for the page) when the unit isn't one.
def _pilot(conn, unit: str) -> Truck:
    truck = db.pilot_truck(conn, unit)
    if truck is None:
        raise LookupError(f"Unit {unit} is not a test truck")
    return truck


# The Accounting view: every EFS statement read (newest first) and one of them, the newest unless another is asked
# for, as its tree of boxes and the checks on its fills (Love's prices, Samsara's evidence per fill, bought vs burned
# per truck). The Datatruck lines read are the statement's days and one either side; the Love's price sheets, its days.
def accounting_payload(statement_no: str | None) -> dict:
    with db.connect() as conn:
        statements = db.statements(conn)
        if not statements:
            return {"statements": [], "statement": None, "tree": None, "checks": None}
        read = db.statement(conn, statement_no or statements[0].statement_no)
        if read is None:
            raise LookupError(f"No EFS statement {statement_no} has been read")
        statement, lines = read
        days = sorted(l.day for l in lines) or [statement.statement_day]
        datatruck = db.fuel_lines_between(conn, fuel.shift_days(days[0], -1), fuel.shift_days(days[-1], 1))
        sheets, network = db.price_sheets(conn, days[0]), db.network_discounts(conn, days[0])
        found = accounting.match([l for l in lines if accounting.is_purchase(l)], datatruck)
        seen = db.fill_evidence(conn, [f.line_id for f in found.values()])
        burns = db.statement_burn(conn, statement.statement_no)
        samsara_ids = {t.unit: t.samsara_id for t in db.fleet(conn)}
        stores = {s.store_no: (s.lat, s.lng) for s in db.stores(conn)}
    listed = [{"statement_no": s.statement_no, "account": s.account, "statement_day": s.statement_day, "charges": s.charges}
              for s in statements]
    chosen = next(s for s in listed if s["statement_no"] == statement.statement_no) | {"first_day": days[0], "last_day": days[-1]}
    tree = accounting.tree(statement, lines, found, datatruck, config.EFS_ACCOUNTS.get(statement.account))
    checks = {"headline": fill_checks.headline(lines, found), "loves": fill_checks.loves_promise(lines, found, sheets, network),
              "fills": evidence.fills(lines, found, seen, set(samsara_ids), stores),
              "burn": evidence.bought_vs_burned(lines, found, burns, samsara_ids, seen)}
    return {"statements": listed, "statement": chosen, "tree": tree, "checks": checks}


# A dataclass as plain JSON-ready values (datetimes become ISO text).
def _plain(obj) -> dict:
    return json.loads(json.dumps(asdict(obj), default=lambda value: value.isoformat()))


# Every refreshed table with its row count and last refresh time.
def _sources(conn) -> list[dict]:
    return [{"table": t, "rows": n, "refreshed": at} for t, n, at in db.status(conn)]
