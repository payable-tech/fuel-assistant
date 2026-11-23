# Tests route geometry: distances, cutting a line into short pieces, and finding the stores along a route.
from base import geo
from base.models import Store


# A store at a point, with a price.
def store(no: str, lat: float, lng: float, net: float = 5.0) -> Store:
    return Store(store_no=no, city="", state="", lat=lat, lng=lng, retail=net + 0.5, net=net, price_date="2026-10-19")


# New York to Los Angeles is about 2,445 straight-line miles.
def test_miles():
    assert abs(geo.miles((40.71, -74.01), (34.05, -118.24)) - 2445) < 15


# Compass directions: east is 90, north 0, west 270; two directions are at most 180 apart, across north too.
def test_bearing_and_turn():
    assert round(geo.bearing((35.0, -100.0), (35.0, -99.0))) == 90
    assert round(geo.bearing((35.0, -100.0), (36.0, -100.0))) == 0
    assert round(geo.bearing((35.0, -100.0), (35.0, -101.0))) == 270
    assert geo.turn(350, 10) == 20 and geo.turn(90, 270) == 180 and geo.turn(45, 45) == 0


# A 10-mile line cut into 0.5-mile pieces has no piece longer than 0.5 mi and keeps both ends.
def test_densify():
    line = [(35.0, -100.0), (35.0, -99.823)]  # ~10 mi east
    points = geo.densify(line, 0.5)
    gaps = [geo.miles(a, b) for a, b in zip(points, points[1:])]
    assert max(gaps) <= 0.5 and points[0] == line[0] and points[-1] == line[-1]


# Thinning keeps the ends and drops points closer than the step to the last one kept.
def test_thin():
    line = [(35.0, -100.0), (35.0, -99.999), (35.0, -99.99), (35.0, -99.9), (35.0, -99.8999)]
    assert geo.thin(line, 0.5) == [(35.0, -100.0), (35.0, -99.99), (35.0, -99.9), (35.0, -99.8999)]
    assert geo.thin(line[:1], 0.5) == line[:1]


# On a straight 55-mile road, a store 0.7 mi off the middle is found about 28 mi along; one 3.5 mi off is not.
def test_stores_along_a_straight_road():
    line = [(35.0, -100.0), (35.0, -99.0)]  # one straight piece, as Google sends long straight roads
    found = geo.stores_along(line, [store("far", 35.05, -99.5), store("near", 35.01, -99.5)], 1.5, 0.5)
    assert [s.store.store_no for s in found] == ["near"]
    assert abs(found[0].miles - 28.3) < 0.6 and abs(found[0].off_mi - 0.69) < 0.05


# Stores come back in route order.
def test_route_order():
    line = [(35.0, -100.0), (35.0, -99.0)]
    found = geo.stores_along(line, [store("east", 35.0, -99.1), store("west", 35.0, -99.9)], 1.5, 0.5)
    assert [s.store.store_no for s in found] == ["west", "east"]


# How far along a line a point is, looking only ahead of a mile: a road passing the same place twice counts the later one.
def test_mile_on():
    there_and_back = [(30.0, -97.0), (31.0, -97.0), (30.0, -97.0)]
    total = geo.along(there_and_back)[-1]
    assert geo.mile_on(there_and_back, (30.0, -97.0), 0.0) == 0.0
    assert geo.mile_on(there_and_back, (30.0, -97.0), 10.0) == total


def test_stretch():
    line = [(30.0, -97.0), (31.0, -97.0), (32.0, -97.0)]
    marks = geo.along(line)
    assert geo.stretch(line, marks[1] - 1, marks[2] + 1) == line[1:]


# Google's own documented example decodes to its three points, and encoding them gives the same text back.
def test_polyline():
    text, points = "_p~iF~ps|U_ulLnnqC_mqNvxq`@", [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert geo.decode(text) == points and geo.encode(points) == text


# The track point nearest a moment, before or after it; none on an empty track.
def test_where_at():
    from datetime import datetime, timedelta, timezone
    from base.models import TrackPoint
    at = datetime(2026, 11, 5, tzinfo=timezone.utc)
    track = [TrackPoint(at - timedelta(minutes=9), 30.0, -97.0), TrackPoint(at + timedelta(minutes=4), 30.1, -97.0)]
    assert geo.where_at(track, at) == track[1] and geo.where_at([], at) is None


# A thinned track keeps its first and last points and those at least the step apart, with their times.
def test_thin_track():
    from datetime import datetime, timedelta, timezone
    from base.models import TrackPoint
    at = datetime(2026, 11, 5, tzinfo=timezone.utc)
    track = [TrackPoint(at + timedelta(minutes=k), 30.0, -97.0) for k in range(5)] + [TrackPoint(at + timedelta(minutes=9), 30.1, -97.0)]
    kept = geo.thin_track(track, 0.1)
    assert [p.at for p in kept] == [at, at + timedelta(minutes=9)]


# A place lies behind a truck when it is more than the angle off its way and farther than `near_mi`; never while its
# way isn't known.
def test_behind():
    here = (30.0, -97.0)
    assert geo.behind(here, 90, (30.0, -97.5), 2, 135)            # west of a truck going east
    assert not geo.behind(here, 90, (30.0, -96.5), 2, 135)        # east: ahead
    assert not geo.behind(here, 90, (30.5, -97.0), 2, 135)        # north: beside its way, not behind
    assert not geo.behind(here, 90, (30.0, -97.01), 2, 135)       # half a mile back: he is there
    assert not geo.behind(here, None, (30.0, -97.5), 2, 135)      # parked: no way to be behind


# The point of a line some miles from its start; its last point past the end.
def test_point_at():
    line = [(30.0, -97.0 + k / 58) for k in range(11)]            # a point about every mile, going east
    assert geo.point_at(line, 0) == line[0] and geo.point_at(line, 4.5) == line[5] and geo.point_at(line, 50) == line[-1]
