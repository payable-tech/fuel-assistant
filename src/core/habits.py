# Driver habits (pure): every driver's diesel stops with the truck's gauge around them, how each driver usually
# fuels, and that habit simulated on a planned road ("what this driver would do on this load").
from collections import defaultdict
from datetime import timedelta
from statistics import median

from core import tank
from core.fuel import LOVES, chain, purchase_stops, utc
from models import DriverHabit, FuelLine, FuelPlan, FuelReading, FuelStop, PlanStop, StoreOnRoute


# Every driver's diesel stops, each with the gauge of the truck they drove around it (`readings` by unit).
# Purchases Datatruck doesn't tie to a driver are left out: a habit belongs to a driver.
def fuel_stops(lines: list[FuelLine], readings: dict[str, list[FuelReading]], window: timedelta) -> list[FuelStop]:
    by_driver = defaultdict(list)
    for line in lines:
        if line.driver_id is not None:
            by_driver[line.driver_id].append(line)
    return [_stop(stop, readings.get(stop[0].unit, []), window)
            for mine in by_driver.values() for stop in purchase_stops(mine, window)]


# One stop's purchases as a FuelStop, with the gauge just before and just after.
def _stop(lines: list[FuelLine], readings: list[FuelReading], window: timedelta) -> FuelStop:
    first, last = utc(lines[0].fueled_at), utc(lines[-1].fueled_at)
    gauge = tank.gauge_around(first, last, readings, window)
    return FuelStop(driver_id=lines[0].driver_id, driver_name=lines[0].driver_name or "", unit=lines[0].unit, at=last,
                    gallons=sum(l.gallons for l in lines), billed=sum(l.billed for l in lines),
                    loves=chain(lines[0].location) == LOVES, state=lines[0].state,
                    gauge_before=gauge[0] if gauge else None, gauge_after=gauge[1] if gauge else None)


# How each driver usually fuels, most gallons first. A stop starting below `low_pct` "ran low"; one buying less
# than `top_off_gal` is a top-off.
def habits(stops: list[FuelStop], low_pct: float, top_off_gal: float) -> list[DriverHabit]:
    by_driver = defaultdict(list)
    for s in stops:
        by_driver[s.driver_id].append(s)
    return sorted((_habit(mine, low_pct, top_off_gal) for mine in by_driver.values()), key=lambda h: -h.gallons)


# One driver's habit from their stops: middle levels and gallons (one odd stop doesn't move them), and shares.
def _habit(stops: list[FuelStop], low_pct: float, top_off_gal: float) -> DriverHabit:
    latest = max(stops, key=lambda s: s.at)
    gauged = [s for s in stops if s.gauge_before is not None]
    gallons = sum(s.gallons for s in stops)
    at_loves, outside = [s for s in stops if s.loves], [s for s in stops if not s.loves]
    return DriverHabit(
        driver_id=latest.driver_id, name=latest.driver_name, unit=latest.unit, stops=len(stops), gallons=gallons,
        gauged=len(gauged),
        stop_at_pct=median(s.gauge_before for s in gauged) if gauged else None,
        ran_low_share=sum(s.gauge_before < low_pct for s in gauged) / len(gauged) if gauged else None,
        fill_to_pct=median(s.gauge_after for s in gauged) if gauged else None,
        gal_per_stop=median(s.gallons for s in stops),
        top_off_share=sum(s.gallons < top_off_gal for s in stops) / len(stops),
        loves_share=sum(s.gallons for s in at_loves) / gallons,
        paid_per_gal=_per_gal(stops),
        outside_premium=_per_gal(outside) - _per_gal(at_loves) if at_loves and outside else None)


# Dollars billed per gallon over some stops.
def _per_gal(stops: list[FuelStop]) -> float:
    return sum(s.billed for s in stops) / sum(s.gallons for s in stops)


# What the driver would do on a planned road, by habit: when the gauge gets to their usual stop level they fuel at
# the Love's nearest that point (one they can still reach) up to their usual fill level. The share of gallons they
# usually buy outside Love's costs their usual premium. None without gauge readings to know their levels, or when
# their habit runs out of Love's within reach.
def simulate(habit: DriverHabit, start_pct: float, tank_gal: float, mpg: float, route_mi: float,
             stores: list[StoreOnRoute]) -> FuelPlan | None:
    if habit.stop_at_pct is None:
        return None
    stop_gal, fill_gal = habit.stop_at_pct / 100 * tank_gal, habit.fill_to_pct / 100 * tank_gal
    extra = (1 - habit.loves_share) * (habit.outside_premium or 0)  # what their outside buying adds per gallon
    fuel, mile, stops = min(start_pct, 100) / 100 * tank_gal, 0.0, []
    while (want := mile + (fuel - stop_gal) * mpg) < route_mi:  # the gauge gets to their stop level before the end
        reachable = [s for s in stores if mile < s.miles <= mile + fuel * mpg]
        if not reachable:
            return None
        pick = min(reachable, key=lambda s: abs(s.miles - want))
        arrive = fuel - (pick.miles - mile) / mpg
        gallons = max(fill_gal - arrive, 0.0)
        if gallons:
            stops.append(PlanStop(store=pick.store, miles=pick.miles, arrive_gal=arrive, gallons=gallons,
                                  cost=gallons * (pick.store.net + extra)))
        fuel, mile = arrive + gallons, pick.miles
    return FuelPlan(stops=tuple(stops), end_gal=fuel - (route_mi - mile) / mpg, fuel_cost=sum(s.cost for s in stops))
