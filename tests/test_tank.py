# Tests the tank helper: Central times to UTC, purchases at one stop counted once, and the estimate from the gauge.
from datetime import datetime, timedelta, timezone

from base import fuel
from base.models import FuelLine, FuelReading, TankEstimate
from features.engine import tank

WINDOW = timedelta(hours=2)


# A purchase of `gallons` at a Central clock time ("2026-10-18 07:00").
def line(fueled_at: str, gallons: float, product: str = "ULSD") -> FuelLine:
    return FuelLine(1, fueled_at, "fuel", product, gallons, 0.0, 0.0, 0.0, True, "LOVES #1", "", "TX", "TTL",
                    "340", "company", 7, "", "lease", None)


# One fill-up on an October day: a purchase at 07:00 Central (12:00 UTC) and gauge readings just before and after.
def fill(day: int, gallons: float, before: float, after: float) -> tuple[list[FuelLine], list[FuelReading]]:
    at = datetime(2026, 10, day, 12, tzinfo=timezone.utc)
    return ([line(f"2026-10-{day:02d} 07:00", gallons)],
            [FuelReading(at - timedelta(minutes=10), before), FuelReading(at + timedelta(minutes=5), after)])


# Runs the estimate over fill-ups made with `fill`.
def estimate(*fills, min_fills: int = 1) -> TankEstimate | None:
    lines = [l for f in fills for l in f[0]]
    readings = [r for f in fills for r in f[1]]
    return tank.estimate("340", lines, readings, WINDOW, min_rise_pct=25, min_fills=min_fills)


# The gauge before a fill is the lowest reading in the window before it; none without a reading there.
def test_gauge_before():
    at = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    readings = [FuelReading(at - timedelta(hours=3), 5.0), FuelReading(at - timedelta(minutes=30), 22.0),
                FuelReading(at - timedelta(minutes=5), 20.0), FuelReading(at + timedelta(minutes=5), 90.0)]
    assert tank.gauge_before(at, readings, WINDOW) == 20.0
    assert tank.gauge_before(at, readings[:1], WINDOW) is None


# Central clock time becomes UTC with daylight saving: +5 h in October, +6 h in December.
def test_central_time_to_utc():
    assert fuel.utc("2026-10-18 07:00") == datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    assert fuel.utc("2026-12-01 07:00") == datetime(2026, 12, 1, 13, tzinfo=timezone.utc)


# 120 gal raising the gauge from 20% to 90% means a 171 gal tank.
def test_tank_from_gauge_rise():
    assert estimate(fill(18, 120, 20, 90)) == TankEstimate("340", 171, 1)


# The middle fill-up size wins, so one odd fill-up doesn't move the estimate.
def test_middle_of_fill_ups():
    result = estimate(fill(16, 75, 40, 90), fill(17, 150, 0, 100), fill(18, 40, 50, 100), min_fills=3)
    assert result == TankEstimate("340", 150, 3)


# Two 100-gal tanks, gauge in one: filling only that side (80 gal, gauge 20% -> 100%) looks like a 100-gal tank.
# Even when most fill-ups are like that, the full ones (160 gal) show the tank holds at least 200 gal.
def test_one_side_fills_dont_shrink_the_tank():
    result = estimate(fill(14, 80, 20, 100), fill(15, 80, 20, 100), fill(16, 80, 20, 100),
                      fill(17, 160, 20, 100), fill(18, 160, 20, 100), min_fills=3)
    assert result == TankEstimate("340", 200, 5)


# A single gauge glitch (reading 50% low before a fill-up) doesn't raise the estimate.
def test_one_glitch_ignored():
    result = estimate(fill(15, 120, 20, 100), fill(16, 120, 20, 100), fill(17, 120, 20, 100),
                      fill(18, 120, 50, 100), min_fills=3)
    assert result == TankEstimate("340", 150, 4)


# Too few usable fill-ups give no estimate rather than a guess.
def test_too_few_fill_ups():
    assert estimate(fill(18, 120, 20, 90), min_fills=2) is None


# A small gauge rise is too noisy to use; a fill-up without gauge readings can't be used either.
def test_small_rise_or_no_readings_skipped():
    assert estimate(fill(18, 10, 80, 90)) is None
    assert tank.estimate("340", fill(18, 120, 20, 90)[0], [], WINDOW, 25, 1) is None


# Two purchases at one stop (0.3 gal, then 119.7 gal four minutes later) are one fill-up of 120 gal.
def test_purchases_at_one_stop_are_one_fill_up():
    lines = [line("2026-10-18 07:00", 0.3), line("2026-10-18 07:04", 119.7)]
    readings = fill(18, 0, 20, 90)[1]
    assert tank.estimate("340", lines, readings, WINDOW, 25, 1) == TankEstimate("340", 171, 1)


# Only diesel counts: DEF bought at the same stop doesn't change the estimate.
def test_only_diesel_counts():
    lines, readings = fill(18, 120, 20, 90)
    lines = lines + [line("2026-10-18 07:02", 10, product="DEFD")]
    assert tank.estimate("340", lines, readings, WINDOW, 25, 1) == TankEstimate("340", 171, 1)
