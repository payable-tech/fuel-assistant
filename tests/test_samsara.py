# Tests how raw Samsara stats become our objects: a missing GPS point or fuel gauge becomes None, not an error.
from datetime import datetime, timezone

from base.sources import samsara

RAW = {"id": "281", "name": "Unit 340",
       "gps": {"time": "2026-10-19T17:58:42Z", "latitude": 32.7, "longitude": -96.8,
               "reverseGeo": {"formattedLocation": "Dallas, TX, 75201"}},
       "fuelPercent": {"time": "2026-10-19T17:56:00Z", "value": 45}}


# A vehicle with GPS and a fuel gauge keeps both, each with its own time.
def test_live_mapping():
    live = samsara._live(RAW)
    assert (live.samsara_id, live.lat, live.lng, live.place, live.fuel_pct) == ("281", 32.7, -96.8, "Dallas, TX, 75201", 45)
    assert live.fuel_at == datetime(2026, 10, 19, 17, 56, tzinfo=timezone.utc)


# A vehicle without a fuel gauge or GPS maps to empty values.
def test_live_without_fuel_or_gps():
    live = samsara._live({"id": "282", "name": "Unit 717"})
    assert (live.lat, live.place, live.gps_at, live.fuel_pct, live.fuel_at) == (None, None, None, None, None)

