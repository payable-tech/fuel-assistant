# Tests driver habits: stops lined up with the gauge, each driver's habit, and that habit simulated on a road.
from datetime import datetime, timedelta, timezone

from core import habits
from models import DriverHabit, FuelLine, FuelReading, FuelStop, Store, StoreOnRoute

WINDOW = timedelta(hours=2)
TANK, MPG = 200, 5  # 100 miles = 20 gal = 10% of the tank


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


# A driver without gauge readings has no levels, and their habit can't be simulated.
def test_habit_without_gauge():
    h = habits.habits([stop(100, None, None)], 10, 50)[0]
    assert h.stop_at_pct is None and habits.simulate(h, 50, TANK, MPG, 1000, []) is None


# A habit for the simulations: stops at 20%, fills to 90%, all at Love's.
def habit(stop_at=20, fill_to=90, loves_share=1.0, premium=None) -> DriverHabit:
    return DriverHabit(7, "Ali", "340", 10, 1000, 10, stop_at, 0, fill_to, 100, 0, loves_share, 5.5, premium)


# A Love's `miles` along the road at `net` a gallon.
def at(miles: float, net: float = 5.0) -> StoreOnRoute:
    return StoreOnRoute(Store(str(int(miles)), "Town", "TX", 0, 0, net + 0.5, net, "2026-10-20"), miles, 0.2)


# From 50% the gauge reaches 20% after 300 miles: the driver fuels at the Love's nearest that point and fills to 90%.
def test_simulate_stops_near_their_level():
    result = habits.simulate(habit(), 50, TANK, MPG, 600, [at(100), at(280), at(450)])
    assert [(s.store.store_no, s.arrive_gal, s.gallons) for s in result.stops] == [("280", 44, 136)]
    assert result.end_gal == 180 - 320 / MPG


# Gallons they usually buy outside Love's cost their usual premium on top of the Love's price.
def test_simulate_outside_premium():
    result = habits.simulate(habit(loves_share=0.5, premium=0.8), 50, TANK, MPG, 600, [at(280)])
    assert result.stops[0].cost == result.stops[0].gallons * (5.0 + 0.4)


# No Love's within reach when the habit needs one: no simulation.
def test_simulate_no_store_in_reach():
    assert habits.simulate(habit(), 20, TANK, MPG, 1000, [at(900)]) is None
