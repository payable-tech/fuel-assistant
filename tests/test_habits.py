# Tests driver habits: stops lined up with the gauge, and each driver's habit.
from datetime import datetime, timedelta, timezone

from base.models import FuelLine, FuelReading, FuelStop
from features.engine import habits

WINDOW = timedelta(hours=2)


# A diesel purchase by driver 7 in truck 340 at a Central clock time.
def bought(central: str, gallons: float, station: str = "LOVES #1", billed_per_gal: float = 5.5, driver=7) -> FuelLine:
    return FuelLine(1, central, "fuel", "ULSD", gallons, gallons * 6, gallons * billed_per_gal, 0.0, True, station, "Town",
                    "TX", "TTL", "340", "company", driver, "Ali Karimov", "lease", None)


# A stop of driver 7 with the gauge before and after (None: no readings).
def stop(gallons: float, before, after, loves: bool = True, billed_per_gal: float = 5.5, day: int = 1) -> FuelStop:
    return FuelStop(7, "Ali", "340", datetime(2026, 10, day, tzinfo=timezone.utc), gallons, gallons * billed_per_gal,
                    loves, "TX", before, after)


# Two purchases at one stop are one stop; it gets the gauge just before and after; a purchase with no driver is left out.
def test_fuel_stops_with_gauge():
    at = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)  # 07:00 Central
    readings = {"340": [FuelReading(at - timedelta(minutes=10), 20), FuelReading(at + timedelta(minutes=10), 95)]}
    lines = [bought("2026-10-18 07:00", 100), bought("2026-10-18 07:05", 50), bought("2026-10-18 09:00", 80, driver=None)]
    stops = habits.fuel_stops(lines, readings, WINDOW)
    assert [(s.gallons, s.gauge_before, s.gauge_after, s.loves) for s in stops] == [(150, 20, 95, True)]


# A habit is the middle of the driver's stops, with shares of low stops, top-offs, Love's gallons, and the premium.
def test_habit_figures():
    stops = [stop(150, 8, 95, day=1), stop(140, 20, 98, day=2), stop(30, 60, 70, day=3),
             stop(100, 25, 90, loves=False, billed_per_gal=6.0, day=4)]
    h = habits.habits(stops, low_pct=10, top_off_gal=50)[0]
    assert (h.stops, h.stop_at_pct, h.fill_to_pct, h.ran_low_share, h.top_off_share) == (4, 22.5, 92.5, 0.25, 0.25)
    assert round(h.loves_share, 3) == round(320 / 420, 3) and round(h.outside_premium, 2) == 0.5


# A driver without gauge readings has no levels.
def test_habit_without_gauge():
    h = habits.habits([stop(100, None, None)], 10, 50)[0]
    assert h.stop_at_pct is None


# A driver's usual level: the middle gauge when stopping and after filling, the middle half around it; not enough stops, none.
def test_usual_level():
    stops = [stop(100, level, 95) for level in (10, 12, 14, 16, 18, 40)]
    u = habits.usual_level(stops, 5)
    assert (u.usual_pct, u.fill_pct, u.stops) == (15, 95, 6) and u.low_pct < 15 < u.high_pct
    assert habits.usual_level(stops[:4], 5) is None
    assert habits.usual_level([stop(100, None, None)] * 9, 5) is None
