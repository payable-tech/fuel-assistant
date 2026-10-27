# Tests the fuel planner: cheapest stops chosen, reserve kept, no needless stops, and no plan when none is safe.
from dataclasses import replace
from datetime import datetime, timezone

from core import planner
from core.message import first_text
from models import LoadPlan, Order, PlanRules, Stop, Store, StoreOnRoute, Truck

RULES = PlanRules(reserve_pct=10, min_buy_gal=20, stop_cost=40, step_gal=5, default_mpg=6.5, mpg_range=(4, 12))
TANK, MPG = 200, 5  # a 200-gal tank and 5 MPG keep the arithmetic easy: 100 miles = 20 gal


# A Love's `miles` along the route, selling at `net` dollars a gallon.
def at(miles: float, net: float, no: str = "") -> StoreOnRoute:
    s = Store(store_no=no or str(int(miles)), city="Town", state="TX", lat=0.0, lng=0.0, retail=net + 0.5, net=net,
              price_date="2026-10-19")
    return StoreOnRoute(store=s, miles=miles, off_mi=0.2)


# Plans with the test tank and MPG.
def plan(start_pct: float, route_mi: float, stores: list[StoreOnRoute], end_price: float = 5.5):
    return planner.plan(start_pct, TANK, MPG, route_mi, stores, end_price, RULES)


# Enough fuel for the whole trip: no stop, and the fuel left is what wasn't burned.
def test_no_stop_needed():
    result = plan(100, 400, [at(200, 5.5)])
    assert result.stops == () and result.end_gal == 120


# Of two reachable stores the cheaper one wins, and it fills up there because that fuel is worth more at the end.
def test_cheaper_store_wins():
    result = plan(50, 1000, [at(100, 6.0), at(300, 5.0)])
    assert [(s.store.store_no, s.gallons) for s in result.stops] == [("300", 160)]
    assert result.end_gal == 60 and result.fuel_cost == 800


# One stop is enough when prices are equal: the stop cost keeps the plan from stopping twice.
def test_no_needless_stops():
    result = plan(50, 800, [at(200, 5.5), at(300, 5.5)], end_price=5.5)
    assert len(result.stops) == 1


# Every stop buys at least the minimum, and the tank never goes below the reserve (20 gal of 200).
def test_minimum_buy_and_reserve():
    result = plan(30, 900, [at(100, 5.0), at(250, 5.2), at(500, 5.1), at(700, 5.3)])
    assert all(s.gallons >= 20 and s.arrive_gal >= 20 for s in result.stops) and result.end_gal >= 20


# Love's too far apart for the fuel on board: no plan rather than an unsafe one.
def test_no_safe_plan():
    assert plan(20, 1000, [at(500, 5.0)]) is None


# A truck that starts below the reserve may still use what it has to reach the first Love's.
def test_start_below_reserve():
    result = plan(5, 100, [at(20, 5.0)])
    assert [s.store.store_no for s in result.stops] == ["20"] and result.stops[0].arrive_gal == 6


# When buying more costs the same (same price here and at the end), the plan buys only what the trip needs.
def test_equal_cost_buys_less():
    result = plan(6, 100, [at(0, 5.5)], end_price=5.5)
    assert (result.stops[0].gallons, result.end_gal) == (28, 20)


# Aiming to reach the end with 40 gal: it buys for that when it can; when it can't, it still keeps the reserve.
def test_end_target_or_reserve():
    rules = replace(RULES, end_min_gal=40)
    aimed = planner.plan(6, TANK, MPG, 100, [at(0, 5.5)], 5.5, rules)
    assert aimed.end_gal == 40 and aimed.stops[0].gallons == 48   # as test_equal_cost_buys_less, plus the buffer
    fallback = planner.plan(50, TANK, MPG, 380, [], 5.5, rules)    # 100 gal, 76 burned, no Love's to reach 40
    assert fallback is not None and fallback.end_gal == 24


# A Love's 10 mi off the road isn't worth 5 cents a gallon less once its detour fuel counts (26 road miles there and
# back, ~5 gal); with the detour not counted the farther one would win.
def test_detour_counted():
    near = at(300, 5.50, "near")
    far = StoreOnRoute(store=Store("far", "Town", "TX", 0.0, 0.0, 6.0, 5.45, "2026-10-19"), miles=300, off_mi=10)
    counted = planner.plan(50, TANK, MPG, 1000, [near, far], 5.5, replace(RULES, detour_factor=2.6))
    assert [s.store.store_no for s in counted.stops] == ["near"]
    assert [s.store.store_no for s in plan(50, 1000, [near, far]).stops] == ["far"]


# On a re-plan the Love's the driver was told about stays unless another one saves more than the switch cost ($25
# here), or it can't be reached any more; a first plan (nothing told yet) just takes the cheapest.
def test_replan_keeps_told_stop():
    rules, told = replace(RULES, switch_cost=25), frozenset({"told"})

    def chosen(stores, keep=told):
        return [s.store.store_no for s in planner.plan(50, TANK, MPG, 1000, stores, 5.5, rules, keep).stops]

    assert chosen([at(300, 5.0, "told"), at(310, 4.9, "new")], frozenset()) == ["new"]
    assert chosen([at(300, 5.0, "told"), at(310, 4.9, "new")]) == ["told"]  # ~$17 cheaper: not worth a change
    assert chosen([at(300, 5.0, "told"), at(310, 4.7, "new")]) == ["new"]   # ~$50 cheaper: worth it
    assert chosen([at(300, 5.0, "new"), at(600, 5.0, "told")]) == ["new"]   # 120 gal to the told one, 100 on board


# Samsara's MPG is used when believable, otherwise the default.
def test_usable_mpg():
    assert (planner.usable_mpg(7.1, RULES), planner.usable_mpg(None, RULES), planner.usable_mpg(25, RULES)) == (7.1, 6.5, 6.5)


# The message lists each stop with its store, mile, gallons, price and a map link, and the price sheet date.
def test_plan_text():
    truck = Truck("340", "s", "V", "Unit 340", "Ali", 7.0, 50, None, 0, 0, "Dallas", None, 200, "auto", 20, -1,
                  "auto", None, True)
    stop = Stop(1, 1, 1, "delivery", 0, 0, "Atlanta", "GA")
    order = Order(1, "L-1", "in_transit", "340", None, (stop,))
    p = LoadPlan(made_at=datetime(2026, 10, 20, tzinfo=timezone.utc), truck=truck, order=order, stops_ahead=(stop,),
                 line=((0, 0), (0, 1)), route_mi=1000, candidates=(), mpg=5, price_date="2026-10-19", end_price=5.5,
                 plan=plan(50, 1000, [at(300, 5.0, "605")]))
    text = first_text(p)
    assert "Love's #605" in text and "→ buy 160 gal · $5.50" in text and "DEL Atlanta, GA" in text  # pump price
    assert "https://www.google.com/maps/search/?api=1&amp;query=0.00000,0.00000" in text and "▶ Start the road" in text
