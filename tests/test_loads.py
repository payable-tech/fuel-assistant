# Tests which of a truck's active orders counts as its current load, and which of its stops are still ahead.
from datetime import datetime, timedelta, timezone

from core.loads import current_order, next_load, stops_ahead
from models import Order, Stop, TrackPoint


# An order with a pickup on an October day (None = no pickup time).
def order(order_id: int, status: str, pickup_day: int | None) -> Order:
    pickup = datetime(2026, 10, pickup_day, tzinfo=timezone.utc) if pickup_day else None
    return Order(order_id, f"L-{order_id}", status, "340", pickup, ())


# The load in transit wins, even over a load with an earlier pickup.
def test_in_transit_wins():
    assert current_order([order(1, "dispatched", 18), order(2, "in_transit", 19)]).order_id == 2


# Without a load in transit, the earliest pickup is next; one without a pickup time comes last.
def test_earliest_pickup_next():
    assert current_order([order(1, "assigned", None), order(2, "dispatched", 20), order(3, "dispatched", 19)]).order_id == 3


# A truck without active orders has no current load.
def test_no_orders():
    assert current_order([]) is None


# The stops ahead are those after the last one the truck's GPS has been at, whatever Datatruck's status says.
# Stops without coordinates are left out.
def test_stops_ahead():
    stops = (Stop(1, 1, 1, "pickup", 32.7, -96.8, "Dallas", "TX"), Stop(2, 1, 2, "delivery", None, None, "X", "LA"),
             Stop(3, 1, 3, "delivery", 33.7, -84.4, "Atlanta", "GA"))
    order = Order(1, "L-1", "dispatched", "340", None, stops)
    at_pickup, far_away, at_delivery = (32.705, -96.8), (40.0, -100.0), (33.7, -84.405)
    assert [s.stop_id for s in stops_ahead(order, [], 1.0)] == [1, 3]                        # not started
    assert [s.stop_id for s in stops_ahead(order, [far_away, at_pickup], 1.0)] == [3]         # picked up
    assert stops_ahead(order, [at_pickup, at_delivery], 1.0) == []                             # delivered
    assert [s.stop_id for s in stops_ahead(order, [(32.75, -96.8)], 1.0)] == [1, 3]           # 3.5 mi off: not there


DALLAS, ATLANTA, HOUSTON = (32.7, -96.8), (33.7, -84.4), (29.8, -95.4)


# A two-stop load picked up on an October day, at noon UTC.
def load(order_id: int, status: str, day: int, frm, to) -> Order:
    stops = (Stop(order_id * 10, order_id, 1, "pickup", *frm, "A", "TX"), Stop(order_id * 10 + 1, order_id, 2, "delivery", *to, "B", "GA"))
    return Order(order_id, f"L-{order_id}", status, "340", datetime(2026, 10, day, 12, tzinfo=timezone.utc), stops)


# A GPS point at a place on an October day, at noon UTC.
def seen(place, day: int) -> TrackPoint:
    return TrackPoint(datetime(2026, 10, day, 12, tzinfo=timezone.utc), *place)


# A finished load still "in transit" in Datatruck is skipped: the next load, not yet picked up, is the one ahead.
def test_next_load_skips_finished():
    done, coming = load(1, "in_transit", 17, DALLAS, ATLANTA), load(2, "dispatched", 19, HOUSTON, DALLAS)
    order, ahead = next_load([done, coming], [seen(DALLAS, 17), seen(ATLANTA, 18)], 1.0, timedelta(hours=24),
                             datetime(2026, 10, 18, 13, tzinfo=timezone.utc))
    assert order.order_id == 2 and [s.stop_id for s in ahead] == [20, 21]  # Dallas on the 17th was the earlier load


# A visit days before a load's pickup (an earlier load at the same shipper) doesn't count as its pickup.
def test_old_visit_not_counted():
    coming = load(2, "dispatched", 19, ATLANTA, HOUSTON)
    order, ahead = next_load([coming], [seen(ATLANTA, 15)], 1.0, timedelta(hours=24),
                             datetime(2026, 10, 19, 13, tzinfo=timezone.utc))
    assert [s.stop_id for s in ahead] == [20, 21]


# Every load finished: nothing ahead.
def test_next_load_none():
    done = load(1, "in_transit", 17, DALLAS, ATLANTA)
    assert next_load([done], [seen(DALLAS, 17), seen(ATLANTA, 18)], 1.0, timedelta(hours=24),
                     datetime(2026, 10, 18, 13, tzinfo=timezone.utc)) is None
