# Tests what a fill paid above the cheapest Love's near it that day: which sheet prices the day, where the fill was,
# and which Love's are near enough.
from itertools import count

from base.models import FillLookup, FuelLine, Store
from features.dashboard import nearby

_ids = count(1)
# Love's #2 is ~21 mi north of #1 and cheaper; #3 is far away and cheapest
STORES = {no: Store(no, "Town", "OK", lat, lng, 6.0, 0.0, "2026-10-19")
          for no, lat, lng in (("1", 35.0, -97.0), ("2", 35.3, -97.0), ("3", 40.0, -90.0))}
SHEETS = {"2026-10-19": {"1": 5.50, "2": 5.00, "3": 4.00}}


# Builds one diesel fill of 100 gallons; tests change only what they check.
def line(at="2026-10-20 10:00", billed=550.0, location="LOVES #1 TRAVEL STOP", line_id=None) -> FuelLine:
    return FuelLine(line_id=line_id or next(_ids), fueled_at=at, transaction_type="fuel", product="ULSD", gallons=100.0,
                    pump_total=600.0, billed=billed, fee=0.0, billable=False, location=location, city="", state="OK",
                    company="TTL", unit="A", truck_ownership="company", driver_id=1, driver_name="",
                    driver_type="company_driver", card_id=None)


# A day uses the newest sheet on or before it, but not one more than a few days old (the sheets have gaps).
def test_sheet_on():
    assert nearby.sheet_on("2026-10-22", SHEETS, 3) == SHEETS["2026-10-19"]
    assert nearby.sheet_on("2026-10-23", SHEETS, 3) is None and nearby.sheet_on("2026-10-18", SHEETS, 3) is None


# A Love's fill is at its store, any other where the truck's GPS was; it paid above the cheapest Love's within reach
# (not the cheaper one far away), below zero when it was cheaper. With no place, sheet or Love's near it can't be told.
def test_paid_above():
    lookups = {90: FillLookup(90, 35.0, -97.0, None), 91: FillLookup(91, 35.0, -97.0, None)}
    assert nearby.paid_above(line(), SHEETS, STORES, {}, 50, 3) == 550 - 100 * 5.00
    assert nearby.paid_above(line(), SHEETS, STORES, {}, 10, 3) == 0  # #2 is too far: #1 itself is the cheapest
    assert nearby.paid_above(line(location="PILOT 445", billed=600.0, line_id=90), SHEETS, STORES, lookups, 50, 3) == 100
    assert nearby.paid_above(line(location="PILOT 445", billed=450.0, line_id=91), SHEETS, STORES, lookups, 50, 3) == -50
    assert nearby.paid_above(line(location="PILOT 445"), SHEETS, STORES, lookups, 50, 3) is None
    assert nearby.paid_above(line(at="2026-10-25 10:00"), SHEETS, STORES, {}, 50, 3) is None
    assert nearby.paid_above(line(location="LOVES #9 TRAVEL STOP"), SHEETS, STORES, {}, 50, 3) is None  # unknown store
