# The fuel recommendation's settings from config.py, in the shape features/engine/recommend takes. Built once here, so the engine
# (features/engine/job) and the dashboard always judge a truck by the same rules.
from base import config
from base.models import FuelRules, TruckNow, UsualLevel

RULES = FuelRules(reserve_pct=config.RESERVE_PCT, worse=config.WORSE_MPG, above_usual=config.ABOVE_USUAL_PTS,
                  look_mi=config.LOOK_MI, part_gap=config.PART_GAP_USD, part_reach_mi=config.PART_REACH_MI,
                  part_min_gal=config.PART_MIN_GAL, part_margin_gal=config.PART_MARGIN_GAL,
                  low_penalty=config.LOW_PENALTY_USD, urgent_pct=config.URGENT_PCT, hold_min=config.FUEL_HOLD_MIN,
                  near_mi=config.NEAR_STOP_MI, max_passed=config.MAX_PASSED, last_pct=config.LAST_PCT)
DEFAULT_USUAL = UsualLevel(*config.DEFAULT_USUAL, stops=0)  # a driver whose usual level isn't known yet: the fleet's middle


# A truck as the rules see it: its gauge in gallons, where it is on its road, its MPGs, and its driver's usual level
# (the fleet's middle while his own isn't known).
def truck_now(fuel_pct: float, mile: float, tank_gal: float, forecast_mpg: float, cautious_mpg: float,
              usual: UsualLevel | None) -> TruckNow:
    return TruckNow(fuel_gal=fuel_pct / 100 * tank_gal, mile=mile, tank_gal=tank_gal, forecast_mpg=forecast_mpg,
                    cautious_mpg=cautious_mpg, usual=usual or DEFAULT_USUAL)
