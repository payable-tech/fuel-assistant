# Tests route geometry: distances, cutting a line into short pieces, and finding the stores along a route.
from core import geo
from models import Store


# A store at a point, with a price.
def store(no: str, lat: float, lng: float, net: float = 5.0) -> Store:
    return Store(store_no=no, city="", state="", lat=lat, lng=lng, retail=net + 0.5, net=net, price_date="2026-10-19")


# New York to Los Angeles is about 2,445 straight-line miles.
def test_miles():
    assert abs(geo.miles((40.71, -74.01), (34.05, -118.24)) - 2445) < 15


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


# Stores come back in route order, and the nearest store to a point is found.
def test_route_order_and_nearest():
    line = [(35.0, -100.0), (35.0, -99.0)]
    found = geo.stores_along(line, [store("east", 35.0, -99.1), store("west", 35.0, -99.9)], 1.5, 0.5)
    assert [s.store.store_no for s in found] == ["west", "east"]
    assert geo.nearest([store("a", 35.0, -99.1), store("b", 36.0, -99.0)], (35.1, -99.0)).store_no == "a"
