# Fuel purchases in figures (pure): what counts as diesel and as Love's, purchases grouped by stop, the company's Monday
# weeks, and the totals, breakdowns and discount chart of the Trends and Live views.
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from base.models import FuelLine

CENTRAL = ZoneInfo("America/Chicago")  # Datatruck purchase times are Central clock time

# Station groups, matched at the start of the station name ("LOVES #220 TRAVEL STOP"). Matching only the start
# keeps "CLOVERDALE TRAVEL PLAZA" and "GOLDEN GATE-LOVELOCK" out of Love's.
CHAINS = [
    ("Love's", re.compile(r"LOVE'?S\b")),
    ("Pilot / Flying J / One9", re.compile(r"(PILOT|FLYING\s*J|FJ|ONE\s?9)\b")),
    ("TA / Petro", re.compile(r"(TA|PETRO)\b")),
]
LOVES = "Love's"
OTHER_STATIONS = "Other stations"
BREAKDOWNS = {  # breakdown name -> the line attribute it groups by
    "company": lambda l: l.company or "Unknown",
    "driver_type": lambda l: l.driver_type or "unknown",
    "truck_ownership": lambda l: l.truck_ownership or "unknown",
    "station": lambda l: chain(l.location),
    "state": lambda l: l.state or "Unknown",
}


# The station group of a fuel line's location.
def chain(location: str) -> str:
    name = location.upper().strip()
    return next((label for label, pattern in CHAINS if pattern.match(name)), OTHER_STATIONS)


# True for a purchase at a Love's.
def is_loves(line: FuelLine) -> bool:
    return chain(line.location) == LOVES


# The store number in a station name or a label: "LOVES #0473 TRAVEL STOP" or "Love's #473 Leary, TX" -> "473".
def store_no(text: str) -> str | None:
    found = re.search(r"#\s*(\d+)", text)
    return (found.group(1).lstrip("0") or "0") if found else None


# True for a diesel purchase: a fuel-card line of diesel ("ULSD") with gallons pumped.
def is_diesel(line: FuelLine) -> bool:
    return line.transaction_type == "fuel" and line.product == "ULSD" and line.gallons > 0


# A truck's diesel purchases grouped by stop, oldest first. A purchase less than `window` after the previous one is
# the same stop (two pumps, a split payment).
def purchase_stops(lines: list[FuelLine], window: timedelta) -> list[list[FuelLine]]:
    stops: list[list[FuelLine]] = []
    for line in sorted((l for l in lines if is_diesel(l)), key=lambda l: l.fueled_at):
        if stops and utc(line.fueled_at) - utc(stops[-1][-1].fueled_at) < window:
            stops[-1].append(line)
        else:
            stops.append([line])
    return stops


# Converts a Datatruck purchase time ("YYYY-MM-DD HH:MM", Central clock time) to UTC, daylight saving included.
def utc(fueled_at: str) -> datetime:
    return datetime.fromisoformat(fueled_at).replace(tzinfo=CENTRAL).astimezone(timezone.utc)


# True for a DEF purchase.
def is_def(line: FuelLine) -> bool:
    return line.transaction_type == "fuel" and line.product == "DEFD"


# The Monday that starts the week of a local day or time ("2026-10-18" or "2026-10-18 09:38").
def week_of(day: str) -> str:
    d = date.fromisoformat(day[:10])
    return (d - timedelta(days=d.weekday())).isoformat()


# Share of gallons in `part` out of `whole`; None when there are no gallons.
def gallon_share(part: list[FuelLine], whole: list[FuelLine]) -> float | None:
    total = sum(l.gallons for l in whole)
    return sum(l.gallons for l in part) / total if total else None


# Discount per gallon of a set of lines (pump price minus what the company paid); None when there are no gallons.
def discount_per_gal(lines: list[FuelLine]) -> float | None:
    gallons = sum(l.gallons for l in lines)
    return sum(l.pump_total - l.billed for l in lines) / gallons if gallons else None


# Totals for a set of diesel lines: gallons, money, discount split by who pays and by station, Love's share, drivers.
def summarize(lines: list[FuelLine]) -> dict:
    gallons = sum(l.gallons for l in lines)
    spend = sum(l.billed for l in lines)
    pump = sum(l.pump_total for l in lines)
    loves = [l for l in lines if is_loves(l)]
    outside = [l for l in lines if not is_loves(l)]
    loves_gallons = sum(l.gallons for l in loves)
    loves_price = sum(l.billed for l in loves) / loves_gallons if loves_gallons else None
    return {
        "lines": len(lines),
        "outside_lines": len(outside),     # fills outside Love's
        "gallons": gallons,
        "spend": spend,                    # what EFS billed the company
        "pump_value": pump,                # the same gallons at the posted pump price
        "price_per_gal": spend / gallons if gallons else None,
        "pump_per_gal": pump / gallons if gallons else None,  # the posted pump price, for comparison
        "discount": pump - spend,          # pump price minus what the company paid
        "discount_billable": sum(l.pump_total - l.billed for l in lines if l.billable),     # kept from drivers
        "discount_company": sum(l.pump_total - l.billed for l in lines if not l.billable),  # lower cost on company fuel
        "loves_share": gallon_share(loves, lines),
        "loves_price_per_gal": loves_price,
        "outside_price_per_gal": sum(l.billed for l in outside) / (gallons - loves_gallons) if gallons > loves_gallons else None,
        # what the gallons bought outside Love's cost above the same gallons at these lines' average Love's price
        "outside_extra": sum(l.billed for l in outside) - (gallons - loves_gallons) * loves_price if outside and loves_price else None,
        "loves_discount_per_gal": discount_per_gal(loves),
        "outside_discount_per_gal": discount_per_gal(outside),
        "billable_share": gallon_share([l for l in lines if l.billable], lines),
        "drivers": len({l.driver_id for l in lines if l.driver_id}),
        "trucks": len({l.unit for l in lines if l.unit}),
    }


# The value that `share` of the gallons were bought at or below (0.1 -> the 10th percentile, counted in gallons, so a
# 150-gallon fill weighs three times a 50-gallon one), from (value, gallons) pairs; None when there are none.
def gallon_percentile(pairs: list[tuple[float, float]], share: float) -> float | None:
    ordered = sorted(pairs)
    total = sum(gallons for _, gallons in ordered)
    bought = 0.0
    for value, gallons in ordered:
        bought += gallons
        if bought >= share * total:
            return value
    return ordered[-1][0] if ordered else None


# How a per-gallon number (`per_gal(line)`) spreads over a set of lines: its average (all dollars over all gallons),
# the range the middle 80% of the gallons fall in, and the lowest and highest single fill. None when there are none.
def spread(lines: list[FuelLine], per_gal) -> dict | None:
    if not lines:
        return None
    pairs = [(per_gal(l), l.gallons) for l in lines]
    return {"average": sum(v * g for v, g in pairs) / sum(g for _, g in pairs),
            "low": gallon_percentile(pairs, 0.1), "high": gallon_percentile(pairs, 0.9),
            "lowest": min(v for v, _ in pairs), "highest": max(v for v, _ in pairs)}


# Love's pump price and Love's discount per gallon, each with how it spread over the week's Love's fills.
def loves_spread(lines: list[FuelLine]) -> dict:
    loves = [l for l in lines if is_loves(l)]
    return {"loves_pump": spread(loves, lambda l: l.pump_total / l.gallons),
            "loves_discount": spread(loves, lambda l: (l.pump_total - l.billed) / l.gallons)}


# The Love's discount offered across all its stores each week, from the price sheets: {week: average of its sheet days},
# given each sheet day's average over every store ({day: dollars per gallon}). Weeks with no sheet are left out.
def network_by_week(daily: dict[str, float]) -> dict[str, float]:
    weeks = defaultdict(list)
    for day, discount in daily.items():
        weeks[week_of(day)].append(discount)
    return {week: mean(days) for week, days in weeks.items()}


# Distinct drivers who fueled, counted per driver type.
def drivers_by_type(lines: list[FuelLine]) -> dict[str, int]:
    seen = defaultdict(set)
    for l in lines:
        if l.driver_id:
            seen[l.driver_type or "unknown"].add(l.driver_id)
    return {kind: len(ids) for kind, ids in seen.items()}


# Splits lines into groups by a key, returning one summarized row per group, largest by gallons first.
def breakdown(lines: list[FuelLine], key) -> list[dict]:
    groups = defaultdict(list)
    for l in lines:
        groups[key(l)].append(l)
    return sorted(({"name": name, **summarize(rows)} for name, rows in groups.items()), key=lambda r: -r["gallons"])


# How concentrated buying outside Love's is: how many drivers do it, and the share of those gallons the top ones hold.
def outside_concentration(lines: list[FuelLine], top: int) -> dict:
    per_driver = defaultdict(float)
    for l in lines:
        if l.driver_id and not is_loves(l):
            per_driver[l.driver_id] += l.gallons
    ranked = sorted(per_driver.values(), reverse=True)
    total = sum(ranked)
    return {"drivers": len(ranked), "top": top, "top_share": sum(ranked[:top]) / total if total else None}


# What is missing from the fuel lines themselves: no truck, no driver, trucks that Samsara can't see.
def data_gaps(lines: list[FuelLine], linked_units: set[str]) -> dict:
    units = {l.unit for l in lines if l.unit}
    return {
        "lines": len(lines),
        "without_truck": sum(1 for l in lines if not l.unit),
        "without_driver": sum(1 for l in lines if not l.driver_id),
        "trucks": len(units),
        "trucks_not_in_samsara": len(units - linked_units),
    }


# Averages each number across weekly rows (skipping missing ones), for comparing a week with the weeks before it.
def average(rows: list[dict]) -> dict:
    numeric = {k for r in rows for k, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    result = {}
    for k in numeric:
        values = [r[k] for r in rows if r.get(k) is not None]
        result[k] = mean(values) if values else None
    return result


# The Trends view's numbers, full weeks only (the week of `today` is still running): the latest week against the average
# of the 4 before it, and breakdowns of the last `breakdown_weeks`. `network`: Love's discount offered, by week.
def baseline(lines: list[FuelLine], network: dict[str, float], today: date, linked_units: set[str], weeks: int,
             breakdown_weeks: int) -> dict:
    running_week = week_of(today.isoformat())
    full = [l for l in lines if week_of(l.fueled_at) < running_week]
    diesel = defaultdict(list)
    def_spend = defaultdict(float)
    for l in full:
        if is_diesel(l):
            diesel[week_of(l.fueled_at)].append(l)
        elif is_def(l):
            def_spend[week_of(l.fueled_at)] += l.billed
    week_keys = sorted(diesel)[-weeks:]
    series = [{"week": w, **summarize(diesel[w]), **loves_spread(diesel[w]), "network_discount": network.get(w),
               "def_spend": def_spend[w], "drivers_by_type": drivers_by_type(diesel[w])}
              for w in week_keys]
    recent_weeks = week_keys[-breakdown_weeks:]
    recent = [l for w in recent_weeks for l in diesel[w]]
    return {
        "data_through": max((l.fueled_at[:10] for l in lines), default=None),
        "running_week": running_week,
        "weeks": series,
        "latest": series[-1] if series else None,
        "before": average(series[-5:-1]),
        "recent": {"from": recent_weeks[0] if recent_weeks else None, "weeks": len(recent_weeks),
                   "total": summarize(recent),
                   "breakdowns": {name: breakdown(recent, key) for name, key in BREAKDOWNS.items()},
                   "outside": outside_concentration(recent, top=25),
                   "gaps": data_gaps(recent, linked_units)},
    }


# Moves a local time ("YYYY-MM-DD HH:MM") or day ("YYYY-MM-DD") by whole days, keeping its format.
def shift_days(when: str, days: int) -> str:
    moved = datetime.fromisoformat(when) + timedelta(days=days)
    return moved.strftime("%Y-%m-%d %H:%M" if len(when) > 10 else "%Y-%m-%d")


# One purchase as the live feed shows it.
def feed_row(l: FuelLine) -> dict:
    return {"fueled_at": l.fueled_at, "unit": l.unit, "driver": l.driver_name, "driver_type": l.driver_type,
            "station": chain(l.location), "location": l.location, "city": l.city, "state": l.state, "gallons": l.gallons,
            "price_per_gal": l.billed / l.gallons, "pump_per_gal": l.pump_total / l.gallons,
            "discount_per_gal": (l.pump_total - l.billed) / l.gallons, "billable": l.billable}


# Drivers who bought outside Love's, with what they paid above the cheapest Love's near each fill that day (`above`:
# dollars by fuel line id, None for a fill it can't be told for yet). Most paid above first.
def outside_by_driver(lines: list[FuelLine], above: dict[int, float | None], limit: int) -> list[dict]:
    drivers = defaultdict(lambda: {"fills": 0, "gallons": 0.0, "told": 0, "paid_above": 0.0, "last": ""})
    for l in sorted(lines, key=lambda l: l.fueled_at):
        if is_loves(l):
            continue
        d = drivers[l.driver_id]
        d.update(driver=l.driver_name or "Unknown driver", unit=l.unit, last=l.fueled_at, station=chain(l.location))
        d["fills"] += 1
        d["gallons"] += l.gallons
        if above.get(l.line_id) is not None:
            d["told"] += 1
            d["paid_above"] += above[l.line_id]
    return sorted(drivers.values(), key=lambda d: -d["paid_above"])[:limit]


# Daily totals for the last `days` days up to `last_day`: gallons at Love's and elsewhere, spend, fills, the discount
# kept and the discount missed outside Love's.
def daily(lines: list[FuelLine], last_day: str, days: int) -> list[dict]:
    rows = []
    for back in range(days - 1, -1, -1):
        day = shift_days(last_day, -back)
        today = [l for l in lines if l.fueled_at[:10] == day]
        s = summarize(today)
        rows.append({"day": day, "loves_gallons": s["gallons"] * (s["loves_share"] or 0),
                     "outside_gallons": s["gallons"] * (1 - (s["loves_share"] or 0)), "spend": s["spend"],
                     "fills": s["lines"], "outside_fills": s["outside_lines"], "loves_share": s["loves_share"],
                     "gallons": s["gallons"], "discount": s["discount"], "missed": missed_discount(today)})
    return rows


# The Live tab's discount chart (the user's ask, 2026-11-04) over the last `count` days, weeks or months to `last_day`:
# the discount kept (the part at our stops, `ours` by day, apart), the discount missed outside Love's, and the gallons.
def discount_periods(lines: list[FuelLine], ours: dict[str, float], last_day: str, period: str, count: int) -> list[dict]:
    keys = period_keys(last_day, period, count)
    # periods without fills stay zeros; the last one is still in progress
    rows = {k: {"key": k, "discount": 0.0, "ours": 0.0, "missed": 0.0, "gallons": 0.0, "outside_gallons": 0.0} for k in keys}
    by_day: dict[str, list[FuelLine]] = {}
    for l in lines:
        by_day.setdefault(l.fueled_at[:10], []).append(l)
    for day in set(by_day) | set(ours):
        row = rows.get(_period_key(day, period))
        if row is None:
            continue
        today = by_day.get(day, [])
        s = summarize(today)
        row["discount"] += s["discount"]
        row["missed"] += missed_discount(today) or 0.0
        row["gallons"] += s["gallons"]
        row["outside_gallons"] += sum(l.gallons for l in today if not is_loves(l))
        row["ours"] += ours.get(day, 0.0)
    return [r | {"own": r["discount"] - r["ours"]} for r in rows.values()]


# The day, week or month a day ("YYYY-MM-DD") falls in, as the chart names it: the day, the week's Monday, "YYYY-MM".
def _period_key(day: str, period: str) -> str:
    return {"day": day, "week": week_of(day), "month": day[:7]}[period]


# The last `count` periods' keys up to the one holding `last_day`, oldest first.
def period_keys(last_day: str, period: str, count: int) -> list[str]:
    if period == "day":
        return [shift_days(last_day, -k) for k in range(count - 1, -1, -1)]
    if period == "week":
        return [shift_days(week_of(last_day), -7 * k) for k in range(count - 1, -1, -1)]
    year, month = int(last_day[:4]), int(last_day[5:7])
    return [f"{year + (month - 1 - k) // 12}-{(month - 1 - k) % 12 + 1:02d}" for k in range(count - 1, -1, -1)]


# The discount missed outside Love's, estimated (the user's ask, 2026-11-04): each such fill's gallons at the day's average
# Love's discount (`lines`: one day's), less the discount it got. None without Love's fills to go by.
def missed_discount(lines: list[FuelLine]) -> float | None:
    loves = [l for l in lines if is_loves(l)]
    loves_gallons = sum(l.gallons for l in loves)
    if not loves_gallons:
        return None
    per_gallon = sum(l.pump_total - l.billed for l in loves) / loves_gallons
    # falls as the fleet moves to Love's
    return sum(max(per_gallon * l.gallons - (l.pump_total - l.billed), 0) for l in lines if not is_loves(l))


# The Live view's numbers up to the newest purchase: this week against last week's same hours, today, the last days, the
# newest purchases, who bought outside Love's (`above`: what each such fill paid above the cheapest Love's near it).
def live(lines: list[FuelLine], above: dict[int, float | None], feed_size: int, days: int, outside_limit: int) -> dict:
    diesel = [l for l in lines if is_diesel(l)]
    if not diesel:
        return {"latest": None}
    latest = max(l.fueled_at for l in diesel)
    week_start = week_of(latest)
    this_week = [l for l in diesel if l.fueled_at >= week_start]
    # last week up to the same weekday and time as the newest purchase, so both sides cover the same hours
    last_week = [l for l in diesel if shift_days(week_start, -7) <= l.fueled_at <= shift_days(latest, -7)]
    week_now = summarize(this_week)
    return {
        "latest": latest,
        "week_start": week_start,
        "this_week": week_now,
        "last_week_same": summarize(last_week),
        "today": summarize([l for l in diesel if l.fueled_at[:10] == latest[:10]]),
        "daily": daily(diesel, latest[:10], days),
        "feed": [feed_row(l) for l in sorted(diesel, key=lambda l: l.fueled_at, reverse=True)[:feed_size]],
        "outside": outside_by_driver(this_week, above, outside_limit),
    }


# Whether a stop told at `made_at` has been overtaken by fuel bought since: a diesel line of the unit after it.
def fueled_since(unit: str, made_at: datetime, lines: list[FuelLine]) -> bool:
    return any(l.unit == unit and is_diesel(l) and utc(l.fueled_at) > made_at for l in lines)


# When a truck last bought diesel among the `lines` (UTC); None when it didn't.
def last_fill(unit: str, lines: list[FuelLine]) -> datetime | None:
    return max((utc(l.fueled_at) for l in lines if l.unit == unit and is_diesel(l)), default=None)
