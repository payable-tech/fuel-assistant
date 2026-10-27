# Samsara API (read-only), across every Samsara account (one per motor carrier, config.SAMSARA_ACCOUNTS): every
# vehicle with its VIN, last GPS time and 30-day MPG; every vehicle's latest position and fuel level; one vehicle's
# GPS track and fuel gauge history, asked of the account the vehicle is in.
from datetime import datetime, timedelta, timezone

import httpx

import config
from models import FuelReading, SamsaraLive, SamsaraVehicle, TrackPoint

BASE_URL = "https://api.samsara.com"
MPG_DAYS = 30
_accounts: dict[str, str] = {}  # vehicle id -> the account it is in, filled as vehicles are listed (see _account_of)


# Returns every Samsara vehicle of every account; VINs are trimmed and upper-cased so they compare cleanly with
# Datatruck. A truck that moved to another carrier's account is in both, its old record no longer reporting.
def vehicles() -> list[SamsaraVehicle]:
    found = []
    for account in config.SAMSARA_ACCOUNTS:
        with _client(account) as client:
            listed = [v for page in _pages(client, "/fleet/vehicles", {"limit": 512}) for v in page]
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


# The account a vehicle is in. Vehicle ids differ between accounts (a truck moved to another carrier gets a new
# record there), so the accounts' vehicle lists tell; they are listed again when a vehicle isn't known yet (after a
# restart, or a truck just added). Raises LookupError for a vehicle in none of them.
def _account_of(samsara_id: str) -> str:
    if samsara_id not in _accounts:
        for account in config.SAMSARA_ACCOUNTS:
            with _client(account) as client:
                _accounts.update({v["id"]: account for page in _pages(client, "/fleet/vehicles", {"limit": 512})
                                  for v in page})
    if samsara_id not in _accounts:
        raise LookupError(f"Samsara vehicle {samsara_id} is in none of the accounts {', '.join(config.SAMSARA_ACCOUNTS)}")
    return _accounts[samsara_id]


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
