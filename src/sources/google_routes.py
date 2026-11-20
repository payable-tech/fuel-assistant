# Google Routes API (read-only): the driving route through a list of points, as a line of (lat, lng) points.
import httpx

import config
from core.geo import decode

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
