# Tests the fuel baseline rules: station groups, Monday weeks, weekly totals, and what counts as a full week.
from datetime import date
from itertools import count

from base import fuel
from base.models import FuelLine

_ids = count(1)


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
    assert fuel.is_loves(line(location="LOVES #220 TRAVEL STOP")) and not fuel.is_loves(line(location="PILOT 445"))


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


# The running week is left out; the latest full week is compared with the average of the ones before it. A week
# with no price sheet has no network discount.
def test_baseline_full_weeks_only():
    lines = [line(day="2026-09-29", gallons=100), line(day="2026-10-06", gallons=200), line(day="2026-10-13", gallons=300),
             line(day="2026-10-20", gallons=999)]  # the week of Oct 19 is still running on Oct 21
    b = fuel.baseline(lines, {"2026-10-12": 0.5}, today=date(2026, 10, 21), linked_units=set(), weeks=26, breakdown_weeks=4)
    assert [w["week"] for w in b["weeks"]] == ["2026-09-28", "2026-10-05", "2026-10-12"]
    assert b["latest"]["gallons"] == 300 and b["before"]["gallons"] == 150
    assert [w["network_discount"] for w in b["weeks"]] == [None, None, 0.5]
    assert b["data_through"] == "2026-10-20"


# DEF is counted on its own, outside the diesel figures.
def test_def_kept_apart():
    b = fuel.baseline([line(), line(product="DEFD", gallons=10, billed=40.0)], {}, today=date(2026, 10, 21),
                      linked_units=set(), weeks=26, breakdown_weeks=4)
    assert b["latest"]["gallons"] == 100 and b["latest"]["def_spend"] == 40


# Breakdowns group the recent weeks, and the gaps count lines with no truck and trucks Samsara can't see.
def test_breakdowns_and_gaps():
    lines = [line(company="TTL", unit="340"), line(company="DT", unit="717"), line(company="DT", unit=None)]
    b = fuel.baseline(lines, {}, today=date(2026, 10, 21), linked_units={"340"}, weeks=26, breakdown_weeks=4)
    by_company = {r["name"]: r["gallons"] for r in b["recent"]["breakdowns"]["company"]}
    assert by_company == {"DT": 200, "TTL": 100}
    assert b["recent"]["gaps"] == {"lines": 3, "without_truck": 1, "without_driver": 0, "trucks": 2, "trucks_not_in_samsara": 1}


# Love's and elsewhere get their own discount per gallon, so the two can be shown side by side.
def test_summarize_discount_by_station():
    s = fuel.summarize([line(gallons=90, billed=0, pump=63.0), line(gallons=10, location="PILOT 1", billed=0, pump=1.0)])
    assert (round(s["loves_discount_per_gal"], 4), round(s["outside_discount_per_gal"], 4)) == (0.7, 0.1)
    assert s["outside_lines"] == 1


# Fuel bought outside Love's costs what it was billed minus the same gallons at the Love's price per gallon; with no
# Love's fill (nothing to compare with) or none outside, there is no number.
def test_outside_extra():
    s = fuel.summarize([line(gallons=100, billed=500.0), line(gallons=50, billed=280.0, location="PILOT 1")])
    assert round(s["outside_extra"], 2) == 280 - 50 * 5.0
    assert fuel.summarize([line()])["outside_extra"] is None
    assert fuel.summarize([line(location="PILOT 1")])["outside_extra"] is None


# A week's network discount is the average of its sheet days; a Sunday belongs to the week before.
def test_network_by_week():
    weeks = fuel.network_by_week({"2026-10-14": 0.5, "2026-10-18": 0.6, "2026-10-19": 0.7})
    assert {w: round(v, 4) for w, v in weeks.items()} == {"2026-10-12": 0.55, "2026-10-19": 0.7}


# "This week so far" is compared with last week up to the same weekday and time as the newest purchase.
def test_live_compares_same_hours_of_last_week():
    lines = [line(day="2026-10-19", gallons=100),                       # Monday this week, 10:00
             line(day="2026-10-12", gallons=40),                        # Monday last week, 10:00: same hours, counts
             line(day="2026-10-13", gallons=999)]                       # Tuesday last week: after the same hours
    live = fuel.live(lines, {}, feed_size=5, days=3, outside_limit=5)
    assert live["latest"] == "2026-10-19 10:00" and live["week_start"] == "2026-10-19"
    assert live["this_week"]["gallons"] == 100 and live["last_week_same"]["gallons"] == 40
    assert [d["day"] for d in live["daily"]] == ["2026-10-17", "2026-10-18", "2026-10-19"]


# Drivers outside Love's add up what their fills paid above the cheapest Love's nearby, counting only the fills that
# could be told; Love's fills aren't listed. Most paid above first.
def test_outside_by_driver_paid_above():
    loves, a1, a2, b = (line(), line(location="PILOT 1", driver=2), line(location="TA 5", driver=2),
                        line(location="PILOT 1", driver=3))
    rows = fuel.outside_by_driver([loves, a1, a2, b], {a1.line_id: 30.0, a2.line_id: None, b.line_id: -5.0}, limit=5)
    assert [(r["fills"], r["told"], r["paid_above"]) for r in rows] == [(2, 1, 30.0), (1, 1, -5.0)]


# Local times move by whole days and keep their format.
def test_shift_days():
    assert fuel.shift_days("2026-10-19 09:45", -7) == "2026-10-12 09:45"
    assert fuel.shift_days("2026-10-01", -1) == "2026-09-30"


# With no fuel lines at all the baseline is empty instead of failing.
def test_baseline_empty():
    b = fuel.baseline([], {}, today=date(2026, 10, 21), linked_units=set(), weeks=26, breakdown_weeks=4)
    assert b["weeks"] == [] and b["latest"] is None and b["recent"]["from"] is None


# Percentiles count gallons, not fills: one big fill outweighs two small ones.
def test_gallon_percentile():
    pairs = [(5.0, 20.0), (6.0, 20.0), (7.0, 160.0)]
    assert fuel.gallon_percentile(pairs, 0.1) == 5.0 and fuel.gallon_percentile(pairs, 0.3) == 7.0
    assert fuel.gallon_percentile([], 0.5) is None


# Love's pump price and discount: the average is all dollars over all gallons, the band holds the middle 80% of the
# gallons, and the extremes are single fills; fills outside Love's are left out.
def test_loves_spread():
    lines = [line(gallons=5, pump=25.0, billed=25.0), line(gallons=90, pump=540.0, billed=495.0),
             line(gallons=5, pump=35.0, billed=30.0), line(gallons=100, pump=900.0, billed=900.0, location="PILOT 1")]
    s = fuel.loves_spread(lines)
    assert s["loves_pump"] == {"average": 6.0, "low": 6.0, "high": 6.0, "lowest": 5.0, "highest": 7.0}
    assert round(s["loves_discount"]["average"], 4) == 0.5 and s["loves_discount"]["lowest"] == 0.0
    assert fuel.loves_spread([line(location="PILOT 1")]) == {"loves_pump": None, "loves_discount": None}


# The discount missed outside Love's: each outside fill's gallons at the day's Love's discount per gallon, less what it got
# (never below zero); none without Love's fills to go by. The day's row carries it.
def test_missed_discount():
    loves = [line(gallons=100, billed=550, pump=600), line(gallons=100, billed=530, pump=600)]     # 60c/gal on average
    pilot = line(gallons=50, billed=290, pump=295, location="PILOT #1")                            # got 10c/gal
    cheap = line(gallons=10, billed=50, pump=60, location="TA #2")                                 # got $1/gal: nothing missed
    assert fuel.missed_discount(loves + [pilot, cheap]) == 0.6 * 50 - 5
    assert fuel.missed_discount([pilot]) is None and fuel.missed_discount(loves) == 0
    assert fuel.daily(loves + [pilot], "2026-10-13", 1)[0]["missed"] == 25


# Kept and missed by period: a week holds its days, our stops' part comes out of the fleet's own, a month without fills is
# zeros, and the months run back across the new year.
def test_discount_periods():
    lines = [line(day="2026-10-13", gallons=100, billed=550, pump=600), line(day="2026-10-14", gallons=100, billed=550, pump=600),
             line(day="2026-10-14", gallons=50, billed=290, pump=295, location="PILOT #1")]
    weeks = fuel.discount_periods(lines, {"2026-10-14": 20.0}, "2026-10-15", "week", 2)
    assert [w["key"] for w in weeks] == ["2026-10-05", "2026-10-12"] and weeks[0]["discount"] == 0
    assert weeks[1]["discount"] == 105 and weeks[1]["ours"] == 20 and weeks[1]["own"] == 85 and weeks[1]["missed"] == 0.5 * 50 - 5
    assert weeks[1]["outside_gallons"] == 50 and weeks[1]["gallons"] == 250
    days = fuel.discount_periods(lines, {}, "2026-10-14", "day", 2)
    assert [d["key"] for d in days] == ["2026-10-13", "2026-10-14"] and days[0]["discount"] == 50
    assert [m["key"] for m in fuel.discount_periods(lines, {}, "2026-02-03", "month", 3)] == ["2025-12", "2026-01", "2026-02"]
