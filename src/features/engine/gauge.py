# Reading the fuel gauge (pure): the calm level now, and the level around a purchase. The gauge wobbles by a few
# points and a stopped truck reports rarely, so a single reading is never taken as the level.
from datetime import datetime, timedelta
from statistics import median

from base.models import FuelReading


# The fuel now, calmed: the middle of the last `span`'s readings (at least `at_least` of them, up to `lookback` ago), none
# from before a fill-up, so a wobble can't change a recommendation but a fill-up shows at once. None without readings.
def steady(readings: list[FuelReading], now: datetime, span: timedelta, lookback: timedelta, at_least: int,
           fill_rise: float) -> float | None:
    recent = sorted((r for r in readings if now - lookback <= r.at <= now), key=lambda r: r.at)
    rises = [i for i in range(1, len(recent)) if recent[i].pct - recent[i - 1].pct >= fill_rise]  # fill-ups
    recent = recent[rises[-1]:] if rises else recent
    inside = [r for r in recent if r.at >= now - span]
    used = inside if len(inside) >= at_least else recent[-at_least:]  # a stopped truck reports rarely, burns next to nothing
    return median(r.pct for r in used) if used else None


# The gauge around a stop from `first` to `last`: (lowest reading in the `window` before, highest in the `window`
# after), or None when either side has no reading.
def around(first: datetime, last: datetime, readings: list[FuelReading],
           window: timedelta) -> tuple[float, float] | None:
    lowest = before(first, readings, window)
    after = [r.pct for r in readings if last <= r.at <= last + window]
    return (lowest, max(after)) if lowest is not None and after else None


# The lowest gauge reading in the `window` before a moment; None without one.
def before(at: datetime, readings: list[FuelReading], window: timedelta) -> float | None:
    return min((r.pct for r in readings if at - window <= r.at <= at), default=None)
