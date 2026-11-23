# The fuel recommendation's rules (pure): where a truck should fuel next, always for a fill-up. The hard rule first (never
# plan under the reserve, MPG taken low), then the driver's own level, then money; regions look further down the road.
from dataclasses import replace
from datetime import datetime, timedelta
from math import ceil

from base import geo
from base.models import (Decision, FuelRules, Picture, Recommendation, Region, StopView, Store, StoreOnRoute, TrackPoint,
                         TruckNow, Zone)

PASSED_MI = 1  # a stop up to this far behind the truck still counts as ahead: where it is on the road is only roughly known


# What to do now: "enough" (the load's end is safely in reach), "watch" (a stop is coming, further than `look_mi`), "stop"
# (tell the driver) or "urgent" (low, and no Love's in reach any more: the job looks for a truck stop). `off_road`: the
# Love's near the road but off it, their miles counting the way there (see split_by_road), for when none on it is in reach.
def decide(truck: TruckNow, stops: list[StoreOnRoute], route_mi: float, rules: FuelRules,
           off_road: list[StoreOnRoute] = ()) -> Decision:
    if worst_pct(truck, route_mi) >= rules.reserve_pct:
        return Decision("enough")
    ahead = [s for s in stops if is_ahead(s, truck.mile)]
    reachable = [s for s in ahead if worst_pct(truck, s.miles) >= rules.last_pct]
    if not reachable:
        return _none_in_reach(truck, ahead, route_mi, rules, off_road)
    safe = [s for s in reachable if worst_pct(truck, s.miles) >= rules.reserve_pct]
    if not safe:  # the reserve is what the plan aims for, not an alarm: the next Love's, urgent only past the last
        detour = _safe_detour(truck, truck.mile, off_road, rules)  # unless one off the road keeps it
        return _detour(truck, detour, rules) if detour else _under_reserve(truck, reachable, rules)
    window = [s for s in safe if arrive_pct(truck, s.miles) <= _top(truck, rules)]
    chosen, reason = (_best(truck, window, rules), "range") if window else (safe[-1], "hard_stop")
    if _skip_is_low(truck, chosen, reachable, route_mi, rules):
        reason = "last"
    later = _safe_detour(truck, chosen.miles, off_road, rules) if reason == "last" and not window else None
    if later:  # a top-up with a full tank isn't worth a warning: that Love's is told instead, once it is close
        return _detour(truck, later, rules)
    if chosen.miles - truck.mile > rules.look_mi:
        return _go(truck, "watch", chosen, reason)
    return _go(truck, "stop", chosen, reason, fill_up(truck, chosen))


# True when skipping `chosen` means low fuel: no Love's after it is in reach, nor the load's last stop, so the driver is
# warned not to skip it. Otherwise skipping is harmless and the stop is told plainly (the user's call, 2026-11-10: "the
# next Love's would put you low" was real but could be ignored with nothing happening; 6282 passed Oklahoma City, the
# last Love's in reach, on a plain message, 2026-11-09).
def _skip_is_low(truck: TruckNow, chosen: StoreOnRoute, reachable: list[StoreOnRoute], route_mi: float,
                 rules: FuelRules) -> bool:
    return chosen.miles >= reachable[-1].miles and worst_pct(truck, route_mi) < rules.last_pct


# The first Love's off the road past `after_mi` that the truck reaches with the reserve kept; None without one. Worth
# waiting for instead of a "last Love's" top-up with a near-full tank, and better than a Love's on the road reached
# under the reserve (14734 was told "last Love's" at Sonora TX at 80%, with Love's Albuquerque 5 mi off its road
# 605 mi on in reach, 2026-11-17; the user's go, 2026-11-18).
def _safe_detour(truck: TruckNow, after_mi: float, off_road: list[StoreOnRoute], rules: FuelRules) -> StoreOnRoute | None:
    return next((s for s in off_road if s.miles > after_mi and is_ahead(s, truck.mile)
                 and worst_pct(truck, s.miles) >= rules.reserve_pct), None)


# A fill-up at a Love's off the road, told once it is within `look_mi`.
def _detour(truck: TruckNow, stop: StoreOnRoute, rules: FuelRules) -> Decision:
    kind = "stop" if stop.miles - truck.mile <= rules.look_mi else "watch"
    return _go(truck, kind, stop, "detour", fill_up(truck, stop))


# No Love's on the road in reach any more: nothing to do while the load's last stop still is; the nearest Love's a few
# miles off the road that is in reach, for a fill-up ("detour"); a long stretch without a Love's to watch while there is
# plenty of fuel; else urgent, naming the next Love's if one is ahead.
def _none_in_reach(truck: TruckNow, ahead: list[StoreOnRoute], route_mi: float, rules: FuelRules,
                   off_road: list[StoreOnRoute]) -> Decision:
    if worst_pct(truck, route_mi) >= rules.last_pct:
        return Decision("enough")
    # before low fuel: 540201 was sent to city gas stations with Love's Ingalls IN 8 mi off its road in reach (2026-11-05)
    detour = [s for s in off_road if is_ahead(s, truck.mile) and worst_pct(truck, s.miles) >= rules.last_pct]
    if detour:
        return _detour(truck, detour[0], rules)
    if 100 * truck.fuel_gal / truck.tank_gal > rules.urgent_pct:
        return Decision("watch", reason="no_loves")
    return _go(truck, "urgent", ahead[0], "low") if ahead else Decision("urgent", reason="low")


# Under the reserve already, with Love's still in reach: the nearest one, not the cheapest, for a fill-up ("last" when
# it is the only one left), told once it is within `look_mi`.
def _under_reserve(truck: TruckNow, reachable: list[StoreOnRoute], rules: FuelRules) -> Decision:
    chosen = reachable[0]
    kind = "stop" if chosen.miles - truck.mile <= rules.look_mi else "watch"
    return _go(truck, kind, chosen, "last" if len(reachable) == 1 else "tight", fill_up(truck, chosen))


# A decision naming a stop, with the gauge on reaching it at the MPG expected and in the worst case.
def _go(truck: TruckNow, kind: str, stop: StoreOnRoute, reason: str, gallons: float | None = None,
        then: StoreOnRoute | None = None) -> Decision:
    return Decision(kind, stop=stop, arrive_pct=arrive_pct(truck, stop.miles), worst_pct=worst_pct(truck, stop.miles),
                    gallons=gallons, then=then, reason=reason)


# The stretches of the road ahead where the truck will need fuel, from the forecast MPG: for each, where it first gets
# near the driver's level to its last safe Love's, assuming a fill-up in the middle of the last one.
def regions(truck: TruckNow, stops: list[StoreOnRoute], route_mi: float, rules: FuelRules,
            told: tuple[StoreOnRoute, float | None] | None = None) -> list[Region]:
    found, now = [], truck
    if told:
        first, now = _told_region(truck, told)
        found.append(first)
    while arrive_pct(now, route_mi) < rules.reserve_pct:
        region = _next_region(now, stops, rules)
        if region is None:
            break
        found.append(region)
        now = replace(now, fuel_gal=_fill_gal(now), mile=region.fill_mi)
    return found


# The stop told as the plan's first region, whatever the rules would pick now, and the truck as it leaves it. `told`:
# the stop and the gallons it was told to buy there (None: a fill-up).
def _told_region(truck: TruckNow, told: tuple[StoreOnRoute, float | None]) -> tuple[Region, TruckNow]:
    stop, gallons = told
    on_arrival = max(arrive_pct(truck, stop.miles), 0) / 100 * truck.tank_gal
    after = on_arrival + gallons if gallons else _fill_gal(truck)
    region = Region(from_mi=stop.miles, to_mi=stop.miles, stops=1, cheapest=station(stop), cheaper_ahead=False,
                    fill_mi=stop.miles, fill_pct=100 * after / truck.tank_gal)
    return region, replace(truck, fuel_gal=after, mile=stop.miles)


# The next stretch from `now` where the truck needs fuel: its Love's at the driver's level, the cheapest of them, whether
# a much cheaper one lies past it, and its middle one for the fill-up. None when no Love's ahead keeps the reserve.
def _next_region(now: TruckNow, stops: list[StoreOnRoute], rules: FuelRules) -> Region | None:
    ahead = [s for s in stops if s.miles > now.mile]
    reachable = [s for s in ahead if arrive_pct(now, s.miles) >= rules.reserve_pct]
    if not reachable:
        return None
    level = [s for s in reachable if arrive_pct(now, s.miles) <= _top(now, rules)]
    # the same rule as the stop itself where it can be applied; far down the road the margin hides everything, so
    # there the forecast alone says roughly where
    inside = [s for s in level if worst_pct(now, s.miles) >= rules.reserve_pct] or level or reachable[-1:]
    cheapest = min(inside, key=lambda s: s.store.net)
    later = [s for s in ahead if s.miles > inside[-1].miles and s.miles - inside[-1].miles <= rules.part_reach_mi]
    cheaper = any(s.store.net <= cheapest.store.net - rules.part_gap and s.store.retail < cheapest.store.retail for s in later)
    return Region(from_mi=inside[0].miles, to_mi=inside[-1].miles, stops=len(inside), cheapest=station(cheapest),
                  cheaper_ahead=cheaper, fill_mi=inside[len(inside) // 2].miles)


# Everything the rules see for a truck now, for the dashboard to draw: the Love's on the road, and the one off it that is
# chosen or told (a detour), if any.
def picture(truck: TruckNow, stops: list[StoreOnRoute], route_mi: float, rules: FuelRules,
            told: tuple[StoreOnRoute, float | None] | None = None, off_road: list[StoreOnRoute] = ()) -> Picture:
    top = _top(truck, rules)
    decision = decide(truck, stops, route_mi, rules, off_road)
    picked = {s.store.store_no for s in (decision.stop, told and told[0]) if s}
    shown = sorted([*stops, *(s for s in off_road if s.store.store_no in picked)], key=lambda s: s.miles)

    # What the rules make of one Love's now.
    def verdict(s: StoreOnRoute) -> str:
        if not is_ahead(s, truck.mile):
            return "passed"
        if worst_pct(truck, s.miles) < rules.last_pct:
            return "out"
        if worst_pct(truck, s.miles) < rules.reserve_pct:
            return "late"
        return "early" if arrive_pct(truck, s.miles) > top else "range"

    views = tuple(StopView(s, arrive_pct(truck, s.miles), worst_pct(truck, s.miles), verdict(s)) for s in shown)
    found = regions(truck, stops, route_mi, rules, told)
    return Picture(decision, views, tuple(found), zones(truck, found, route_mi, rules))


# The fuel zones on the road: one for the tank now, by the same numbers as the Love's verdicts, then one after each
# fill-up planned, by the forecast alone (a rough look ahead: the gauge has the say when the truck gets there).
def zones(truck: TruckNow, found: list[Region], route_mi: float, rules: FuelRules) -> tuple[Zone, ...]:
    top = _top(truck, rules)
    tank = truck.tank_gal

    # One zone from `mile` with `gal` in the tank: from the driver's level, past the reserve, to empty at `burn_mpg`.
    def zone(mile: float, gal: float, burn_mpg: float) -> Zone:
        start = mile + max(gal - top / 100 * tank, 0) * truck.forecast_mpg
        return Zone(start, mile + max(gal - rules.reserve_pct / 100 * tank, 0) * burn_mpg, mile + gal * burn_mpg)

    legs = [zone(truck.mile, truck.fuel_gal, truck.cautious_mpg)]
    for r in found:
        after = r.fill_pct if r.fill_pct is not None else truck.usual.fill_pct
        legs.append(zone(r.fill_mi, after / 100 * tank, truck.forecast_mpg))
    return tuple(z for z in legs if z.start_mi < route_mi)


# What becomes of a told stop at a new look (`stop`: where it is on the road now, None when not ahead): None while it
# stands, "passed" once driven by, "replaced" when the road was just made anew without it or it is out of reach.
def told_now(told: Recommendation, stop: StoreOnRoute | None, truck: TruckNow, road_new: bool, rules: FuelRules) -> str | None:
    urgent = told.kind == "urgent"  # told knowing the place may be out of reach: it stands till he fuels or passes it
    if urgent and told.store_no is None:
        return None  # "find the nearest truck stop" names no place to pass (it was sent on every look before, 2026-11-05)
    if stop is None:
        return "replaced" if road_new else "passed"
    return "replaced" if not urgent and not in_reach(truck, stop, rules) else None


# Where the stop told is on the road now, while it is still ahead: a Love's among the `stops` by its number, else an
# urgent message's truck stop by its place (see _truck_stop). None once driven past or off the road.
def told_stop(told: Recommendation, stops: list[StoreOnRoute], line: list[geo.Point], mile: float, off_mi: float,
              step_mi: float) -> StoreOnRoute | None:
    loves = next((s for s in stops if s.store.store_no == told.store_no and is_ahead(s, mile)), None)
    return loves or _truck_stop(told, line, mile, off_mi, step_mi)


# The truck stop an urgent message told (a Google place, not among the Love's), found on the road again within `off_mi`,
# so the message stands like any other (before, every look took it as passed and sent it again: 0226, 2026-11-03).
def _truck_stop(told: Recommendation, line: list[geo.Point], mile: float, off_mi: float, step_mi: float) -> StoreOnRoute | None:
    if told.kind != "urgent" or told.lat is None or told.lng is None:
        return None
    place = Store(told.store_no or "", "", "", told.lat, told.lng, 0.0, 0.0, "", told.station or "")
    return next((s for s in geo.stores_along(line, [place], off_mi, step_mi) if is_ahead(s, mile)), None)


# True when a fuel stop would be told at the wrong moment: less than `hold_min` after a fill was seen, with the stop
# under `near_mi` away (he's there), while the truck is `parked` (told once it moves, not hours before he gets there),
# or after he drove past `passed` stops told on this tank (see skipped). Low fuel is always told: urgent, under the
# reserve (the last Love's in reach then too, and a no-load truck's nearest Love's). The last Love's in reach with the
# reserve still kept waits like any stop, but is told however many he drove past.
def quiet(here: TruckNow, d: Decision, fueled_at: datetime | None, now: datetime, rules: FuelRules,
          parked: bool = False, passed: int = 0) -> bool:
    if d.kind != "stop" or d.reason not in ("range", "hard_stop", "detour", "last", "no_load", "heading"):
        return False
    if d.reason in ("last", "no_load", "heading") and (d.worst_pct is None or d.worst_pct < rules.reserve_pct):
        return False
    # the fill may still be going on: 14755 got its stop again at the pump, 2026-11-04
    just_fueled = fueled_at is not None and now - fueled_at < timedelta(minutes=rules.hold_min)
    return just_fueled or d.stop.miles - here.mile < rules.near_mi or parked or skipped(d, passed, rules)


# True when a plain fuel stop comes after the driver drove past `passed` stops told on this tank, and that is the limit:
# one more is noise (of 23 third-or-later messages, 1 was followed; the user's go, 2026-11-11). The nearest Love's ahead
# (no load, or off the load's road) is a plain stop too. The last Love's in reach, a detour, low fuel and the emergency
# are not: those are still told.
def skipped(d: Decision, passed: int, rules: FuelRules) -> bool:
    return d.kind == "stop" and d.reason in ("range", "hard_stop", "no_load", "heading") and passed >= rules.max_passed


# True when the truck moved less than `moved_mi` from where its GPS had it at `since` to `position` now: parked (a
# break, a dock), not on its way. False when the track doesn't reach back that far: it can't tell, so the stop is told.
def parked(track: list[TrackPoint], position: geo.Point, since: datetime, moved_mi: float) -> bool:
    before = [p for p in track if p.at <= since]
    return bool(before) and geo.miles((before[-1].lat, before[-1].lng), position) < moved_mi


# The Love's found within the nearby distance of the road, split into those on it (within `corridor_mi`) and those off
# it, each off one's miles counting the way there (straight-line miles off the road times `road_factor`), nearest first.
def split_by_road(near: list[StoreOnRoute], corridor_mi: float,
                  road_factor: float) -> tuple[list[StoreOnRoute], list[StoreOnRoute]]:
    on = [s for s in near if s.off_mi <= corridor_mi]
    off = [replace(s, miles=s.miles + s.off_mi * road_factor) for s in near if s.off_mi > corridor_mi]
    return on, sorted(off, key=lambda s: s.miles)


# The road ahead the truck can still drive on the fuel it has, at the MPG expected: where a truck stop is looked for
# when no Love's can be counted on.
def in_range(here: TruckNow, line: list[geo.Point]) -> list[geo.Point]:
    reach = here.mile + here.fuel_gal * here.forecast_mpg
    return [p for p, m in zip(line, geo.along(line)) if here.mile <= m <= reach]


# The urgent decision with the nearest truck stop in range (`found`: those along `in_range`, miles from its start) in
# place of a Love's further on: buy there just enough to reach that Love's, and fill up at it. Unchanged without one.
def with_backup(here: TruckNow, d: Decision, found: list[StoreOnRoute], rules: FuelRules) -> Decision:
    if not found:
        return d
    near = replace(found[0], miles=found[0].miles + here.mile)
    if d.stop and d.stop.miles <= near.miles:
        return d
    gallons, then = backup_amount(here, near, d.stop, rules)  # d.stop: the next Love's, out of reach for now
    return replace(d, stop=near, arrive_pct=arrive_pct(here, near.miles), worst_pct=worst_pct(here, near.miles),
                   gallons=gallons, then=then)


# The Love's a part fill is to be followed by (its store number): the one the stop told named, else the one the rules
# would name now.
def then_of(told: Recommendation | None, seen: Picture) -> str | None:
    if told:
        return next((v.stop.store.store_no for v in seen.views if station(v.stop) == told.then_station), None)
    return seen.decision.then.store.store_no if seen.decision.then else None


# True while a stop is still ahead of a truck at `mile` of the road (not driven past).
def is_ahead(stop: StoreOnRoute, mile: float) -> bool:
    return stop.miles >= mile - PASSED_MI


# True while the stop already told can still be reached. Dropping under the reserve isn't enough to change it: that would
# be a second message for no gain.
def in_reach(truck: TruckNow, stop: StoreOnRoute, rules: FuelRules) -> bool:
    return worst_pct(truck, stop.miles) >= rules.last_pct


# The gauge on reaching a mile of the road, at the MPG expected.
def arrive_pct(truck: TruckNow, mile: float) -> float:
    return 100 * (truck.fuel_gal - max(mile - truck.mile, 0) / truck.forecast_mpg) / truck.tank_gal


# The gauge on reaching a mile of the road if the truck burns as badly as the hard stop allows for.
def worst_pct(truck: TruckNow, mile: float) -> float:
    return 100 * (truck.fuel_gal - max(mile - truck.mile, 0) / truck.cautious_mpg) / truck.tank_gal


# The highest arrival level the driver accepts: his usual level plus a little, within his own range.
def _top(truck: TruckNow, rules: FuelRules) -> float:
    u = truck.usual
    return max(min(max(u.high_pct, u.usual_pct), u.usual_pct + rules.above_usual), rules.reserve_pct)


# The stop that saves the company the most against the one nearest his usual level, on a full fill; below his range
# counts against it (he doesn't like running that low).
def _best(truck: TruckNow, window: list[StoreOnRoute], rules: FuelRules) -> StoreOnRoute:
    usual = truck.usual.usual_pct
    reference = min(window, key=lambda s: abs(arrive_pct(truck, s.miles) - usual)).store.net

    # Dollars saved on a full fill against the reference, less the penalty for arriving under his range.
    def score(s: StoreOnRoute) -> float:
        arrive = arrive_pct(truck, s.miles)
        gallons = max(_fill_gal(truck) - arrive / 100 * truck.tank_gal, 0)
        return gallons * (reference - s.store.net) - rules.low_penalty * max(truck.usual.low_pct - arrive, 0)

    return max(window, key=score)


# The gallons a fill-up takes at a Love's `stop`, from what the truck arrives with at the MPG expected. A Love's stop is
# always a fill-up: of 12 part fills told (buy less, a much cheaper Love's is ahead), none was bought as asked, and the
# 3 drivers who stopped filled up anyway (the user's go, 2026-11-11).
def fill_up(truck: TruckNow, stop: StoreOnRoute) -> float:
    return max(_fill_gal(truck) - max(arrive_pct(truck, stop.miles), 0) / 100 * truck.tank_gal, 0)


# How much to buy at a truck stop standing in for a Love's out of reach (`then`, None when none is ahead): just enough to
# reach it from the worst-case level there, to fill up where the discount is (the user's go, 2026-11-04; no card line).
def backup_amount(truck: TruckNow, stop: StoreOnRoute, then: StoreOnRoute | None,
                  rules: FuelRules) -> tuple[float, StoreOnRoute | None]:
    on_arrival = max(worst_pct(truck, stop.miles), 0) / 100 * truck.tank_gal
    return _buy(truck, stop, then, on_arrival, rules)


# The gallons to buy at `stop` with `on_arrival` in the tank there, and the Love's to fill up at after (None: a fill-up).
# Before `then`: enough to reach it with the reserve left at the cautious MPG; a fill-up when that's hardly less.
def _buy(truck: TruckNow, stop: StoreOnRoute, then: StoreOnRoute | None, on_arrival: float,
         rules: FuelRules) -> tuple[float, StoreOnRoute | None]:
    fill = max(_fill_gal(truck) - on_arrival, 0)
    if then is None:
        return fill, None
    need = (then.miles - stop.miles) / truck.cautious_mpg + rules.reserve_pct / 100 * truck.tank_gal - on_arrival
    need = max(need, rules.part_min_gal)
    return (5 * ceil(need / 5), then) if need < fill - rules.part_margin_gal else (fill, None)  # rounded up: the reserve holds


# The gallons in the tank after the driver fills to his usual level.
def _fill_gal(truck: TruckNow) -> float:
    return truck.usual.fill_pct / 100 * truck.tank_gal


# A station as the driver says it: "Love's Dunn, NC" (another chain under its own name). Some cities come in capitals
# from the price sheet ("BIG SPRING"): those are written "Big Spring".
def station(s: StoreOnRoute) -> str:
    name = s.store.name or "Love's"
    city = s.store.city.title() if s.store.city.isupper() else s.store.city
    return f"{name} {city}, {s.store.state}"
