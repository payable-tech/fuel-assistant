# Tests which of a truck's active orders counts as its current load, and which of its stops are still ahead.
from datetime import datetime, timedelta, timezone

from base.models import Order, Stop, TrackPoint
from features.engine import loads
from features.engine.loads import current_order, loads_ahead, pick, stops_ahead


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


# A load in transit was picked up: its pickup isn't ahead even when the GPS was never there; while only dispatched, it is.
def test_in_transit_picked_up():
    stops = (Stop(1, 1, 1, "pickup", 44.55, -70.54, "Rumford", "ME"), Stop(2, 1, 2, "delivery", 40.18, -111.63, "Springville", "UT"))
    wyoming = (41.3, -110.9)
    assert [s.stop_id for s in stops_ahead(Order(1, "L-1", "in_transit", "5502", None, stops), [wyoming], 1.0)] == [2]
    assert [s.stop_id for s in stops_ahead(Order(1, "L-1", "dispatched", "5502", None, stops), [wyoming], 1.0)] == [1, 2]


DALLAS, ATLANTA, HOUSTON = (32.7, -96.8), (33.7, -84.4), (29.8, -95.4)


# A two-stop load picked up on an October day, at noon UTC.
def load(order_id: int, status: str, day: int, frm, to) -> Order:
    stops = (Stop(order_id * 10, order_id, 1, "pickup", *frm, "A", "TX"), Stop(order_id * 10 + 1, order_id, 2, "delivery", *to, "B", "GA"))
    return Order(order_id, f"L-{order_id}", status, "340", datetime(2026, 10, day, 12, tzinfo=timezone.utc), stops)


# A GPS point at a place on an October day, at noon UTC.
def seen(place, day: int) -> TrackPoint:
    return TrackPoint(datetime(2026, 10, day, 12, tzinfo=timezone.utc), *place)


# A finished load still "in transit" in Datatruck is skipped: the next load, not yet picked up, is the one ahead.
def test_loads_ahead_skip_finished():
    done, coming = load(1, "in_transit", 17, DALLAS, ATLANTA), load(2, "dispatched", 19, HOUSTON, DALLAS)
    (order, ahead), = loads_ahead([done, coming], [seen(DALLAS, 17), seen(ATLANTA, 18)], 1.0, timedelta(hours=24),
                                  datetime(2026, 10, 18, 13, tzinfo=timezone.utc))
    assert order.order_id == 2 and [s.stop_id for s in ahead] == [20, 21]  # Dallas on the 17th was the earlier load


# A visit days before a load's pickup (an earlier load at the same shipper) doesn't count as its pickup.
def test_old_visit_not_counted():
    coming = load(2, "dispatched", 19, ATLANTA, HOUSTON)
    (order, ahead), = loads_ahead([coming], [seen(ATLANTA, 15)], 1.0, timedelta(hours=24),
                                  datetime(2026, 10, 19, 13, tzinfo=timezone.utc))
    assert [s.stop_id for s in ahead] == [20, 21]


# Every load finished: nothing ahead.
def test_loads_ahead_none():
    done = load(1, "in_transit", 17, DALLAS, ATLANTA)
    assert loads_ahead([done], [seen(DALLAS, 17), seen(ATLANTA, 18)], 1.0, timedelta(hours=24),
                       datetime(2026, 10, 18, 13, tzinfo=timezone.utc)) == []


# Live MPG doesn't count while the truck runs empty: a pickup still ahead, or at its pickup less than `settle` ago.
def test_empty_lately():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    pickup = Stop(1, 1, 1, "pickup", 30.0, -97.0, "A", "TX")
    delivery = Stop(2, 1, 2, "delivery", 31.0, -97.0, "B", "TX")
    order = Order(1, "L", "in_transit", "340", now, (pickup, delivery))
    settle = timedelta(hours=3)
    assert loads.empty_lately(order, [pickup, delivery], [], 1.0, settle, now)
    an_hour_ago = [TrackPoint(at=now - timedelta(hours=1), lat=30.0, lng=-97.0)]
    assert loads.empty_lately(order, [delivery], an_hour_ago, 1.0, settle, now)
    long_ago = [TrackPoint(at=now - timedelta(hours=5), lat=30.0, lng=-97.0)]
    assert not loads.empty_lately(order, [delivery], long_ago, 1.0, settle, now)


# Stops reached drop off the front and the road still fits; a stop added, moved or dropped means a new road.
def test_same_stops():
    road = [(40.0, -82.0), (38.0, -85.0), (29.8, -95.4)]
    assert loads.same_stops(road[1:], road) and loads.same_stops(road, road)
    assert loads.same_stops([(38.00004, -85.00004), road[2]], road)  # the same place, a few metres off
    assert not loads.same_stops(road + [(30.0, -97.0)], road)          # a stop added
    assert not loads.same_stops([road[0], (38.5, -85.0), road[2]], road)  # a stop moved
    assert not loads.same_stops([road[0], road[2]], road)               # a stop dropped


# A load picked up more than the limit ago is over whatever Datatruck shows; one without a pickup time is kept.
def test_under_way():
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    old, recent, unknown = order(1, "in_transit", 6), order(2, "in_transit", 30), order(3, "assigned", None)
    assert [o.order_id for o in loads.under_way([old, recent, unknown], timedelta(days=10), now)] == [2, 3]


# The load to judge by is the first whose next stop isn't behind the truck: Datatruck still shows the old load in transit
# (its delivery behind him) while the one he drives was added (ahead): that one takes over. With his way unknown, or
# one load only, the first (the road check takes it from there).
def test_pick_prefers_a_load_ahead():
    here, west, east = (30.0, -97.0), (30.0, -99.0), (30.0, -95.0)
    old = (load(1, "in_transit", 17, DALLAS, west), [Stop(11, 1, 2, "delivery", *west, "B", "TX")])
    new = (load(2, "dispatched", 19, DALLAS, east), [Stop(21, 2, 2, "delivery", *east, "B", "TX")])
    assert pick([old, new], here, 90, 2, 135)[0].order_id == 2       # driving east: the load ahead
    assert pick([old, new], here, None, 2, 135)[0].order_id == 1     # way unknown: the one in transit
    assert pick([old], here, 90, 2, 135)[0].order_id == 1
    assert pick([], here, 90, 2, 135) is None
