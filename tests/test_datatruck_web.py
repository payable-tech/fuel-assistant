# Tests how raw Datatruck web records become our objects: times kept as written, card numbers dropped.
from base.sources import datatruck_web

RAW_LINE = {
    "id": 9, "date": "2026-10-18T09:38:00Z", "transaction_type": "fuel", "product": "ULSD", "quantity": 120.5,
    "total": 700.0, "amount": 640.0, "fee": 1.0, "billable": True, "location": " LOVES #220 TRAVEL STOP ",
    "city": "Ardmore", "state": "OK", "mc_number": {"id": 1, "company_name": "TAYLOR TRANSPORTS LLC"},
    "truck": {"id": 5, "unit_number": " 0340 ", "ownership": "company"},
    "driver": {"id": 7, "full_name": "Sample Driver", "driver_type": "lease"},
    "card": {"id": 33, "number": "7083050030000000000"}, "card_number": "7083050030000000000",
}


# A fuel line keeps the Central clock time as written and Datatruck's card id, never the card number.
def test_fuel_line_mapping():
    f = datatruck_web._fuel_line(RAW_LINE)
    assert f.fueled_at == "2026-10-18 09:38" and f.unit == "0340" and f.location == "LOVES #220 TRAVEL STOP"
    assert (f.gallons, f.pump_total, f.billed, f.billable) == (120.5, 700.0, 640.0, True)
    assert f.card_id == 33 and "7083050030000000000" not in repr(f)


# A line without truck or driver maps to empty values instead of failing.
def test_fuel_line_without_truck_or_driver():
    f = datatruck_web._fuel_line(RAW_LINE | {"truck": None, "driver": None, "card": None})
    assert (f.unit, f.truck_ownership, f.driver_id, f.driver_type, f.card_id) == (None, None, None, None, None)


# A line read twice (pushed onto the next page by a new purchase while the pages are read) is kept once.
def test_fuel_lines_once_each(monkeypatch):
    pages = [RAW_LINE | {"id": 3}, RAW_LINE | {"id": 2}, RAW_LINE | {"id": 2}, RAW_LINE | {"id": 1}]
    monkeypatch.setattr(datatruck_web, "_all", lambda path, params: pages)
    assert [l.line_id for l in datatruck_web.fuel_lines()] == [3, 2, 1]


# A fuel card keeps who it belongs to and how it is charged; of its number only the last four digits, never the whole.
def test_fuel_card_mapping():
    c = datatruck_web._fuel_card({"id": 4, "number": "7083050030000007539", "mc_number": {"company_name": "DT"},
                                  "assigned_to": "driver", "assigned_driver": {"id": 7}, "unit_number": "717",
                                  "is_billable": True, "fuel_deduction_policy": "retail_plus_fee", "is_card_active": True})
    assert (c.card_id, c.driver_id, c.unit, c.billable, c.deduction_policy, c.active) == (4, 7, "717", True, "retail_plus_fee", True)
    assert c.last4 == "7539" and "708305003" not in repr(c)
    assert datatruck_web._fuel_card({"id": 5, "number": None}).last4 is None
