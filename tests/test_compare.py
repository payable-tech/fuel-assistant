# Tests comparing two ways of fueling a trip: extra dollars, less the extra fuel left at the end at its value there;
# and each way's figures at the pump price beside what the company was billed.
from datetime import datetime, timezone

from core.compare import extra_at_pump, extra_cost, from_fills, from_plan
from models import Fill, FuelPlan, Outcome, PlanStop, Store


# A Love's whose pump price is $0.60 above its discounted price.
STORE = Store(store_no="1", city="Town", state="TX", lat=0, lng=0, retail=6.0, net=5.4, price_date="2026-10-21")


# A plan's figures at the pump: its gallons at the pump price; a habit's premium for buying outside Love's (cost above
# the discounted price) is added at the pump too.
def test_plan_at_the_pump():
    plan = FuelPlan(stops=(PlanStop(STORE, 100, 30, 100, 540), PlanStop(STORE, 400, 25, 50, 290)), end_gal=40, fuel_cost=830)
    figures = from_plan(plan)
    assert (figures.gallons, figures.bought, figures.pump) == (150, 830, 150 * 6.0 + 20)  # 50 gal at $0.40 more: $20


# Real fill-ups add up at the pump, billed and as the drivers paid; with no fuel left known, the end is open.
def test_fills_add_up():
    at = datetime(2026, 10, 22, tzinfo=timezone.utc)
    fills = [Fill(at, 0, 0, 100, 540, "LOVES #1", "Town", "TX", 1, pump=600, fee=1.5, driver_paid=601.5),
             Fill(at, 0, 0, 40, 240, "PILOT #9", "Town", "TX", None, pump=250, driver_paid=0)]
    figures = from_fills(fills, None)
    assert (figures.stops, figures.pump, figures.bought, figures.driver_paid, figures.end_gal) == (2, 850, 780, 601.5, None)


# At the pump, too: $60 more at the pump, 2 gal less left worth $6 each there, is $72 more.
def test_extra_at_pump():
    real, plan = Outcome(2, 120, 660, 40, pump=720), Outcome(2, 120, 600, 42, pump=660)
    assert extra_at_pump(real, plan, 6.0) == 72


# Bought $100 more but ended with 10 gal more, worth $6 each at the end: $40 more in all.
def test_extra_cost_counts_fuel_left():
    habit, plan = Outcome(3, 220, 1300, 40), Outcome(2, 200, 1200, 30)
    assert extra_cost(habit, plan, 6.0) == 40


# Filling up cheap before an expensive end isn't counted as costing more.
def test_carrying_cheap_fuel_is_not_a_cost():
    plan, habit = Outcome(1, 180, 900, 150), Outcome(1, 80, 480, 50)  # plan bought 100 gal more at $4.20
    assert extra_cost(habit, plan, 7.0) == 280  # the habit buys those 100 gal at the end for $7: $280 more
