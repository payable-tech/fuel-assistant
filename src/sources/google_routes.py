# Google Routes API (read-only): the driving route through a list of points, as a line of (lat, lng) points.
import httpx

import config

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


# Returns the driving route from the first point through the middle ones to the last, as (lat, lng) points.
# Traffic is ignored: it doesn't change where the road goes, and it's the cheapest kind of request.
def route(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    body = {"origin": _waypoint(points[0]), "destination": _waypoint(points[-1]),
            "intermediates": [_waypoint(p) for p in points[1:-1]],
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
    headers = {"X-Goog-Api-Key": config.secret("GOOGLE_MAPS_API_KEY"),
               "X-Goog-FieldMask": "routes.polyline.encodedPolyline"}  # ask only for the line we use
    response = httpx.post(URL, json=body, headers=headers, timeout=60)
    if response.is_error:  # e.g. a wrong key or the Routes API not enabled: Google's message says which
        raise RuntimeError(f"Google Routes API {response.status_code}: {response.json()['error']['message']}")
    routes = response.json().get("routes")
    if not routes:
        raise LookupError("Google found no driving route through these points")
    return decode(routes[0]["polyline"]["encodedPolyline"])


# One point in the shape the Routes API expects.
def _waypoint(point: tuple[float, float]) -> dict:
    return {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}


# Encodes (lat, lng) points as Google's polyline text, the reverse of `decode` (e.g. to search places along a road).
def encode(points: list[tuple[float, float]]) -> str:
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
def decode(text: str) -> list[tuple[float, float]]:
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
