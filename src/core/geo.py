# Route geometry (pure): distances on the earth, a route's length, the Love's stores along a route, and Google's
# encoded form of a line.
from datetime import datetime
from math import asin, atan2, ceil, cos, degrees, radians, sin, sqrt

from models import Store, StoreOnRoute, TrackPoint

EARTH_MI = 3958.8
DEG_MI = 45  # one degree of longitude is at least this many miles anywhere in the lower 48 states

Point = tuple[float, float]  # (lat, lng)


# Straight-line (great-circle) miles between two points.
def miles(a: Point, b: Point) -> float:
    lat1, lng1, lat2, lng2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_MI * asin(sqrt(h))


# The compass direction from one point to another: degrees clockwise from north (0 north, 90 east, 180 south, 270 west).
def bearing(a: Point, b: Point) -> float:
    lat1, lng1, lat2, lng2 = map(radians, (*a, *b))
    x = sin(lng2 - lng1) * cos(lat2)
    y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(lng2 - lng1)
    return degrees(atan2(x, y)) % 360


# How far apart two compass directions are, 0 (the same way) to 180 (opposite ways).
def turn(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


# True when a place lies behind a truck at `position` going `toward` (compass degrees): farther than `near_mi` and more
# than `behind_deg` off its way. Never while its way isn't known (`toward` None).
def behind(position: Point, toward: float | None, place: Point, near_mi: float, behind_deg: float) -> bool:
    return toward is not None and miles(position, place) > near_mi and turn(bearing(position, place), toward) > behind_deg


# The point of a line `mile` miles from its start; its last point when the line is shorter.
def point_at(line: list[Point], mile: float) -> Point:
    for point, mark in zip(line, along(line)):
        if mark >= mile:
            return point
    return line[-1]


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


# A GPS track with its points at least `min_mi` apart (the first and last kept): the same road and stops, without the
# hundreds of points a parked truck sends.
def thin_track(track: list[TrackPoint], min_mi: float) -> list[TrackPoint]:
    kept = track[:1]
    for p in track[1:-1]:
        if miles((kept[-1].lat, kept[-1].lng), (p.lat, p.lng)) >= min_mi:
            kept.append(p)
    return kept + track[-1:] if len(track) > 1 else kept


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


# How far along a line a point is: the line's nearest point to it, looking only from `from_mile` on (a road can pass
# near the same place twice).
def mile_on(line: list[Point], point: Point, from_mile: float) -> float:
    marks = along(line)
    ahead = [k for k in range(len(line)) if marks[k] >= from_mile] or [len(line) - 1]
    return marks[min(ahead, key=lambda k: miles(line[k], point))]


# The point of a GPS track nearest a moment in time; None for an empty track.
def where_at(track: list[TrackPoint], at: datetime) -> TrackPoint | None:
    return min(track, key=lambda p: abs(p.at - at), default=None)


# The piece of a line between two miles along it.
def stretch(line: list[Point], from_mile: float, to_mile: float) -> list[Point]:
    return [p for p, m in zip(line, along(line)) if from_mile <= m <= to_mile]


# Encodes (lat, lng) points as Google's polyline text, the reverse of `decode` (e.g. to search places along a road).
def encode(points: list[Point]) -> str:
    out, last_lat, last_lng = [], 0, 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for delta in (ilat - last_lat, ilng - last_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1  # the lowest bit carries the sign
            while value >= 0x20:  # 5-bit chunks, each but the last with the "more follows" bit
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last_lat, last_lng = ilat, ilng
    return "".join(out)


# Decodes Google's encoded polyline text into (lat, lng) points. Each value is stored as the change from the
# previous one, in 5-bit chunks offset by 63 (format documented by Google Maps).
def decode(text: str) -> list[Point]:
    points, index, lat, lng = [], 0, 0, 0
    while index < len(text):
        deltas = []
        for _ in range(2):  # latitude change, then longitude change
            shift = result = 0
            while True:
                chunk = ord(text[index]) - 63
                index += 1
                result |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:  # the last chunk of a value has no "more follows" bit
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)  # the lowest bit carries the sign
        lat, lng = lat + deltas[0], lng + deltas[1]
        points.append((lat / 1e5, lng / 1e5))
    return points
