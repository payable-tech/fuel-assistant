# Tests that the engine never tells a Love's behind the driver: a load he isn't driving (its road starts with a U-turn)
# or a stop already behind him gives way to the nearest Love's ahead in his direction, and a load put right in Datatruck
# takes over again (1767 on I-30, 2026-11-22). Whole looks of the engine, with the GPS, gauge and Google road given.
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from base import config, geo
from base.models import Order, Recommendation, Stop, Store, TrackPoint, Truck, UsualLevel
from base.store import db
from features.engine import job

AT = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
AHEAD = Store("7", "Seguin", "TX", 30.0, -96.6, 6.0, 5.5, "2026-11-22")      # ~24 mi east of the truck at -97.0
BEHIND = Store("8", "Columbus", "TX", 30.0, -97.4, 6.0, 5.5, "2026-11-22")   # ~24 mi west of it
WEST, EAST = (30.0, -100.0), (30.0, -90.0)                                   # a delivery behind him, one ahead
USUAL = UsualLevel(usual_pct=22, low_pct=15, high_pct=30, fill_pct=95, stops=20)


# A temporary database, every send caught, Google's road a straight line through the points asked (each call kept),
# the GPS track and the gauge as the test sets them: no Samsara or Google call.
@pytest.fixture
def world(tmp_path, monkeypatch):
    w = SimpleNamespace(routes=[], sends=[], track=[])
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "TEST_CHAT_ID", None)
    monkeypatch.setattr(config, "LIVE_UNITS", ("340",))
    monkeypatch.setattr(job.telegram, "send", lambda chat, text: w.sends.append(text))
    monkeypatch.setattr(job.google_routes, "route", lambda points: w.routes.append(points) or straight(points))
    monkeypatch.setattr(job, "_track", lambda truck, since, now: w.track)
    monkeypatch.setattr(job, "_steady_fuel", lambda truck, now: truck.fuel_pct)
    return w


# A road through the points as straight lines, a point about every mile.
def straight(points: list[geo.Point]) -> list[geo.Point]:
    line = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(geo.miles(a, b)))
        line += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return line + [points[-1]]


# A load in transit to one delivery.
def load(order_id: int, to: geo.Point, status: str = "in_transit") -> Order:
    return Order(order_id, f"L-{order_id}", status, "340", AT - timedelta(hours=5), (Stop(order_id, order_id, 1, "delivery", *to, "X", "TX"),))


# One look of the engine at a truck on latitude 30 at `lng`, `minutes` after AT, having driven east for the hour before
# (a point a minute, about a mile each), its gauge fresh at 20% (the driver's usual level is 22%).
def look(w, lng: float, minutes: int, orders: list[Order]) -> None:
    at = AT + timedelta(minutes=minutes)
    w.track = [TrackPoint(at - timedelta(minutes=k), 30.0, lng - k / 58) for k in range(60, -1, -1)]
    truck = Truck("340", "1", "V", "Unit 340", "Ali", 7.0, 20.0, at, 30.0, lng, None, at, 160.0, "manual", None, -100,
                  "auto", None, True)
    job._look(truck, orders, [AHEAD, BEHIND], USUAL, None, [], at)


# The truck's messages, oldest first, and its saved look.
def told() -> tuple[list[Recommendation], object]:
    with db.connect() as conn:
        return db.recommendations(conn, "2026-11-01")[::-1], db.truck_watch(conn, "340")  # listed newest first


# A load he isn't driving (its delivery behind him): the Love's behind on its road is never told; the nearest one ahead
# in his direction is, once. Four looks later it still stands: no new message, and no new road from Google.
def test_wrong_load_tells_the_loves_ahead(world):
    look(world, -97.0, 0, [load(7, WEST)])
    recs, watch = told()
    assert [(r.store_no, r.reason, r.order_id) for r in recs] == [("7", "heading", 7)] and watch.state == "stop"
    assert len(world.sends) == 1 and "About" in world.sends[0] and len(world.routes) == 1
    for k in range(1, 5):
        look(world, -97.0 + 5 * k / 58, 5 * k, [load(7, WEST)])
    recs, watch = told()
    assert len(recs) == 1 and recs[0].status == "open" and watch.state == "told"
    assert len(world.sends) == 1 and len(world.routes) == 1


# A stop told on the road that is now behind him (he drove past it, or the road was wrong) is passed, and the stop
# ahead on his road is told instead: one new message.
def test_a_told_stop_behind_him_is_passed(world):
    with db.connect() as conn:
        db.add_recommendation(conn, Recommendation(
            None, "340", "Ali", 7, "L-7", AT - timedelta(minutes=30), "stop", "8", "Love's Columbus, TX", 10.0, 20.0, 18.0,
            17.0, 120.0, None, "range", 5.5, 6.0, "2026-11-22", 7.0, 5.6, 22.0, "Fill up", "open", None, AT, BEHIND.lat,
            BEHIND.lng))
    look(world, -97.0, 0, [load(7, EAST)])
    recs, _ = told()
    assert recs[0].status == "passed"
    assert [(r.store_no, r.reason) for r in recs[1:]] == [("7", recs[1].reason)] and recs[1].reason != "heading"
    assert len(world.sends) == 1


# The load put right in Datatruck (its delivery moved to where he goes): a new road, the road's rules again; the stop
# told by his way stands, so no second message.
def test_load_put_right_takes_over(world):
    look(world, -97.0, 0, [load(7, WEST)])
    look(world, -97.0 + 5 / 58, 5, [load(7, EAST)])
    recs, watch = told()
    assert len(world.routes) == 2 and watch.road_stops == (EAST,) and watch.regions != ()
    assert len(recs) == 1 and recs[0].status == "open" and watch.state == "told" and len(world.sends) == 1


# The load he really drives added in Datatruck while the old one still shows in transit: the new one takes over.
def test_added_load_takes_over(world):
    look(world, -97.0, 0, [load(7, WEST)])
    look(world, -97.0 + 5 / 58, 5, [load(7, WEST), load(9, EAST, "dispatched")])
    recs, watch = told()
    assert watch.order_id == 9 and watch.road_stops == (EAST,) and len(world.routes) == 2
    assert len(recs) == 1 and recs[0].status == "open" and len(world.sends) == 1


# A truck driving its load's road is judged on the road as before: the stop ahead on it, told by the road's rules.
def test_truck_on_its_road_is_unchanged(world):
    look(world, -97.0, 0, [load(7, EAST)])
    recs, watch = told()
    assert [r.store_no for r in recs] == ["7"] and recs[0].reason != "heading" and watch.regions != ()


# Parked (or just off a stop), its way isn't known: the road's rules alone, as before.
def test_parked_truck_is_judged_on_the_road(world):
    look(world, -97.0, 0, [load(7, WEST)])
    world.routes.clear()
    with db.connect() as conn:
        conn.execute("DELETE FROM recommendations")
        conn.execute("DELETE FROM truck_watch")
    at = AT + timedelta(hours=2)
    world.track = [TrackPoint(at - timedelta(minutes=k), 30.0, -97.0) for k in range(60, -1, -1)]
    truck = Truck("340", "1", "V", "Unit 340", "Ali", 7.0, 20.0, at, 30.0, -97.0, None, at, 160.0, "manual", None, -100,
                  "auto", None, True)
    job._look(truck, [load(7, WEST)], [AHEAD, BEHIND], USUAL, None, [], at)
    _, watch = told()
    assert watch.state != "off its road" and not watch.state.startswith("off its road") and watch.regions != ()


# A truck that drove back along its road, far behind the mile it was last at, has left that road: a new one is made
# (its mile can't go back, so the old road would count the miles from where it was: 9606, "11 mi" for 88). Near its
# mile, the road is kept.
def test_driving_the_road_back_makes_a_new_road(world):
    line = straight([(30.0, -99.0), EAST])
    old = SimpleNamespace(order_id=7, line=line, road_stops=(EAST,), mile=100.0, road_made_at=AT - timedelta(hours=2))
    order = load(7, EAST)
    back = Truck("340", "1", "V", "Unit 340", "Ali", 7.0, 20.0, AT, 30.0, -98.6, None, AT, 160.0, "manual", None, -100,
                 "auto", None, True)                                # 70 mi back west of its mile 100
    road = job._road(back, order, list(order.stops), old, AT)
    assert road.new and len(world.routes) == 1
    near = replace(back, lng=-99.0 + 100 / 59.9)                   # at its mile 100
    road = job._road(near, order, list(order.stops), old, AT)
    assert not road.new and len(world.routes) == 1


# A stop told on the old load's road, when the load he drives takes over: it stands while it is on the new road (no
# second message for the same fill), and is replaced when it isn't.
def test_a_stop_told_on_the_old_load_is_judged_on_the_new_road(world):
    def told_on_load_8(store: Store) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM recommendations")
            conn.execute("DELETE FROM truck_watch")
            db.add_recommendation(conn, Recommendation(
                None, "340", "Ali", 8, "L-8", AT - timedelta(minutes=10), "stop", store.store_no, f"Love's {store.city}, TX",
                24.0, 20.0, 18.0, 17.0, 120.0, None, "range", 5.5, 6.0, "2026-11-22", 7.0, 5.6, 22.0, "Fill up", "open", None,
                AT, store.lat, store.lng))

    told_on_load_8(AHEAD)                                          # on the new load's road east
    look(world, -97.0, 0, [load(9, EAST)])
    recs, watch = told()
    assert [r.status for r in recs] == ["open"] and watch.state == "told" and world.sends == []
    north = Store("5", "Bastrop", "TX", 30.4, -96.9, 6.0, 5.5, "2026-11-22")
    told_on_load_8(north)                                          # 28 mi off the new road: not on his way
    look(world, -97.0, 0, [load(9, EAST)])
    recs, _ = told()
    assert recs[0].status == "replaced" and len(world.sends) == 1  # and the stop on the new road told instead


# Arriving at a pickup (268331 at Reynoldsburg, 2026-11-22): the road turns back there toward the delivery, so the Love's
# past the pickup isn't "behind" him and the road isn't wrong: judged on the road as before.
def test_arriving_at_a_pickup_the_road_may_turn_back(world):
    pickup = Stop(1, 7, 1, "pickup", 30.0, -96.95, "X", "TX")                     # 3 mi ahead of him, east
    order = Order(7, "L-7", "dispatched", "340", AT + timedelta(hours=1), (pickup, Stop(2, 7, 2, "delivery", *WEST, "Y", "TX")))
    look(world, -97.0, 0, [order])
    recs, watch = told()
    assert not watch.state.startswith("off its road") and watch.regions != ()
    assert all(r.reason != "heading" for r in recs)


# Just set off from a stop (a pickup that turned him around): the miles he came by don't give his way, so the road
# isn't judged by them; once he has driven HEADING_MI since, they do.
def test_just_left_a_stop_the_way_waits(world):
    at = AT + timedelta(minutes=30)
    came = [TrackPoint(at - timedelta(minutes=60 - k), 30.0, -97.3 + k / 58) for k in range(0, 18)]   # east to -97.0
    still = [TrackPoint(at - timedelta(minutes=42 - k), 30.0, -97.0) for k in range(0, 37)]           # 36 min there
    back = [TrackPoint(at - timedelta(minutes=5 - k), 30.0, -97.0 - (k + 1) / 58) for k in range(5)]  # 5 mi back west
    track = came + still + back
    assert job._toward(track, (track[-1].lat, track[-1].lng), at) is None
    more = track + [TrackPoint(at + timedelta(minutes=k + 1), 30.0, -97.0 - (6 + k) / 58) for k in range(6)]
    assert round(job._toward(more, (more[-1].lat, more[-1].lng), at + timedelta(minutes=6))) == 270


# The position is read once a pass, the GPS track fresh at each look: the track runs past it. The miles after the
# position was read are left out, or the way would come out backwards (a point 10 mi "back" that is really ahead).
def test_way_ignores_the_gps_after_the_position(world):
    seen = AT - timedelta(minutes=12)                                             # the position read 12 min ago
    track = [TrackPoint(AT - timedelta(minutes=k), 30.0, -97.0 + (12 - k) / 58) for k in range(60, -1, -1)]  # east
    position = (30.0, -97.0)                                                      # where it was at `seen`
    assert round(job._toward(track, position, AT)) == 270                         # without the cut: backwards
    assert round(job._toward(track, position, AT, seen)) == 90
