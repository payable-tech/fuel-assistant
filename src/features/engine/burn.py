# Live MPG (pure): the engine as a fuel meter. Fuel burned follows engine load x RPM x time, so a running total of that,
# calibrated per truck against its fuel gauge, tells how many gallons a stretch really took, without the gauge's wobble.
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from statistics import median

from base.models import EngineHistory, FuelReading

GAP_S = 600  # engine readings further apart than this: the engine was off in between, nothing burned
GAUGE_SPAN_S = 600  # the gauge at a moment is its middle reading this close to it, to calm its wobble

Meter = tuple[list[float], list[float]]  # (times in seconds, running total of load x RPM x seconds at each)


# The engine's running total of load x RPM x time. Each load reading is paired with the RPM reading just before it.
def meter(history: EngineHistory) -> Meter:
    rpm_at, rpm = [s.at.timestamp() for s in history.rpm], [s.value for s in history.rpm]
    times, totals, total, last, rate = [], [], 0.0, None, 0.0
    for sample in history.load:
        at = sample.at.timestamp()
        i = bisect_right(rpm_at, at) - 1
        if i < 0 or at - rpm_at[i] > GAP_S:
            continue
        if last is not None and at - last <= GAP_S:
            total += rate * (at - last)
        last, rate = at, sample.value * rpm[i]
        times.append(at)
        totals.append(total)
    return times, totals


# How many gallons one unit of the meter burns on this truck: gauge drops over stretches of `stretch_mi` driven with no
# fill-up, against the meter over the same stretches. None with fewer than `min_stretches` usable stretches.
def gal_per_unit(m: Meter, history: EngineHistory, gauge: list[FuelReading], tank_gal: float, stretch_mi: float,
                 fill_rise: float, min_stretches: int) -> tuple[float, int] | None:
    odo_at, odo = [s.at.timestamp() for s in history.miles], [s.value for s in history.miles]
    g_at, g_pct = [r.at.timestamp() for r in gauge], [r.pct for r in gauge]
    fills = [g_at[i] for i in range(1, len(g_pct)) if g_pct[i] - g_pct[i - 1] >= fill_rise]
    gallons, units, stretches = 0.0, 0.0, 0
    for start_mile in _steps(odo, stretch_mi):
        a, b = bisect_left(odo, start_mile), bisect_left(odo, start_mile + stretch_mi)
        if b >= len(odo):
            break
        first, second = _level(g_at, g_pct, odo_at[a]), _level(g_at, g_pct, odo_at[b])
        if first is None or second is None or first <= second or any(odo_at[a] <= f <= odo_at[b] for f in fills):
            continue
        used = _total(m, odo_at[b]) - _total(m, odo_at[a])
        if used > 0:
            gallons += (first - second) / 100 * tank_gal
            units += used
            stretches += 1
    return (gallons / units, stretches) if stretches >= min_stretches else None


# MPG over the time between two moments, from `miles` driven and the meter; None with too few miles to say.
def live_mpg(m: Meter, factor: float, miles: float, start: datetime, end: datetime, min_miles: float,
             mpg_range: tuple[float, float]) -> float | None:
    gallons = factor * (_total(m, end.timestamp()) - _total(m, start.timestamp()))
    if miles < min_miles or gallons <= 0:
        return None
    return min(max(miles / gallons, mpg_range[0]), mpg_range[1])


# The MPG to expect on the road ahead: halfway between the truck's average and how it runs now (load, wind), which
# predicted the gauge best on 12 trucks. Just the average without a live figure.
def forecast_mpg(average: float, live: float | None) -> float:
    return (average + live) / 2 if live else average


# The MPG the hard stop counts on: the lower of the two, made `worse` of that, so running out is the unlikely mistake.
def cautious_mpg(average: float, live: float | None, worse: float) -> float:
    return min(average, live or average) * worse


# The fuel now, calmed: the middle of the last `span`'s readings (at least `at_least` of them, up to `lookback` ago), none
# from before a fill-up, so a wobble can't change a recommendation but a fill-up shows at once. None without readings.
def steady_gauge(readings: list[FuelReading], now: datetime, span: timedelta, lookback: timedelta, at_least: int,
                 fill_rise: float) -> float | None:
    recent = sorted((r for r in readings if now - lookback <= r.at <= now), key=lambda r: r.at)
    rises = [i for i in range(1, len(recent)) if recent[i].pct - recent[i - 1].pct >= fill_rise]  # fill-ups
    recent = recent[rises[-1]:] if rises else recent
    inside = [r for r in recent if r.at >= now - span]
    used = inside if len(inside) >= at_least else recent[-at_least:]  # a stopped truck reports rarely, burns next to nothing
    return median(r.pct for r in used) if used else None


# The gauge at a moment: the middle reading close to it; None without readings.
def _level(times: list[float], pct: list[float], at: float) -> float | None:
    i, j = bisect_left(times, at - GAUGE_SPAN_S), bisect_right(times, at + GAUGE_SPAN_S)
    return median(pct[i:j]) if j > i else None


# The meter's total at a moment.
def _total(m: Meter, at: float) -> float:
    i = bisect_right(m[0], at) - 1
    return m[1][i] if i >= 0 else 0.0


# Where each stretch starts along the odometer.
def _steps(odo: list[float], stretch_mi: float) -> list[float]:
    if not odo:
        return []
    return [odo[0] + k * stretch_mi for k in range(int((odo[-1] - odo[0]) // stretch_mi))]
