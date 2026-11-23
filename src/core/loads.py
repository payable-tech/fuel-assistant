# Loads (pure): which of a truck's active Datatruck orders is the one it is working on now, and where it still goes.
from datetime import datetime, timedelta, timezone

from core import geo
from models import Order, Stop, TrackPoint

NO_PICKUP = datetime.max.replace(tzinfo=timezone.utc)  # an order without a pickup time sorts last


# The truck's current load by Datatruck alone: the one in transit, else the earliest pickup; None when it has none.
def current_order(orders: list[Order]) -> Order | None:
    return min(orders, key=_priority, default=None)


# The truck's loads that still have a stop ahead, with those stops: in transit first, then by pickup, GPS points from
# `window` before each one's pickup counting. A finished load Datatruck still shows as active has none: it drops out.
def loads_ahead(orders: list[Order], track: list[TrackPoint], reached_mi: float, window: timedelta,
                now: datetime) -> list[tuple[Order, list[Stop]]]:
    found = []
    for order in sorted(orders, key=_priority):
        since = visits_from(order, window, now)
        ahead = stops_ahead(order, [(p.lat, p.lng) for p in track if p.at >= since], reached_mi)
        if ahead:
            found.append((order, ahead))
    return found


# The load the truck is working on, of those with stops ahead (`loads_ahead`, in their order): the first whose next stop
# doesn't lie behind the truck at `position` going `toward`, else the first. So when Datatruck adds the load the driver
# really drives while the old one still shows in transit, the new one takes over. None when no load has a stop ahead.
def pick(found: list[tuple[Order, list[Stop]]], position: geo.Point, toward: float | None, near_mi: float,
         behind_deg: float) -> tuple[Order, list[Stop]] | None:
    for order, ahead in found:
        if not geo.behind(position, toward, (ahead[0].lat, ahead[0].lng), near_mi, behind_deg):
            return order, ahead
    return found[0] if found else None


# The loads that can still be under way: one picked up more than `max_age` ago is over, whatever Datatruck still says
# (19727 kept a load "in transit" from Oct 6, and its GPS was read back to then on every look). No pickup time: kept.
def under_way(orders: list[Order], max_age: timedelta, now: datetime) -> list[Order]:
    return [o for o in orders if o.pickup_at is None or now - o.pickup_at <= max_age]


# When GPS visits start to count for a load: `window` before its pickup appointment (before now without one), so a
# visit to the same place on an earlier load doesn't count.
def visits_from(order: Order, window: timedelta, now: datetime) -> datetime:
    return (order.pickup_at or now) - window


# The stops the truck still has to drive to: those after the last stop its GPS `track` came within `reached_mi` of, as
# Datatruck's status lags (loads stay "dispatched" after delivery) and its stops have no "done" mark.
def stops_ahead(order: Order, track: list[geo.Point], reached_mi: float) -> list[Stop]:
    stops = [s for s in order.stops if s.lat is not None and s.lng is not None]  # can't be routed: see `holes`
    reached = [i for i, s in enumerate(stops) if any(geo.miles((s.lat, s.lng), p) <= reached_mi for p in track)]
    # a load "in transit" was picked up, even with the GPS never there (a trailer handed over elsewhere, a wrong pickup
    # address: unit 5502, 2026-11-03)
    if order.status == "in_transit" and stops and stops[0].kind == "pickup":
        reached = [0, *reached]
    return stops[reached[-1] + 1:] if reached else stops


# True while the stops ahead are still the ones a road was made through, less those reached since (they drop off the
# front). A stop added, moved or dropped in Datatruck means the road is out of date. Places compare to about 100 m.
def same_stops(ahead: list[geo.Point], made_for: list[geo.Point]) -> bool:
    now, then = [_place(p) for p in ahead], [_place(p) for p in made_for]
    return len(now) <= len(then) and now == then[len(then) - len(now):]


# A stop's place rounded to about 100 m, so the same address always compares equal.
def _place(p: geo.Point) -> tuple[float, float]:
    return round(p[0], 3), round(p[1], 3)


# True while the truck's recent MPG says nothing about the road ahead: a pickup is still ahead (it runs empty), or it
# was at its pickup less than `settle` ago (its recent hours are mostly empty ones).
def empty_lately(order: Order, ahead: list[Stop], track: list[TrackPoint], reached_mi: float, settle: timedelta,
                 now: datetime) -> bool:
    if any(s.kind == "pickup" for s in ahead):
        return True
    pickups = [(s.lat, s.lng) for s in order.stops if s.kind == "pickup" and s.lat is not None]
    visits = [p.at for p in track if any(geo.miles((p.lat, p.lng), s) <= reached_mi for s in pickups)]
    return bool(visits) and now - max(visits) < settle


# Sort key for a truck's loads: the one in transit first, then by pickup, an order without a pickup time last.
def _priority(order: Order) -> tuple:
    return order.status != "in_transit", order.pickup_at or NO_PICKUP, order.order_id
