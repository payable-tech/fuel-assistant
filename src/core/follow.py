# Following a sent plan (pure): what the truck did since the last look (a pickup or delivery reached, fuel bought at
# a planned stop or elsewhere, a planned stop driven past), the fuel on board by estimate, and folding in a re-plan
# of the rest of the road once the driver went off plan.
import re
from dataclasses import replace
from datetime import datetime, timedelta

from core import fuel, geo, route
from models import Event, Fill, FuelReading, LoadPlan, PlanStop, Progress, Stop, TrackPoint, Waypoint

SETTLE = timedelta(minutes=5)  # gauge readings this long after leaving a stop show what is in the tank


# A just-made plan's progress: nothing passed or told yet; its Love's are planned stops 1, 2, ...
def start(p: LoadPlan) -> Progress:
    return Progress(road=p, passed=0, planned=tuple(w for w in route.waypoints(p) if w.kind == "fuel"), events=())


# True once the truck has passed every waypoint of the road in force, the last delivery included.
def finished(prog: Progress) -> bool:
    return prog.passed >= len(route.waypoints(prog.road))


# What happened since the last look, from the GPS track since the plan and its fill-ups since (core/trip): a pickup
# or delivery reached, fuel bought (at planned stop n, or elsewhere), and a planned stop missed: the truck left it
# `missed_after` ago with no fuel line from it (a break at the stop doesn't count, and its fuel line may lag), or
# already `quick` ago when the `gauge` readings since leaving show it didn't fill (see _no_fill). Once the last
# delivery is reached, later fill-ups are the next load's. A fill-up whose purchases span one already told is that
# same stop: its gallons are brought up to date, not told again. Returns the progress after it and the new events,
# in time order.
def look(prog: Progress, track: list[TrackPoint], fills: list[Fill], now: datetime, reached_mi: float,
         step_mi: float, missed_after: timedelta, gauge: list[FuelReading] = (), quick: timedelta | None = None,
         rise_pct: float = 0.0) -> tuple[Progress, list[Event]]:
    points = route.waypoints(prog.road)
    driven = [t for t in track if t.at >= prog.road.made_at]
    times = route.passed_at(points, driven, reached_mi, step_mi)
    if len(times) == len(points):
        fills = [f for f in fills if f.at <= times[-1]]
    events, new = list(prog.events), []
    for f in fills:
        k = next((k for k, e in enumerate(events) if e.kind == "bought" and (f.first_at or f.at) <= e.at <= f.at), None)
        if k is None:
            new.append(_bought(f, prog.planned))
        else:  # a late line joined a stop already told
            events[k] = replace(events[k], gallons=f.gallons, billed=f.billed, pump=f.pump)
    new += [Event(w.kind, w.label, times[i]) for i, w in enumerate(points)
            if prog.passed <= i < len(times) and w.kind != "fuel"]
    settled = {e.stop_no for e in events + new if e.kind in ("bought", "missed")}
    readings = sorted(gauge, key=lambda r: r.at)
    for i, w in enumerate(points[:len(times)]):
        left = _left_at(w, driven, times[i], reached_mi) if w.kind == "fuel" else None
        if left is None or number(prog, w) in settled:
            continue
        waited = now - left
        if waited >= missed_after or (quick is not None and waited >= quick
                                      and _no_fill(readings, times[i], left, rise_pct)):
            new.append(Event("missed", w.label, left, number(prog, w)))
    new.sort(key=lambda e: e.at)
    return replace(prog, passed=len(times), events=tuple(events) + tuple(new)), new


# When the truck first reached a planned stop it has since passed with nothing told about it yet (no fuel line, not
# missed), the earliest such: from then on its gauge can tell whether it filled there. None when there is none.
def open_since(prog: Progress, track: list[TrackPoint], reached_mi: float, step_mi: float) -> datetime | None:
    points = route.waypoints(prog.road)
    times = route.passed_at(points, [t for t in track if t.at >= prog.road.made_at], reached_mi, step_mi)
    settled = {e.stop_no for e in prog.events if e.kind in ("bought", "missed")}
    return min((times[i] for i, w in enumerate(points[:len(times)])
                if w.kind == "fuel" and number(prog, w) not in settled), default=None)


# True when the gauge says the truck didn't fill at a stop: there is a reading from before it got there and one from
# SETTLE after it left (the fuel has settled in the tank), and none after leaving is `rise_pct` above the one before.
# A fill-up of even the 20-gal minimum lifts the gauge ~10%; the gauge wobbles ~3%.
def _no_fill(readings: list[FuelReading], reached: datetime, left: datetime, rise_pct: float) -> bool:
    before = [r.pct for r in readings if r.at <= reached]
    after = [r.pct for r in readings if r.at >= left + SETTLE]
    return bool(before) and bool(after) and max(after) - before[-1] < rise_pct


# The events as a message tells them: a stop told missed (or dropped) that the driver did buy at after all, its fuel
# line coming in late, reads as bought only.
def as_told(events: tuple[Event, ...]) -> list[Event]:
    bought = {e.stop_no for e in events if e.kind == "bought" and e.stop_no}
    return [e for e in events if not (e.kind in ("missed", "dropped") and e.stop_no in bought)]


# True when the driver went off plan: fuel bought away from the planned stops, or a planned stop missed.
def off_plan(events: list[Event]) -> bool:
    return any(e.kind == "missed" or (e.kind == "bought" and e.stop_no is None) for e in events)


# What the road ahead expects, counted from the fuel on board now and where the truck is on the road (`here`, miles
# along it): for each waypoint not passed yet, the fuel on arrival and, at a planned fuel stop, that stop.
def ahead(prog: Progress, fuel_gal: float, here: float) -> list[tuple[Waypoint, float, PlanStop | None]]:
    points = route.waypoints(prog.road)
    stops = dict(zip([i for i, w in enumerate(points) if w.kind == "fuel"], prog.road.plan.stops if prog.road.plan else ()))
    result, gal, mile = [], fuel_gal, here
    for i in range(prog.passed, len(points)):
        w = points[i]
        gal -= max(0.0, w.miles - mile) / prog.road.mpg
        mile = max(mile, w.miles)
        result.append((w, gal, stops.get(i)))
        gal += stops[i].gallons if i in stops else 0.0
    return result


# True when the road ahead no longer fits the fuel on board (fuel bought off plan, a stop skipped): it would arrive
# somewhere more than `slack_gal` under the reserve, or a planned fill would overflow the tank by more than that. A
# truck already under the reserve may use what it has to reach its next fuel stop, as the planner allows. It waits
# while a planned stop just passed is still open (its fuel line may not be in yet; if nothing was bought, "missed"
# comes and re-plans), and until the road is `gap` old, so a truck idling in a yard or a wobbling gauge doesn't get
# re-plan after re-plan. A road with no safe plan is tried again then if the truck would arrive under the reserve: by
# then it may be among Love's it couldn't reach from where the plan was made.
def needs_replan(prog: Progress, fuel_gal: float, here: float, reserve_gal: float, tank_gal: float,
                 slack_gal: float, now: datetime, gap: timedelta) -> bool:
    if now - prog.road.made_at < gap:
        return False
    settled = {e.stop_no for e in prog.events if e.kind in ("bought", "missed")}
    if any(w.kind == "fuel" and number(prog, w) not in settled for w in route.waypoints(prog.road)[:prog.passed]):
        return False
    expected = ahead(prog, fuel_gal, here)
    if prog.road.plan is None:
        return any(gal < reserve_gal for _, gal, _ in expected)
    low_ok = fuel_gal < reserve_gal and any(stop for _, _, stop in expected)
    for _, gal, stop in expected:
        if gal < reserve_gal - slack_gal and not low_ok:
            return True
        if stop:
            if gal + stop.gallons > tank_gal + slack_gal:
                return True
            low_ok = False  # from the first fuel stop on, the reserve holds again
    return False


# True when a re-plan stops at the same Love's, in the same order, as the road in force still does: then it only
# changes the amounts, and there is nothing new to tell the driver.
def same_stops(prog: Progress, road: LoadPlan) -> bool:
    still = [w.label for w in route.waypoints(prog.road)[prog.passed:] if w.kind == "fuel"]
    return still == [w.label for w in route.waypoints(road) if w.kind == "fuel"]


# The store numbers of the Love's the road in force still plans to stop at: what the driver was told is ahead.
def stores_ahead(prog: Progress) -> frozenset[str]:
    fuel = [i for i, w in enumerate(route.waypoints(prog.road)) if w.kind == "fuel"]
    stops = prog.road.plan.stops if prog.road.plan else ()
    return frozenset(s.store.store_no for i, s in zip(fuel, stops) if i >= prog.passed)


# The points of the driver's own route (the road's `via`) still ahead of the truck, `here` miles along the road in
# force: a re-plan keeps going through them; one the truck is within `reached_mi` of, or past, is done with.
def via_ahead(road: LoadPlan, here: float, reached_mi: float) -> tuple[geo.Point, ...]:
    return tuple(v for v in road.via if route.mile_of(road, v, 0.0) > here + reached_mi)


# The load's stops the truck hasn't reached yet on the road in force: what a re-plan has to get to.
def stops_left(prog: Progress) -> list[Stop]:
    reached = sum(1 for w in route.waypoints(prog.road)[:prog.passed] if w.kind != "fuel")
    return list(prog.road.stops_ahead[reached:])


# Folds in a re-plan of the rest of the road, made from where the truck is now: planned stops ahead that the new
# road doesn't use are dropped ("no longer needed"), its new Love's get the next numbers, and nothing of the new road
# is passed yet. A planned stop already passed is left as it is: fuel bought there may still come in, and is told as
# that stop. Returns the progress and the new events.
def replanned(prog: Progress, road: LoadPlan, now: datetime) -> tuple[Progress, list[Event]]:
    kept = {w.label for w in route.waypoints(road) if w.kind == "fuel"}
    settled = {e.stop_no for e in prog.events if e.kind in ("bought", "missed")}
    new = [Event("dropped", w.label, now, number(prog, w)) for i, w in enumerate(route.waypoints(prog.road))
           if i >= prog.passed and w.kind == "fuel" and w.label not in kept and number(prog, w) not in settled]
    new.append(Event("replanned", town(road.truck.place), now))
    known = {w.label for w in prog.planned}
    planned = prog.planned + tuple(w for w in route.waypoints(road) if w.kind == "fuel" and w.label not in known)
    return Progress(road=road, passed=0, planned=planned, events=prog.events + tuple(new)), new


# The fuel on board now: Samsara's latest gauge reading when it is at most `fresh` old and nothing was bought in the
# last `window` (right after a one-side fill a dual-tank gauge reads high); otherwise the estimate (fuel_gal).
def fuel_now(p: LoadPlan, track: list[TrackPoint], events: tuple[Event, ...], gauge_pct: float | None,
             gauge_at: datetime | None, now: datetime, window: timedelta, fresh: timedelta, thin_mi: float) -> float:
    last_buy = max((e.at for e in events if e.kind == "bought"), default=None)
    if (gauge_pct is not None and gauge_at is not None and now - gauge_at <= fresh
            and (last_buy is None or now - last_buy >= window)):
        return gauge_pct / 100 * p.truck.tank_gal
    return fuel_gal(p, track, events, thin_mi)


# The fuel on board now, by estimate: the plan's start, less the miles driven since at its MPG, plus every gallon
# bought since; never below empty or above a full tank.
def fuel_gal(p: LoadPlan, track: list[TrackPoint], events: tuple[Event, ...], thin_mi: float) -> float:
    driven = geo.along(geo.thin([(t.lat, t.lng) for t in track if t.at >= p.made_at], thin_mi))[-1]
    bought = sum(e.gallons for e in events if e.kind == "bought")
    start_gal = p.truck.fuel_pct / 100 * p.truck.tank_gal
    return max(0.0, min(p.truck.tank_gal, start_gal - driven / p.mpg + bought))


# The number a planned Love's goes by (1, 2, ...), or None for a waypoint that isn't one.
def number(prog: Progress, w: Waypoint) -> int | None:
    return next((n for n, q in enumerate(prog.planned, start=1) if q.label == w.label), None)


# The town and state of a Samsara address: "1425 Crooked Hill Road, Harrisburg, PA, 17110" -> "Harrisburg, PA".
def town(place: str | None) -> str:
    if not place:
        return "where the truck was"
    return ", ".join([part for part in place.split(", ") if not part.isdigit()][-2:])


# When the truck left waypoint `w` after reaching it at `at`: its first GPS point since then more than `reached_mi`
# away. None while it is still there (a break or a rest at the stop). A stop passed another way is left at once.
def _left_at(w: Waypoint, track: list[TrackPoint], at: datetime, reached_mi: float) -> datetime | None:
    return next((t.at for t in track if t.at >= at and geo.miles((t.lat, t.lng), (w.lat, w.lng)) > reached_mi), None)


# A fill-up as an event: at planned stop n (its planned name), or elsewhere (the station as people say it).
def _bought(f: Fill, planned: tuple[Waypoint, ...]) -> Event:
    n = _planned_no(f, planned)
    label = planned[n - 1].label if n else f"{_station(f.station)} {_name(f.city)}, {f.state}"
    return Event("bought", label, f.at, n, f.gallons, f.billed, f.pump)


# The planned stop a fill-up was made at: the planned Love's with the same store number (whatever its GPS says, which
# may have a gap). A Love's line without a number counts where its GPS place was (core/trip). Any other station is
# no planned stop, however near (a Pilot at the same exit is off plan), unless the plan sent the driver to a station
# that isn't a Love's (none was in reach): a fill-up where its GPS place was counts there.
def _planned_no(f: Fill, planned: tuple[Waypoint, ...]) -> int | None:
    if fuel.chain(f.station) != fuel.LOVES:
        n = f.plan_stop
        return n if n and not planned[n - 1].label.startswith("Love's #") else None
    store = _store_no(f.station)
    if store is None:
        return f.plan_stop
    return next((n for n, w in enumerate(planned, start=1) if _store_no(w.label) == store), None)


# The store number in a station name or a label: "LOVES #0473 TRAVEL STOP" or "Love's #473 Leary, TX" -> "473".
def _store_no(text: str) -> str | None:
    found = re.search(r"#\s*(\d+)", text)
    return (found.group(1).lstrip("0") or "0") if found else None


# A station as people say it: "LOVES #473 TRAVEL STOP" -> "Love's #473", like the planned stops; any other one
# readable as Datatruck names it ("Pilot Travel Center #452").
def _station(name: str) -> str:
    store = _store_no(name)
    if fuel.chain(name) == fuel.LOVES and store:
        return f"Love's #{store}"
    return _name(name)


# Datatruck's capital letters made readable: "PILOT TRAVEL CENTER #452" -> "Pilot Travel Center #452"; short words
# such as "TA" or "BP" stay as they are.
def _name(text: str) -> str:
    return " ".join(w if len(w) <= 3 else w.capitalize() for w in text.split())
