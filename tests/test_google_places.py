# Tests how Google Places results become stations (name, town, state and diesel price read from a place; truck stops
# apart from other diesel stations) and the road line sent to it (Google's polyline encoding).
from sources import google_places


# A place as Google Places API (New) sends it, selling diesel at `diesel` dollars (none: no price).
def place(pid: str, name: str, diesel: float | None = 6.5) -> dict:
    prices = [{"type": "DIESEL", "price": {"currencyCode": "USD", "units": str(int(diesel)),
                                           "nanos": round((diesel % 1) * 1e9)}, "updateTime": "2026-10-23T09:00:00Z"}
              ] if diesel else []
    return {"id": pid, "displayName": {"text": name}, "location": {"latitude": 46.43, "longitude": -116.99},
            "types": ["truck_stop", "gas_station"],
            "addressComponents": [{"longText": "Lewiston", "shortText": "Lewiston", "types": ["locality", "political"]},
                                  {"longText": "Idaho", "shortText": "ID",
                                   "types": ["administrative_area_level_1", "political"]}],
            "fuelOptions": {"fuelPrices": prices}}


# A place's name, town, state and diesel price (with the day it was updated); no price known: 0 and no day.
def test_station():
    s = google_places._station(place("ChIJ1", "Stinker Stores", 6.5))
    assert (s.store_no, s.name, s.city, s.state, round(s.retail, 2), s.net == s.retail, s.price_date) == \
        ("ChIJ1", "Stinker Stores", "Lewiston", "ID", 6.5, True, "2026-10-23")
    unknown = google_places._station(place("ChIJ2", "Coleman Oil", None))
    assert (unknown.retail, unknown.price_date) == (0.0, "")


# Truck stops that sell fuel (a rest area doesn't), apart from the other stations; of those, only the ones selling
# diesel, each place once.
def test_truck_stops_and_others(monkeypatch):
    found = {"truck stop": [place("t", "Town Pump"), {**place("r", "US-12 Lenore Rest Area", None), "types": ["rest_stop"]}],
             "diesel": [place("t", "Town Pump"), place("g1", "Conoco", 6.58), place("g2", "Costco Gas Station", None)]}
    monkeypatch.setattr(google_places, "_along", lambda line, query, kind: found[query])
    truck_stops, others = google_places.stations_along([(46.4, -117.0), (46.5, -116.8)])
    assert [s.store_no for s in truck_stops] == ["t"] and [s.store_no for s in others] == ["g1"]


# Road lines go to Google encoded the way its own lines come back.
def test_polyline_round_trip():
    from sources import google_routes
    points = [(46.42230, -117.04430), (46.43039, -116.98559), (45.6642, -108.8)]
    assert google_routes.encode([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    assert google_routes.decode(google_routes.encode(points)) == points
