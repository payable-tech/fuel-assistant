# Datatruck Open API (read-only, API-key login): active orders with their stops. Everything else comes from datatruck_web.
import json
import time
from datetime import datetime

import httpx

import config
from models import Order, Stop

ACTIVE_STATUSES = ["assigned", "dispatched", "in_transit"]
PAGE_SIZE = 25          # the largest page Datatruck allows
PAUSE_SEC = 3.1         # Datatruck allows 20 calls per minute, so calls are kept at least 3 s apart

_last_call = 0.0        # monotonic time of the previous call, shared by every job in this process


# Returns all active orders (assigned, dispatched, in transit) with their stops in route order. An order added or
# changed while the pages are read (~11 pages, half a minute) shifts the list, so one can come on two pages: each
# order is kept once, as last read.
def active_orders() -> list[Order]:
    query = json.dumps([{"column": "status", "value": ACTIVE_STATUSES, "contains": "is_in"}])
    with _client() as client:
        raw = {o["id"]: o for o in _results(client, "/orders/", {"filter": query})}
    return [_order(o) for o in raw.values()]


# Converts one raw order. Its truck comes from the order's trip (the other assignment field is often empty).
def _order(raw: dict) -> Order:
    unit = ((raw.get("trip") or {}).get("truck__unit_number") or "").strip()
    return Order(order_id=raw["id"], load_id=str(raw.get("load_id") or ""), status=raw["status"],
                 unit=unit or None, pickup_at=_time(raw.get("pickup_appointment_time")),
                 stops=tuple(_stop(s, raw["id"]) for s in sorted(raw["stops"], key=lambda s: s["ordering"])))


# Converts one raw stop. Datatruck sends coordinates as text, possibly empty.
def _stop(raw: dict, order_id: int) -> Stop:
    location = raw.get("location") or {}
    return Stop(stop_id=raw["id"], order_id=order_id, seq=raw["ordering"], kind=raw.get("stop_type") or "",
                lat=_float(location.get("latitude")), lng=_float(location.get("longitude")),
                city=location.get("city") or "", state=location.get("state") or "")


# Opens an HTTP client for this company's Datatruck, authorized with the Open API token.
def _client() -> httpx.Client:
    return httpx.Client(base_url=f"https://{config.secret('DT_SLUG')}.datatruck.io/api/v1/openapi", timeout=60,
                        headers={"Authorization": f"Token {config.secret('DT_API_TOKEN')}"})


# Yields every result of a paginated list, one page per call, respecting the rate limit.
def _results(client: httpx.Client, path: str, params: dict):
    page = 1
    while True:
        _wait_turn()
        response = client.get(path, params=params | {"page": page, "page_size": PAGE_SIZE})
        response.raise_for_status()
        body = response.json()
        yield from body["results"]
        if not body["next"]:
            return
        page += 1


# Sleeps until PAUSE_SEC has passed since the previous Datatruck call.
def _wait_turn() -> None:
    global _last_call
    time.sleep(max(0.0, _last_call + PAUSE_SEC - time.monotonic()))
    _last_call = time.monotonic()


# Parses text to a number; empty text gives None.
def _float(text: str | None) -> float | None:
    return float(text) if text not in (None, "") else None


# Parses a Datatruck timestamp ("2026-10-17T12:30:00Z"); empty gives None.
def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None
