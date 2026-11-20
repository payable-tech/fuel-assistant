# Google Places API (New), read-only: the real truck stops along a stretch of road, the backup when no Love's can be
# counted on. Truck stops only: a gas station is no use to a truck (Fred Meyer, Medford OR, 2026-10-28).
import re

import httpx

import config
from models import Store
from core.geo import encode

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.id,places.displayName,places.location,places.addressComponents,places.types,places.businessStatus"
# A big chain's travel center by its name: "Pilot Travel Center", "TA Express Travel Center", "Petro truckstop"
CHAINS = re.compile(r"(pilot|flying j|ta|petro)\b.*(travel|stop)", re.IGNORECASE)


# The open truck stops along a road line, as stores whose store number is Google's id, with no prices.
def truck_stops_along(line: list[tuple[float, float]]) -> list[Store]:
    body = {"textQuery": "truck stop", "pageSize": 20, "searchAlongRouteParameters": {"polyline": {"encodedPolyline": encode(line)}}}
    headers = {"X-Goog-Api-Key": config.secret("GOOGLE_MAPS_API_KEY"), "X-Goog-FieldMask": FIELDS}
    response = httpx.post(URL, json=body, headers=headers, timeout=30)
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
