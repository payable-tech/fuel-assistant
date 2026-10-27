# Tests the fuel baseline rules: station groups, Monday weeks, weekly totals, and what counts as a full week.
from datetime import date
from itertools import count

from core import fuel
from models import FuelLine

_ids = count(1)


# A market price function for tests that don't look at the market: no price for anything.
def no_market(line):
    return None


# Builds one fuel line with sensible defaults; tests change only what they check.
def line(day="2026-10-13", gallons=100.0, billed=500.0, pump=560.0, location="LOVES #220 TRAVEL STOP", billable=True,
         driver=1, driver_type="lease", unit="340", product="ULSD", company="TTL", ownership="company") -> FuelLine:
    return FuelLine(line_id=next(_ids), fueled_at=f"{day} 10:00", transaction_type="fuel", product=product,
                    gallons=gallons, pump_total=pump, billed=billed, fee=0.0, billable=billable, location=location,
                    city="", state="TX", company=company, unit=unit, truck_ownership=ownership, driver_id=driver,
                    driver_name="", driver_type=driver_type, card_id=None)


# Station names are grouped by how they start, so look-alikes are not counted as Love's.
def test_station_groups():
    assert fuel.chain("LOVES #220 TRAVEL STOP") == "Love's"
    assert fuel.chain("loves  #701 travel sto") == "Love's"
    assert fuel.chain("CLOVERDALE TRAVEL PLAZA") == "Other stations"
    assert fuel.chain("GOLDEN GATE-LOVELOCK") == "Other stations"
    assert fuel.chain("FJ-SMITHTON") == fuel.chain("ONE9 PRIDE 12") == fuel.chain("PILOT 445") == "Pilot / Flying J / One9"
    assert fuel.chain("TA BREEZEWOOD") == fuel.chain("PETRO 312") == "TA / Petro"
    assert fuel.chain("TAYLOR FUEL") == "Other stations"


# A week starts on Monday: Sunday belongs to the Monday before it.
def test_week_starts_monday():
    assert fuel.week_of("2026-10-12") == "2026-10-12"        # Monday
    assert fuel.week_of("2026-10-18 23:59") == "2026-10-12"  # Sunday
    assert fuel.week_of("2026-10-19") == "2026-10-19"


# Totals split the discount by who paid and count Love's gallons and distinct drivers.
def test_summarize():
    s = fuel.summarize([line(billable=True), line(billable=False, driver=2), line(location="PILOT 445", pump=520.0)])
    assert s["gallons"] == 300 and s["spend"] == 1500 and s["discount"] == 1640 - 1500
    assert s["discount_billable"] == 60 + 20 and s["discount_company"] == 60
    assert round(s["loves_share"], 3) == 0.667 and s["drivers"] == 2


# The running week is left out; the latest full week is compared with the average of the ones before it.
def test_baseline_full_weeks_only():
    lines = [line(day="2026-09-29", gallons=100), line(day="2026-10-06", gallons=200), line(day="2026-10-13", gallons=300),
             line(day="2026-10-20", gallons=999)]  # the week of Oct 19 is still running on Oct 21
    b = fuel.baseline(lines, today=date(2026, 10, 21), linked_units=set(), weeks=26, breakdown_weeks=4, price_of=no_market)
    assert [w["week"] for w in b["weeks"]] == ["2026-09-28", "2026-10-05", "2026-10-12"]
    assert b["latest"]["gallons"] == 300 and b["before"]["gallons"] == 150
    assert b["data_through"] == "2026-10-20"


# DEF is counted on its own, outside the diesel figures.
def test_def_kept_apart():
    b = fuel.baseline([line(), line(product="DEFD", gallons=10, billed=40.0)], today=date(2026, 10, 21),
                      linked_units=set(), weeks=26, breakdown_weeks=4, price_of=no_market)
    assert b["latest"]["gallons"] == 100 and b["latest"]["def_spend"] == 40


# Breakdowns group the recent weeks, and the gaps count lines with no truck and trucks Samsara can't see.
def test_breakdowns_and_gaps():
    lines = [line(company="TTL", unit="340"), line(company="DT", unit="717"), line(company="DT", unit=None)]
    b = fuel.baseline(lines, today=date(2026, 10, 21), linked_units={"340"}, weeks=26, breakdown_weeks=4, price_of=no_market)
    by_company = {r["name"]: r["gallons"] for r in b["recent"]["breakdowns"]["company"]}
    assert by_company == {"DT": 200, "TTL": 100}
    assert b["recent"]["gaps"] == {"lines": 3, "without_truck": 1, "without_driver": 0, "trucks": 2, "trucks_not_in_samsara": 1}


# Love's and elsewhere get their own discount per gallon, so the two can be shown side by side.
def test_summarize_discount_by_station():
    s = fuel.summarize([line(gallons=90, billed=0, pump=63.0), line(gallons=10, location="PILOT 1", billed=0, pump=1.0)])
    assert (round(s["loves_discount_per_gal"], 4), round(s["outside_discount_per_gal"], 4)) == (0.7, 0.1)
    assert s["outside_lines"] == 1


# "This week so far" is compared with last week up to the same weekday and time as the newest purchase.
def test_live_compares_same_hours_of_last_week():
    lines = [line(day="2026-10-19", gallons=100),                       # Monday this week, 10:00
             line(day="2026-10-12", gallons=40),                        # Monday last week, 10:00: same hours, counts
             line(day="2026-10-13", gallons=999)]                       # Tuesday last week: after the same hours
    live = fuel.live(lines, feed_size=5, days=3, outside_limit=5)
    assert live["latest"] == "2026-10-19 10:00" and live["week_start"] == "2026-10-19"
    assert live["this_week"]["gallons"] == 100 and live["last_week_same"]["gallons"] == 40
    assert [d["day"] for d in live["daily"]] == ["2026-10-17", "2026-10-18", "2026-10-19"]


# Outside Love's, the discount missed is the gallons times how much smaller the discount was than Love's average.
def test_outside_by_driver_missed_discount():
    lines = [line(gallons=100, billed=500, pump=560),                                   # Love's: 60c a gallon
             line(gallons=50, billed=500, pump=505, location="PILOT 1", driver=2)]      # outside: 10c a gallon
    rows = fuel.outside_by_driver(lines, loves_discount=0.60, limit=5)
    assert len(rows) == 1 and rows[0]["fills"] == 1 and round(rows[0]["missed"], 6) == 25.0


# Local times move by whole days and keep their format.
def test_shift_days():
    assert fuel.shift_days("2026-10-19 09:45", -7) == "2026-10-12 09:45"
    assert fuel.shift_days("2026-10-01", -1) == "2026-09-30"


# With no fuel lines at all the baseline is empty instead of failing.
def test_baseline_empty():
    b = fuel.baseline([], today=date(2026, 10, 21), linked_units=set(), weeks=26, breakdown_weeks=4, price_of=no_market)
    assert b["weeks"] == [] and b["latest"] is None and b["recent"]["from"] is None


# Against the market: what the gallons would cost at market price, and how much less we paid, per gallon too.
def test_vs_market():
    v = fuel.vs_market([line(gallons=100, billed=500.0), line(gallons=100, billed=540.0)], lambda l: 5.50)
    assert (v["market_value"], v["saved_vs_market"], v["saved_per_gal"]) == (1100.0, 60.0, 0.30)


# One line without a market price leaves the whole comparison unknown, never half-counted.
def test_vs_market_unknown_without_price():
    v = fuel.vs_market([line(), line(day="2026-10-20")], lambda l: 5.50 if l.fueled_at < "2026-10-19" else None)
    assert v["market_value"] is None and v["saved_per_gal"] is None
