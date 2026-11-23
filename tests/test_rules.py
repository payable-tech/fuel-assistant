# Tests the recommendation's settings as the rules take them, and a truck as the rules see it.
from base import config
from features.engine import settings as rules


# The rules carry config's numbers, the same ones for the engine and the dashboard.
def test_rules_from_config():
    assert (rules.RULES.reserve_pct, rules.RULES.worse, rules.RULES.last_pct) == (config.RESERVE_PCT, config.WORSE_MPG, config.LAST_PCT)
    assert (rules.RULES.hold_min, rules.RULES.near_mi, rules.RULES.max_passed) == (config.FUEL_HOLD_MIN, config.NEAR_STOP_MI, config.MAX_PASSED)


# A truck's gauge becomes gallons in its tank, and a driver whose usual level isn't known gets the fleet's.
def test_truck_now():
    here = rules.truck_now(20.0, 12.0, 150.0, 7.0, 5.6, None)
    assert (here.fuel_gal, here.mile, here.tank_gal, here.forecast_mpg, here.cautious_mpg) == (30.0, 12.0, 150.0, 7.0, 5.6)
    assert here.usual == rules.DEFAULT_USUAL
