# Route geometry (pure): distances on the earth, a route's length, and the Love's stores along a route.
from math import asin, ceil, cos, radians, sin, sqrt

from models import Store, StoreOnRoute

EARTH_MI = 3958.8
DEG_MI = 45  # one degree of longitude is at least this many miles anywhere in the lower 48 states

Point = tuple[float, float]  # (lat, lng)


# Straight-line (great-circle) miles between two points.
def miles(a: Point, b: Point) -> float:
    lat1, lng1, lat2, lng2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_MI * asin(sqrt(h))


# Miles from the start of a line to each of its points.
def along(line: list[Point]) -> list[float]:
    total, result = 0.0, [0.0]
    for a, b in zip(line, line[1:]):
        total += miles(a, b)
        result.append(total)
    return result


# Cuts a line so no piece is longer than `step_mi`. Google sends a long straight road as one piece, and a store
# halfway along it would otherwise look far from the route.
def densify(line: list[Point], step_mi: float) -> list[Point]:
    points = [line[0]]
    for a, b in zip(line, line[1:]):
        pieces = max(1, ceil(miles(a, b) / step_mi))
        points += [(a[0] + (b[0] - a[0]) * k / pieces, a[1] + (b[1] - a[1]) * k / pieces) for k in range(1, pieces + 1)]
    return points


# Drops points closer than `min_mi` to the last point kept (the first and last always stay): the same line on a
# map with far fewer points to send and draw.
def thin(line: list[Point], min_mi: float) -> list[Point]:
    kept = line[:1]
    for p in line[1:-1]:
        if miles(kept[-1], p) >= min_mi:
            kept.append(p)
    return kept + line[-1:] if len(line) > 1 else kept


# The stores within `corridor_mi` of a route, each with how far along the route it is, in route order.
def stores_along(line: list[Point], stores: list[Store], corridor_mi: float, step_mi: float) -> list[StoreOnRoute]:
    points = densify(line, step_mi)
    distance = along(points)
    margin = corridor_mi / DEG_MI
    south, north = min(p[0] for p in points) - margin, max(p[0] for p in points) + margin
    west, east = min(p[1] for p in points) - margin, max(p[1] for p in points) + margin
    found = []
    for store in stores:
        if not (south <= store.lat <= north and west <= store.lng <= east):
            continue  # outside the route's box: can't be near it, skip the slow check
        off, i = min((miles((store.lat, store.lng), p), i) for i, p in enumerate(points))
        if off <= corridor_mi:
            found.append(StoreOnRoute(store=store, miles=distance[i], off_mi=off))
    return sorted(found, key=lambda s: s.miles)


# The store nearest to a point.
def nearest(stores: list[Store], point: Point) -> Store:
    return min(stores, key=lambda s: miles((s.lat, s.lng), point))
