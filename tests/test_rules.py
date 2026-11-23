# Tests the recommendation's settings as the rules take them, and a truck as the rules see it.
from features.engine import settings


# The rules carry the settings' numbers, the same ones for the engine and the dashboard.
def test_rules_from_settings():
    assert (settings.RULES.reserve_pct, settings.RULES.worse, settings.RULES.last_pct) == (settings.RESERVE_PCT, settings.WORSE_MPG, settings.LAST_PCT)
    assert (settings.RULES.hold_min, settings.RULES.near_mi, settings.RULES.max_passed) == (settings.FUEL_HOLD_MIN, settings.NEAR_STOP_MI, settings.MAX_PASSED)


# A truck's gauge becomes gallons in its tank, and a driver whose usual level isn't known gets the fleet's.
def test_truck_now():
    here = settings.truck_now(20.0, 12.0, 150.0, 7.0, 5.6, None)
    assert (here.fuel_gal, here.mile, here.tank_gal, here.forecast_mpg, here.cautious_mpg) == (30.0, 12.0, 150.0, 7.0, 5.6)
    assert here.usual == settings.DEFAULT_USUAL
