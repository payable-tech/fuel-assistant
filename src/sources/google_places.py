# Google Places API (New), read-only: the fuel stations along a stretch of road a truck can fill at, with their
# diesel price when Google has one. Used only when no Love's is in reach of the truck (jobs/plan_loads).
import httpx

import config
from core import fuel
from models import Store
from sources.google_routes import encode

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ("places.id,places.displayName,places.location,places.addressComponents,places.types,places.fuelOptions,"
          "places.businessStatus")


# The stations along a road line (Google's search along a route, up to 20 of each kind), as stores whose store
# number is Google's id: its truck stops, and apart from those the gas stations that sell diesel (a mountain road can
# go 200 mi without a truck stop). Love's are left out (the price sheet has them). A station whose price Google
# doesn't have gets price 0 and no price date.
def stations_along(line: list[tuple[float, float]]) -> tuple[list[Store], list[Store]]:
    # Google calls a rest area or a truck scale a truck stop too: only those that are also gas stations sell fuel
    truck_stops = [p for p in _along(line, "truck stop", None) if "gas_station" in p.get("types", [])]
    known = {p["id"] for p in truck_stops}
    others = [p for p in _along(line, "diesel", "gas_station") if p["id"] not in known and "DIESEL" in _prices(p)]
    return [_station(p) for p in truck_stops], [_station(p) for p in others]


# The open places Google finds for `query` along a road line (of one type, if given), Love's left out.
def _along(line: list[tuple[float, float]], query: str, kind: str | None) -> list[dict]:
    body = {"textQuery": query, "pageSize": 20, "searchAlongRouteParameters": {"polyline": {"encodedPolyline": encode(line)}}}
    if kind:
        body["includedType"] = kind
    headers = {"X-Goog-Api-Key": config.secret("GOOGLE_MAPS_API_KEY"), "X-Goog-FieldMask": FIELDS}
    response = httpx.post(URL, json=body, headers=headers, timeout=30)
    if response.is_error:  # e.g. the Places API (New) not enabled for the key: Google's message says which
        raise RuntimeError(f"Google Places API {response.status_code}: {response.json()['error']['message']}")
    return [p for p in response.json().get("places", [])
            if p.get("businessStatus", "OPERATIONAL") == "OPERATIONAL"
            and fuel.chain(p["displayName"]["text"].replace("’", "'")) != fuel.LOVES]


# One place as a store: its Google id as the store number, its name, town and state, and its diesel price.
def _station(place: dict) -> Store:
    parts = {kind: c for c in place.get("addressComponents", []) for kind in c.get("types", [])}
    town = parts.get("locality") or parts.get("postal_town") or parts.get("administrative_area_level_2") or {}
    prices = _prices(place)
    price, day = prices.get("DIESEL") or (0.0, "")
    return Store(store_no=place["id"], city=town.get("longText", ""),
                 state=(parts.get("administrative_area_level_1") or {}).get("shortText", ""),
                 lat=place["location"]["latitude"], lng=place["location"]["longitude"], retail=price, net=price,
                 price_date=day, name=place["displayName"]["text"])


# A place's fuel prices: {fuel type: (dollars a gallon, "YYYY-MM-DD" it was updated)}.
def _prices(place: dict) -> dict[str, tuple[float, str]]:
    return {p["type"]: (int(p["price"].get("units", 0)) + p["price"].get("nanos", 0) / 1e9, p.get("updateTime", "")[:10])
            for p in (place.get("fuelOptions") or {}).get("fuelPrices", []) if p.get("price")}
