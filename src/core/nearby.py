# What a fill paid above the cheapest Love's near it that day (pure), for the Live view's list of fills outside Love's.
# Near is a straight-line circle around the truck (its road ahead isn't known): the most that could have been saved.
from datetime import date, timedelta

from core import geo
from core.fuel import is_loves, store_no
from models import FillLookup, FuelLine, Store

LAT_MI = 69.0  # miles in one degree of latitude: stores farther north or south than this skip the exact distance


# The newest price sheet ({store_no: our price}) on or before a day, when it is at most `max_age` days older; else None.
def sheet_on(day: str, sheets: dict[str, dict[str, float]], max_age: int) -> dict[str, float] | None:
    newest = max((d for d in sheets if d <= day), default=None)
    if newest is None or date.fromisoformat(day) - date.fromisoformat(newest) > timedelta(days=max_age):
        return None
    return sheets[newest]


# Our lowest price at any Love's on a sheet within `near_mi` (straight line) of a point; None when none is that close.
def cheapest_near(point: geo.Point, sheet: dict[str, float], stores: dict[str, Store], near_mi: float) -> float | None:
    return min((net for no, net in sheet.items() if no in stores and abs(stores[no].lat - point[0]) * LAT_MI <= near_mi
                and geo.miles(point, (stores[no].lat, stores[no].lng)) <= near_mi), default=None)


# Where a fill happened: a Love's fill at its store, any other where the truck's GPS was (its lookup); None when not
# known.
def place_of(line: FuelLine, stores: dict[str, Store], lookups: dict[int, FillLookup]) -> geo.Point | None:
    if is_loves(line):
        store = stores.get(store_no(line.location) or "")
        return (store.lat, store.lng) if store else None
    found = lookups.get(line.line_id)
    return (found.lat, found.lng) if found and found.lat is not None else None


# What a fill paid above the cheapest Love's within `near_mi` that day, in dollars (below zero: it was cheaper); None
# when that can't be told (no price sheet for the day, the place not known yet, no Love's that close).
def paid_above(line: FuelLine, sheets: dict[str, dict[str, float]], stores: dict[str, Store],
               lookups: dict[int, FillLookup], near_mi: float, max_age: int) -> float | None:
    sheet = sheet_on(line.fueled_at[:10], sheets, max_age)
    point = place_of(line, stores, lookups)
    cheapest = cheapest_near(point, sheet, stores, near_mi) if sheet and point else None
    return line.billed - cheapest * line.gallons if cheapest is not None else None
