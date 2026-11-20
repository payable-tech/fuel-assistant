# Samsara API (read-only) across every account (one per motor carrier, SAMSARA_ACCOUNTS): each vehicle's VIN, last GPS
# time and 30-day MPG, every vehicle's latest position and fuel, one vehicle's GPS, gauge and engine history, and every
# vehicle's fuel used and gauge for a statement's days.
from datetime import datetime, timedelta, timezone

import httpx

import config
from models import EngineHistory, FuelReading, Sample, SamsaraLive, SamsaraVehicle, TrackPoint

METERS_PER_MILE = 1609.34
ML_PER_GALLON = 3785.41
BASE_URL = "https://api.samsara.com"
MPG_DAYS = 30
_accounts: dict[str, str] = {}  # vehicle id -> the account it is in, filled as vehicles are listed (see _account_of)


# Returns every Samsara vehicle of every account; VINs are trimmed and upper-cased so they compare cleanly with
# Datatruck. A truck that moved to another carrier's account is in both, its old record no longer reporting.
def vehicles() -> list[SamsaraVehicle]:
    found = []
    for account in config.SAMSARA_ACCOUNTS:
        with _client(account) as client:
            listed = _listed(client)
            gps_at = {s["id"]: _time(s["gps"]["time"])
                      for page in _pages(client, "/fleet/vehicles/stats", {"types": "gps"})
                      for s in page if s.get("gps")}
            mpg = _mpg(client)
        _accounts.update({v["id"]: account for v in listed})
        found += [SamsaraVehicle(samsara_id=v["id"], name=v["name"], vin=(v.get("vin") or "").strip().upper(),
                                 mpg=mpg.get(v["id"]), last_gps_at=gps_at.get(v["id"]))
                  for v in listed]
    return found


# Returns {vehicle id: MPG} from the fuel & energy report of the last MPG_DAYS days.
def _mpg(client: httpx.Client) -> dict[str, float]:
    end = datetime.now(timezone.utc)
    params = {"startDate": _iso(end - timedelta(days=MPG_DAYS)), "endDate": _iso(end)}
    return {r["vehicle"]["id"]: r["efficiencyMpge"]
            for page in _pages(client, "/fleet/reports/vehicles/fuel-energy", params)
            for r in page["vehicleReports"]
            if r.get("efficiencyMpge")}  # 0 means "no driving data", so it is left out as unknown


# Returns every vehicle's latest GPS point and fuel gauge reading, in every account.
def live() -> list[SamsaraLive]:
    found = []
    for account in config.SAMSARA_ACCOUNTS:
        with _client(account) as client:
            found += [_live(s) for page in _pages(client, "/fleet/vehicles/stats", {"types": "gps,fuelPercents"})
                      for s in page]
    return found


# Converts one vehicle's latest stats; a value Samsara doesn't have becomes None.
def _live(stats: dict) -> SamsaraLive:
    gps, fuel = stats.get("gps") or {}, stats.get("fuelPercent") or {}
    return SamsaraLive(samsara_id=stats["id"], lat=gps.get("latitude"), lng=gps.get("longitude"),
                       place=(gps.get("reverseGeo") or {}).get("formattedLocation"),
                       gps_at=_time(gps["time"]) if gps else None,
                       fuel_pct=fuel.get("value"), fuel_at=_time(fuel["time"]) if fuel else None)


# Returns one vehicle's GPS track between two times: thousands of points a day, three pages for three days.
def gps_history(samsara_id: str, start: datetime, end: datetime) -> list[TrackPoint]:
    params = {"types": "gps", "vehicleIds": samsara_id, "startTime": _iso(start), "endTime": _iso(end)}
    with _client(_account_of(samsara_id)) as client:
        return [TrackPoint(at=_time(p["time"]), lat=p["latitude"], lng=p["longitude"])
                for page in _pages(client, "/fleet/vehicles/stats/history", params)
                for vehicle in page for p in vehicle.get("gps", [])]


# Returns one vehicle's fuel gauge readings (about one every 2 minutes while it runs) between two times.
def fuel_history(samsara_id: str, start: datetime, end: datetime) -> list[FuelReading]:
    params = {"types": "fuelPercents", "vehicleIds": samsara_id, "startTime": _iso(start), "endTime": _iso(end)}
    with _client(_account_of(samsara_id)) as client:
        return [FuelReading(at=_time(r["time"]), pct=r["value"])
                for page in _pages(client, "/fleet/vehicles/stats/history", params)
                for vehicle in page for r in vehicle.get("fuelPercents", [])]


# Returns one vehicle's GPS points between two times, each with Samsara's address ("Street, City, ST, ZIP"). Keep the
# window short: a point comes every few seconds.
def placed_track(samsara_id: str, start: datetime, end: datetime) -> list[TrackPoint]:
    params = {"types": "gps", "vehicleIds": samsara_id, "startTime": _iso(start), "endTime": _iso(end)}
    with _client(_account_of(samsara_id)) as client:
        return [TrackPoint(at=_time(p["time"]), lat=p["latitude"], lng=p["longitude"],
                           place=(p.get("reverseGeo") or {}).get("formattedLocation"))
                for page in _pages(client, "/fleet/vehicles/stats/history", params)
                for vehicle in page for p in vehicle.get("gps", [])]


# Returns every vehicle's engine fuel used (gallons) and miles driven between two times, from the fuel & energy report
# of every account, as {vehicle id: (gallons, miles)}.
def fuel_used(start: datetime, end: datetime) -> dict[str, tuple[float, float]]:
    found = {}
    for account in config.SAMSARA_ACCOUNTS:
        with _client(account) as client:
            found |= {r["vehicle"]["id"]: (r["fuelConsumedMl"] / ML_PER_GALLON, r["distanceTraveledMeters"] / METERS_PER_MILE)
                      for page in _pages(client, "/fleet/reports/vehicles/fuel-energy",
                                         {"startDate": _iso(start), "endDate": _iso(end)})
                      for r in page["vehicleReports"]}
    return found


# Returns every vehicle's gauge (%) as of a moment: its last reading at or before it, when that reading is no older than
# `fresh` (an older one belongs to a truck parked or with a dead gauge), as {vehicle id: %}.
def gauges_at(moment: datetime, fresh: timedelta) -> dict[str, float]:
    found = {}
    for account in config.SAMSARA_ACCOUNTS:
        with _client(account) as client:
            found |= {s["id"]: s["fuelPercent"]["value"]
                      for page in _pages(client, "/fleet/vehicles/stats", {"types": "fuelPercents", "time": _iso(moment)})
                      for s in page
                      if s.get("fuelPercent") and moment - _time(s["fuelPercent"]["time"]) <= fresh}
    return found


# Returns one vehicle's engine load %, RPM and odometer miles between two times (a reading every few minutes while it
# runs), each oldest first.
def engine_history(samsara_id: str, start: datetime, end: datetime) -> EngineHistory:
    params = {"types": "engineLoadPercent,engineRpm,obdOdometerMeters", "vehicleIds": samsara_id,
              "startTime": _iso(start), "endTime": _iso(end)}
    with _client(_account_of(samsara_id)) as client:
        pages = [v for page in _pages(client, "/fleet/vehicles/stats/history", params) for v in page]

    # One signal's readings, oldest first, times `scale`.
    def samples(name: str, scale: float = 1.0) -> tuple[Sample, ...]:
        found = [Sample(at=_time(r["time"]), value=r["value"] * scale) for v in pages for r in v.get(name, [])]
        return tuple(sorted(found, key=lambda s: s.at))

    return EngineHistory(load=samples("engineLoadPercent"), rpm=samples("engineRpm"),
                         miles=samples("obdOdometerMeters", 1 / METERS_PER_MILE))


# The account a vehicle is in, from the accounts' vehicle lists (a truck moved to another carrier gets a new id there).
# Raises LookupError for a vehicle in none of them.
def _account_of(samsara_id: str) -> str:
    if samsara_id not in _accounts:  # not known yet (after a restart, or a truck just added): list them again
        for account in config.SAMSARA_ACCOUNTS:
            with _client(account) as client:
                _accounts.update({v["id"]: account for v in _listed(client)})
    if samsara_id not in _accounts:
        raise LookupError(f"Samsara vehicle {samsara_id} is in none of the accounts {', '.join(config.SAMSARA_ACCOUNTS)}")
    return _accounts[samsara_id]


# Every vehicle of the account a client is logged in to, as Samsara lists it.
def _listed(client: httpx.Client) -> list[dict]:
    return [v for page in _pages(client, "/fleet/vehicles", {"limit": 512}) for v in page]


# Opens an HTTP client authorized with one account's Samsara token.
def _client(account: str) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=60,
                        headers={"Authorization": f"Bearer {config.secret(f'SAMSARA_API_TOKEN_{account}')}"})


# Yields the `data` of each page of an endpoint, following Samsara's pagination cursor.
def _pages(client: httpx.Client, path: str, params: dict):
    cursor = None
    while True:
        response = client.get(path, params=params | ({"after": cursor} if cursor else {}))
        response.raise_for_status()
        body = response.json()
        yield body["data"]
        if not body["pagination"]["hasNextPage"]:
            return
        cursor = body["pagination"]["endCursor"]


# Parses a Samsara timestamp ("2026-10-18T12:00:00Z") into a UTC datetime.
def _time(text: str) -> datetime:
    return datetime.fromisoformat(text)


# Formats a UTC datetime the way Samsara expects ("2026-10-18T12:00:00Z").
def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
