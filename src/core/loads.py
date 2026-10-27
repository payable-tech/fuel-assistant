# Loads (pure): which of a truck's active Datatruck orders is the one it is working on now, and where it still goes.
from datetime import datetime, timedelta, timezone

from core import geo
from models import Order, Stop, TrackPoint

NO_PICKUP = datetime.max.replace(tzinfo=timezone.utc)  # an order without a pickup time sorts last


# The truck's current load by Datatruck alone: the one in transit, else the earliest pickup; None when it has none.
def current_order(orders: list[Order]) -> Order | None:
    return min(orders, key=_priority, default=None)


# The load the truck is working on and its stops still ahead: the first of its loads (in transit first, then by
# pickup) with a stop ahead, so a finished load that Datatruck still shows as active doesn't hide the next one.
# For each load only GPS points from `window` before its pickup count. None when nothing is ahead.
def next_load(orders: list[Order], track: list[TrackPoint], reached_mi: float, window: timedelta,
              now: datetime) -> tuple[Order, list[Stop]] | None:
    for order in sorted(orders, key=_priority):
        since = visits_from(order, window, now)
        ahead = stops_ahead(order, [(p.lat, p.lng) for p in track if p.at >= since], reached_mi)
        if ahead:
            return order, ahead
    return None


# When GPS visits start to count for a load: `window` before its pickup appointment (before now without one), so a
# visit to the same place on an earlier load doesn't count.
def visits_from(order: Order, window: timedelta, now: datetime) -> datetime:
    return (order.pickup_at or now) - window


# The stops the truck still has to drive to: those after the last stop its GPS `track` came within `reached_mi` of.
# Where the truck has really been decides, because Datatruck's status lags (loads stay "dispatched" after delivery)
# and its stops have no "done" mark. Stops without coordinates can't be routed and are left out (see `holes`).
def stops_ahead(order: Order, track: list[geo.Point], reached_mi: float) -> list[Stop]:
    stops = [s for s in order.stops if s.lat is not None and s.lng is not None]
    reached = [i for i, s in enumerate(stops) if any(geo.miles((s.lat, s.lng), p) <= reached_mi for p in track)]
    return stops[reached[-1] + 1:] if reached else stops


# Sort key for a truck's loads: the one in transit first, then by pickup, an order without a pickup time last.
def _priority(order: Order) -> tuple:
    return order.status != "in_transit", order.pickup_at or NO_PICKUP, order.order_id
