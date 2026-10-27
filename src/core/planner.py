# Fuel planner (pure): where along a load's route to buy fuel, and how much, for the lowest total cost.
# At each Love's on the route the truck either drives past or fills up to some level. For every (stop, level) the
# planner keeps only the cheapest way to get there, so trying every combination stays fast.
from math import inf

from models import FuelPlan, PlanRules, PlanStop, StoreOnRoute


# The truck's MPG when Samsara's is believable, else the default.
def usable_mpg(mpg: float | None, rules: PlanRules) -> float:
    low, high = rules.mpg_range
    return mpg if mpg is not None and low <= mpg <= high else rules.default_mpg


# Plans one trip of `route_mi` miles with the Love's `stores` along it (in route order). Fuel left at the end is
# worth `end_price` a gallon (it won't need buying there). A store off the route costs the fuel to drive there and
# back (`rules.detour_factor`). The plan reaches the end with `rules.end_min_gal` when one can, else with the reserve;
# None when no plan keeps the reserve. On a re-plan, `keep` holds the store numbers the driver was already told to
# stop at: any other Love's counts `rules.switch_cost` more, so near-equal choices don't swap back and forth.
def plan(start_pct: float, tank_gal: float, mpg: float, route_mi: float, stores: list[StoreOnRoute],
         end_price: float, rules: PlanRules, keep: frozenset[str] = frozenset()) -> FuelPlan | None:
    start_gal = min(start_pct, 100) / 100 * tank_gal
    reserve = tank_gal * rules.reserve_pct / 100
    levels = _levels(tank_gal, reserve, rules.step_gal)
    # state (index of the last stop, level filled to there; -1 = the start) -> (cost so far, previous state, gallons)
    best: dict[tuple[int, float], tuple[float, tuple | None, float]] = {(-1, start_gal): (0.0, None, 0.0)}
    for j, s in enumerate(stores):
        stop_cost = rules.stop_cost + (rules.switch_cost if keep and s.store.store_no not in keep else 0.0)
        reached = {}
        for (i, fuel), (cost, _, _) in best.items():
            arrive = _back_on_road(stores, i, fuel, mpg, rules) - (s.miles - _mile(stores, i)) / mpg - _way(s, mpg, rules)
            if arrive < _floor(i, start_gal, reserve):
                continue
            for level in levels:  # from a full tank down
                gallons = level - arrive
                if gallons < rules.min_buy_gal:
                    break  # lower levels would buy even less
                total = cost + gallons * s.store.net + stop_cost
                if total < reached.get((j, level), (inf,))[0]:
                    reached[(j, level)] = (total, (i, fuel), gallons)
        best |= reached
    for end_floor in (max(reserve, rules.end_min_gal), reserve):  # the end target first, else just the reserve
        found = _cheapest_finish(best, stores, end_floor, route_mi, mpg, end_price, rules)
        if found:
            return found
    return None


# Picks the cheapest state that reaches the end with at least `end_floor` left, and walks back through it to list
# the stops. Between plans that cost the same to the cent, the one ending with less fuel (buying less) wins.
def _cheapest_finish(best: dict, stores: list[StoreOnRoute], end_floor: float, route_mi: float, mpg: float,
                     end_price: float, rules: PlanRules) -> FuelPlan | None:
    finishes = [(round(cost - end_gal * end_price, 2), end_gal, state)
                for state, (cost, _, _) in best.items()
                if (end_gal := _back_on_road(stores, state[0], state[1], mpg, rules)
                    - (route_mi - _mile(stores, state[0])) / mpg) >= end_floor]
    if not finishes:
        return None
    _, end_gal, state = min(finishes)
    stops = []
    while state[0] >= 0:
        _, previous, gallons = best[state]
        s = stores[state[0]]
        stops.append(PlanStop(store=s.store, miles=s.miles, arrive_gal=state[1] - gallons, gallons=gallons,
                              cost=gallons * s.store.net))
        state = previous
    stops.reverse()
    return FuelPlan(stops=tuple(stops), end_gal=end_gal, fuel_cost=sum(s.cost for s in stops))


# Fill-up levels, from a full tank down in steps, all above the reserve. Starting from full keeps "fill it up" a choice.
def _levels(tank_gal: float, reserve: float, step_gal: float) -> list[float]:
    count = int((tank_gal - reserve) // step_gal) + 1
    return [level for k in range(count) if (level := tank_gal - k * step_gal) > reserve]


# Miles from the start to stop `i` (-1 = the start itself).
def _mile(stores: list[StoreOnRoute], i: int) -> float:
    return stores[i].miles if i >= 0 else 0.0


# Gallons to drive from the route to store `s`, or back (one way of its detour).
def _way(s: StoreOnRoute, mpg: float, rules: PlanRules) -> float:
    return s.off_mi * rules.detour_factor / 2 / mpg


# The fuel when back on the route after filling to `fuel` at stop `i` (at the start: the fuel itself).
def _back_on_road(stores: list[StoreOnRoute], i: int, fuel: float, mpg: float, rules: PlanRules) -> float:
    return fuel - _way(stores[i], mpg, rules) if i >= 0 else fuel


# The least fuel the truck may arrive with at a Love's. A truck already below the reserve at the start may use
# what it has left to reach its first stop; everyone else keeps the reserve.
def _floor(i: int, start_gal: float, reserve: float) -> float:
    return reserve if i >= 0 or start_gal >= reserve else 0.0
