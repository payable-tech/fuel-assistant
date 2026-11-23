# Tank helper (pure): a truck's tank size from its diesel purchases and the Samsara fuel gauge around them.
# 120 gal raising the gauge from 20% to 90% means the tank holds 120 ÷ 0.70 ≈ 171 gal.
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from base.fuel import purchase_stops, utc
from base.models import FuelLine, FuelReading, TankEstimate
from features.engine import gauge


# The diesel bought at one stop, from its first to its last purchase (UTC).
@dataclass(frozen=True)
class FillUp:
    first: datetime
    last: datetime
    gallons: float


# What one fill-up says about the tank: its size (gallons ÷ gauge rise) and the least it must hold (gallons ÷ the
# room that was left, i.e. what was poured plus what was already in it).
@dataclass(frozen=True)
class Measure:
    size: float
    holds_at_least: float


# Estimates one truck's tank: the middle fill-up size, but never less than what the tank has been seen to hold. None
# when fewer than `min_fills` fill-ups are clear enough: a guess is worse than a visible gap.
def estimate(unit: str, lines: list[FuelLine], readings: list[FuelReading], window: timedelta,
             min_rise_pct: float, min_fills: int) -> TankEstimate | None:
    measures = [m for fill in fill_ups(lines, window) if (m := measure(fill, readings, window, min_rise_pct))]
    if len(measures) < min_fills:
        return None
    # With two tanks and the gauge in one, filling only that side reads full with half the fuel in: such a fill-up looks
    # like half the tank. The "holds at least" floor keeps those from pulling the estimate down.
    floor = sorted(m.holds_at_least for m in measures)[-2:][0]  # 2nd biggest: the biggest may be a gauge glitch
    return TankEstimate(unit=unit, tank_gal=round(max(median(m.size for m in measures), floor)), fills=len(measures))


# Diesel purchases as fill-ups, one per stop. Purchases less than `window` apart are measured together, since
# their gauge windows would overlap.
def fill_ups(lines: list[FuelLine], window: timedelta) -> list[FillUp]:
    return [FillUp(first=utc(stop[0].fueled_at), last=utc(stop[-1].fueled_at), gallons=sum(l.gallons for l in stop))
            for stop in purchase_stops(lines, window)]


# Measures one fill-up from the gauge around it. None when readings are missing or the gauge rose too little to trust.
def measure(fill: FillUp, readings: list[FuelReading], window: timedelta, min_rise_pct: float) -> Measure | None:
    levels = gauge.around(fill.first, fill.last, readings, window)
    if levels is None or levels[1] - levels[0] < min_rise_pct:
        return None
    low, high = levels
    return Measure(size=fill.gallons / ((high - low) / 100), holds_at_least=fill.gallons / ((100 - low) / 100))
