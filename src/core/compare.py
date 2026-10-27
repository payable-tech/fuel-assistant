# Comparing ways of fueling one trip (pure): the plan, the driver's habit and what really happened, in the same
# figures, and how much more one cost than another.
from models import Fill, FuelPlan, Outcome


# A plan (or a simulated habit) in comparable figures. At the pump, each stop's gallons cost the store's pump price
# plus whatever its cost carries above the discounted price (a habit's premium for buying outside Love's).
def from_plan(plan: FuelPlan) -> Outcome:
    pump = sum(s.gallons * s.store.retail + (s.cost - s.gallons * s.store.net) for s in plan.stops)
    return Outcome(stops=len(plan.stops), gallons=sum(s.gallons for s in plan.stops), bought=plan.fuel_cost,
                   end_gal=plan.end_gal, pump=pump)


# What really happened in comparable figures: the real fill-ups and the fuel left at the end (None while the trip
# isn't over).
def from_fills(fills: list[Fill], end_gal: float | None) -> Outcome:
    return Outcome(stops=len(fills), gallons=sum(f.gallons for f in fills), bought=sum(f.billed for f in fills),
                   end_gal=end_gal, pump=sum(f.pump for f in fills), driver_paid=sum(f.driver_paid for f in fills))


# How much more `a` cost than `b` for the same trip from the same start: the extra dollars bought, less the extra
# fuel left at the end, worth `end_price` a gallon because it won't need buying there. Negative: `a` cost less.
def extra_cost(a: Outcome, b: Outcome, end_price: float) -> float:
    return (a.bought - b.bought) - (a.end_gal - b.end_gal) * end_price


# The same at the pump price: what the driver sees, with fuel left at the end worth the pump price near the end.
def extra_at_pump(a: Outcome, b: Outcome, end_pump: float) -> float:
    return (a.pump - b.pump) - (a.end_gal - b.end_gal) * end_pump
