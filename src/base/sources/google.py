# Google Maps (read-only): the driving route through a list of points (Routes API), the real truck stops along a stretch
# of road (Places API (New)), and whether this PC can reach those two addresses at all (for the heartbeat).
import re

import httpx

from base import config
from base.geo import decode, encode
from base.models import Store

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.id,places.displayName,places.location,places.addressComponents,places.types,places.businessStatus"
# A big chain's travel center by its name: "Pilot Travel Center", "TA Express Travel Center", "Petro truckstop"
CHAINS = re.compile(r"(pilot|flying j|ta|petro)\b.*(travel|stop)", re.IGNORECASE)
REACH_TIMEOUT_S = 10


# Returns the driving route from the first point through the middle ones to the last, as (lat, lng) points.
# Traffic is ignored: it doesn't change where the road goes, and it's the cheapest kind of request.
def route(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    body = {"origin": _waypoint(points[0]), "destination": _waypoint(points[-1]),
            "intermediates": [_waypoint(p) for p in points[1:-1]],
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
    headers = {"X-Goog-Api-Key": config.secret("GOOGLE_MAPS_API_KEY"),
               "X-Goog-FieldMask": "routes.polyline.encodedPolyline"}  # ask only for the line we use
    response = httpx.post(ROUTES_URL, json=body, headers=headers, timeout=60)
    if response.is_error:  # e.g. a wrong key or the Routes API not enabled: Google's message says which
        raise RuntimeError(f"Google Routes API {response.status_code}: {response.json()['error']['message']}")
    routes = response.json().get("routes")
    if not routes:
        raise LookupError("Google found no driving route through these points")
    return decode(routes[0]["polyline"]["encodedPolyline"])


# One point in the shape the Routes API expects.
def _waypoint(point: tuple[float, float]) -> dict:
    return {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}


# The open truck stops along a road line, as stores whose store number is Google's id, with no prices: the backup when
# no Love's can be counted on. Truck stops only: a gas station is no use to a truck (Fred Meyer, Medford OR, 2026-10-28).
def truck_stops_along(line: list[tuple[float, float]]) -> list[Store]:
    body = {"textQuery": "truck stop", "pageSize": 20, "searchAlongRouteParameters": {"polyline": {"encodedPolyline": encode(line)}}}
    headers = {"X-Goog-Api-Key": config.secret("GOOGLE_MAPS_API_KEY"), "X-Goog-FieldMask": FIELDS}
    response = httpx.post(PLACES_URL, json=body, headers=headers, timeout=30)
    if response.is_error:  # e.g. the Places API (New) not enabled for the key: Google's message says which
        raise RuntimeError(f"Google Places API {response.status_code}: {response.json()['error']['message']}")
    return [_station(p) for p in response.json().get("places", [])
            if is_truck_stop(p["displayName"]["text"], p.get("types", [])) and p.get("businessStatus", "OPERATIONAL") == "OPERATIONAL"]


# True for a place a semi can fuel at: tagged both a truck stop and a gas station (the truck stop tag alone also covers
# truck parking, rest areas and scales), or a big chain's travel center, which Google often tags wrong (TA as car
# repair, Petro as a rest stop). Never a gas station in town: 540201 was sent to two in Indianapolis (2026-11-05).
def is_truck_stop(name: str, types: list[str]) -> bool:
    return {"truck_stop", "gas_station"} <= set(types) or CHAINS.match(name) is not None


# One place as a store: its Google id as the store number, its name, town and state.
def _station(place: dict) -> Store:
    parts = {kind: c for c in place.get("addressComponents", []) for kind in c.get("types", [])}
    town = parts.get("locality") or parts.get("postal_town") or parts.get("administrative_area_level_2") or {}
    return Store(store_no=place["id"], city=town.get("longText", ""),
                 state=(parts.get("administrative_area_level_1") or {}).get("shortText", ""),
                 lat=place["location"]["latitude"], lng=place["location"]["longitude"], retail=0.0, net=0.0,
                 price_date="", name=place["displayName"]["text"])


# Can this PC reach the addresses the Routes and Places APIs are called at (no key, no cost)? Tries each once. Returns
# None when both answer, else which one didn't and why. Any answer counts, even "not found" (what Google says to a call
# with no question): the check is only whether the address can be reached, so a wrong key or an unpaid bill isn't seen
# here. On 2026-11-22 the office network refused them for hours, no new road could be made, and nobody knew.
def unreachable() -> str | None:
    for url in (ROUTES_URL, PLACES_URL):  # exactly the addresses the program calls, not Google in general
        host = httpx.URL(url).host
        try:
            httpx.get(f"https://{host}/", timeout=REACH_TIMEOUT_S)
        except Exception as error:  # whatever the failure, the heartbeat's other checks must still run
            return f"{host}: {type(error).__name__}: {error}"
    return None
