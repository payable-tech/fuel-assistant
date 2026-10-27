# Datatruck web API (the one Datatruck's own website uses), read-only: fuel lines, fuel cards, trucks, drivers.
# Login: the .env refresh token is traded with AWS Cognito for a 1-hour token, renewed automatically before it runs out.
import json
import time

import httpx

import config
from models import DatatruckDriver, DatatruckTruck, FuelCard, FuelLine

PAGE_SIZE = 5000        # Datatruck accepts this many rows per page
RECENT_PAGE_SIZE = 1000 # about 5 days of fuel lines: one page usually covers a recent refresh
RENEW_EARLY_SEC = 300   # renew the token this long before it expires

_session = {"token": "", "expires": 0.0}  # the current 1-hour token, shared by every job in this process


# Returns every fuel-card purchase line Datatruck has, newest first.
def fuel_lines() -> list[FuelLine]:
    return [_fuel_line(r) for r in _all("/v1/fuel/transactions/", {"ordering": "-date"})]


# Returns the fuel lines fueled on or after a local day ("YYYY-MM-DD"), reading newest-first pages only until it
# passes that day. Lines are keyed by id, so a line that shifts to the next page while new ones arrive counts once.
def fuel_lines_since(since_day: str) -> list[FuelLine]:
    found, page = {}, 1
    while True:
        body = _get("/v1/fuel/transactions/", {"ordering": "-date", "page": page, "page_size": RECENT_PAGE_SIZE})
        batch = [_fuel_line(r) for r in body["results"]]
        found.update({l.line_id: l for l in batch if l.fueled_at >= since_day})
        if not body.get("next") or not batch or batch[-1].fueled_at < since_day:
            return list(found.values())
        page += 1


# Returns every fuel card with who it is assigned to and how its purchases are charged.
def fuel_cards() -> list[FuelCard]:
    return [_fuel_card(r) for r in _all("/v1/fuel/cards/list/", {})]


# Returns every truck that is not inactive, with its unit number, VIN and ownership.
def trucks() -> list[DatatruckTruck]:
    active = [{"column": "status", "contains": "is_not", "value": "inactive"}]
    return [_truck(r) for r in _all("/v2/truck/truck/", {"filter": json.dumps(active)})]


# Returns every driver, active or not, with type and employment status.
def drivers() -> list[DatatruckDriver]:
    return [_driver(r) for r in _all("/v2/driver/list/", {})]


# Converts one raw fuel line. Datatruck writes Central time as if it were UTC, so the clock is kept as written.
def _fuel_line(raw: dict) -> FuelLine:
    driver, truck, mc, card = (raw.get(k) or {} for k in ("driver", "truck", "mc_number", "card"))
    return FuelLine(
        line_id=raw["id"], fueled_at=(raw.get("date") or "")[:16].replace("T", " "),
        transaction_type=raw.get("transaction_type") or "", product=raw.get("product") or "",
        gallons=float(raw.get("quantity") or 0), pump_total=float(raw.get("total") or 0),
        billed=float(raw.get("amount") or 0), fee=float(raw.get("fee") or 0), billable=bool(raw.get("billable")),
        location=(raw.get("location") or "").strip(), city=raw.get("city") or "", state=raw.get("state") or "",
        company=mc.get("company_name") or "", unit=(truck.get("unit_number") or "").strip() or None,
        truck_ownership=truck.get("ownership"), driver_id=driver.get("id"), driver_name=driver.get("full_name"),
        driver_type=driver.get("driver_type"), card_id=card.get("id"),
    )


# Converts one raw fuel card, dropping its number.
def _fuel_card(raw: dict) -> FuelCard:
    driver = raw.get("assigned_driver") or {}
    return FuelCard(
        card_id=raw["id"], company=(raw.get("mc_number") or {}).get("company_name") or "",
        assigned_to=raw.get("assigned_to"), driver_id=driver.get("id"),
        unit=(raw.get("unit_number") or "").strip() or None, billable=bool(raw.get("is_billable")),
        deduction_policy=raw.get("fuel_deduction_policy"), active=bool(raw.get("is_card_active")),
    )


# Converts one raw truck; VINs are trimmed and upper-cased so they compare cleanly with Samsara.
def _truck(raw: dict) -> DatatruckTruck:
    return DatatruckTruck(dt_id=raw["id"], unit=(raw.get("unit_number") or "").strip(),
                          vin=(raw.get("vin") or "").strip().upper(), status=raw.get("status") or "",
                          ownership=raw.get("ownership"))


# Converts one raw driver.
def _driver(raw: dict) -> DatatruckDriver:
    truck = raw.get("assigned_truck") or {}
    return DatatruckDriver(
        driver_id=raw["id"], full_name=raw.get("full_name") or (raw.get("account") or {}).get("full_name") or "",
        driver_type=raw.get("driver_type"), employee_status=raw.get("new_employee_status"),
        company=(raw.get("mc_number") or {}).get("company_name") or "", unit=(truck.get("unit_number") or "").strip() or None,
    )


# Fetches every page of a list endpoint and returns all its rows.
def _all(path: str, params: dict) -> list[dict]:
    rows, page = [], 1
    while True:
        body = _get(path, params | {"page": page, "page_size": PAGE_SIZE})
        rows += body["results"]
        if not body.get("next"):
            return rows
        page += 1


# One authorized GET against this company's Datatruck web API.
def _get(path: str, params: dict) -> dict:
    response = httpx.get(f"https://{config.secret('DT_SLUG')}.datatruck.io/api{path}", params=params, timeout=120,
                         headers={"Authorization": f"Bearer {_token()}"})
    response.raise_for_status()
    return response.json()


# Returns a valid 1-hour token, trading the .env refresh token for a new one when the current one is about to expire.
def _token() -> str:
    if time.time() < _session["expires"] - RENEW_EARLY_SEC:
        return _session["token"]
    response = httpx.post(
        config.DT_COGNITO_URL, timeout=30,
        headers={"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"},
        json={"AuthFlow": "REFRESH_TOKEN_AUTH", "ClientId": config.DT_COGNITO_CLIENT_ID,
              "AuthParameters": {"REFRESH_TOKEN": config.secret("DT_WEB_REFRESH_TOKEN")}},
    )
    if response.status_code != 200:
        # usually: Bob signed out of Datatruck in the browser, which revokes the refresh token
        raise RuntimeError(f"Datatruck web login refused ({response.json().get('__type', response.status_code)}). "
                           "Put a fresh DT_WEB_REFRESH_TOKEN in .env (see the note there).")
    result = response.json()["AuthenticationResult"]
    _session.update(token=result["IdToken"], expires=time.time() + result["ExpiresIn"])
    return _session["token"]
