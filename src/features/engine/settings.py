# The fuel engine's settings: every number its rules and its helper jobs go by. At the end they are put in the shape
# features/engine/road_rules takes (RULES), built once here, so the engine (features/engine/job) and the dashboard always
# judge a truck by the same rules.
from base.models import FuelRules, TruckNow, UsualLevel

# Fuel recommendation (features/engine/road_rules): the hard rule, the driver's level, then money
RESERVE_PCT = 10           # never plan to arrive under this at the cautious MPG
WORSE_MPG = 0.85           # the cautious MPG: the lower of average and live, 15% worse (the user's pick, 2026-11-02)
ABOVE_USUAL_PTS = 1        # a stop reached more than this above the driver's usual level gets ignored (2-17% fuel there).
                           # Was 5 until 2026-11-16 (the user's word): stops told 5+ points above the usual level were
                           # driven past twice as often, and drivers who passed fueled 12 points lower than we told
LOOK_MI = 60               # the driver is told when the stop is this close: until then the choice stays open, and the
                           # closer it is made, the better the estimate (2026-11-02, was 150)
# A Love's stop is always a fill-up (the user's go, 2026-11-11: of 12 part fills told, none was bought as asked). Only a
# truck stop standing in for a Love's out of reach still asks for part of a tank.
PART_GAP_USD = 0.50        # a Love's ahead this much cheaper, also at the pump, is marked on the plan's regions
PART_REACH_MI = 500        # ...when at most this far past the stop
PART_MIN_GAL = 30          # at a truck stop before a Love's: buy at least this
PART_MARGIN_GAL = 25       # ...and at least this less than a fill-up, or it isn't worth asking
MAX_PASSED = 2             # after this many stops told and driven past on one tank, no more are told until the last
                           # Love's in reach or low fuel (the user's go, 2026-11-11: of 23 third-or-later messages, 1 was followed)
LAST_PCT = 3               # a Love's reached with less than this in the worst case is out of reach: the emergency starts past the last one
URGENT_PCT = 25            # with no Love's to count on, the truck stop backup starts at this gauge level
LOW_FUEL_ALARM = False     # the low-fuel message (a truck stop that isn't a Love's, or "find the nearest truck stop") is
                           # off: the truck still shows as urgent on the page, nothing is told or recorded (the user's
                           # word, 2026-11-13, "we will work on that or remove later": 1 of 20 was followed)
LOW_PENALTY_USD = 5        # dollars a stop loses per point it is reached below the driver's range
DEFAULT_MPG = 6.5          # used when Samsara MPG is missing or outside MPG_RANGE
USUAL_MIN_STOPS = 5        # fewer gauged stops: the driver's usual level isn't known
DEFAULT_USUAL_LEVELS = (22, 15, 30, 95)  # ...and these are used: the fleet's middle (usual, low, high, fill)
GAUGE_STEADY_MIN = 10      # the fuel now is the middle of the gauge readings of this many minutes: the gauge wobbles ~3 points
GAUGE_MIN_READINGS = 5     # ...but at least this many, looking back up to GAUGE_LOOKBACK_MIN: a stopped truck reports rarely
GAUGE_LOOKBACK_MIN = 60
GAUGE_FRESH_MIN = 30       # an older gauge reading can't be recommended on
FILL_RISE_PCT = 8          # a gauge rise this big means fuel was bought
FUEL_HOLD_MIN = 60         # ...and no new message for this long after it: the fill may still be going on (the user's go,
                           # 2026-11-04, after 14755 got its stop again at the pump, its gauge half way up)
NEAR_STOP_MI = 2           # a stop closer than this isn't told: the driver is already there. Low fuel is told anyway
PARKED_MIN = 15            # a truck that moved less than PARKED_MI in this many minutes is parked: its stop waits
PARKED_MI = 1              # ...till it moves (told at 08:18 while parked, 540201 passed it 3 h later; user's go 2026-11-05)
STOP_REACHED_MI = 1.0      # a load's stop is done once the truck's GPS has been this close to it
VISIT_WINDOW_H = 24        # ...counting only visits from this long before the pickup appointment (not earlier loads)
LOAD_MAX_DAYS = 10         # a load picked up longer ago than this is over, whatever Datatruck still shows
CORRIDOR_MI = 1.5          # Love's farther than this (straight line) from the road are not considered
ROUTE_STEP_MI = 0.5        # the road is cut into pieces this short to find the stores along it
LINE_STEP_MI = 0.1         # a saved road keeps points at least this far apart (same line, fewer points)
OFF_ROAD_MI = 5            # a truck this far from its road has gone another way: a new road is made
REROUTE_MIN = 60           # ...at most this often
TRUCK_STOP_OFF_MI = 2      # no Love's in reach: real truck stops this close to the road ahead count
NEARBY_MI = 10             # Love's this close to the road, though off it: counted, with the way there, when none on the
                           # road is in reach, before low fuel (540201, Ingalls IN, user's go 2026-11-05); on the map too
DETOUR_ROAD_FACTOR = 1.3   # the road to a Love's off the road is about this much longer than the straight line
# A truck with no load (features/engine/way_rules, the user's go 2026-11-18): once its fuel is down to the driver's usual level, the
# nearest Love's ahead in the direction it is going is told, like any stop (within LOOK_MI, held while parked)
HEADING_MI = 10            # its direction: from where its GPS was this many miles back to where it is now
HEADING_MAX_MIN = 30       # ...driven within this many minutes: the miles before a stop say nothing of the way after it
# Never a Love's behind the driver (the user's go, 2026-11-22: 1767 told Love's he had passed, down to 4% on I-30). The
# stops told Nov 15-22 that lay behind the truck were 151-180 degrees off its way; of 331 good ones, 3 were over 135.
BEHIND_DEG = 135           # a place more than this off the truck's way lies behind it
ROAD_AHEAD_MI = 20         # the load's road this far on from the truck shows where it goes: behind him, the road is wrong
                           # (a load in Datatruck he isn't driving makes a road that starts with a U-turn), and the
                           # nearest Love's ahead in his direction is told instead, as for a truck with no load
AHEAD_CONE_DEG = 45        # a Love's counts as ahead when it lies within this many degrees of that direction, either side.
                           # Replay on 251 no-load Love's fills made while driving (Oct 1-Nov 17): from 30 mi before the
                           # Love's he used, our nearest ahead was that one 66% of the time (15 mi / 30 degrees: 57%)
MAP_STEP_MI = 0.25         # roads go to the map with points at least this far apart
EXITS_PAUSE_SEC = 1        # between two Love's store pages read for their highway and exit: 608 stores take ~10 min, once
LINK_MAX_VIA = 3          # stops on the way in a message's link: Google's limit on mobile browsers

# Live MPG (features/engine/mpg): the engine as a fuel meter
LIVE_MPG_HOURS = 3         # how the truck runs "now": over this many hours
LIVE_MIN_MILES = 25        # ...with at least these miles driven in them
BURN_DAYS = 14             # each truck is calibrated on this many days
BURN_STRETCH_MI = 250      # ...of gauge drops over stretches this long
BURN_MIN_STRETCHES = 3     # fewer: no factor, the truck's live MPG stays unknown

# Driver habits: how each driver usually fuels, from their diesel stops and the Samsara gauge around them
HABIT_DAYS = 30            # stops of the last this many days
HABIT_MAX_FAILED = 0.2     # more than this share of trucks without gauge readings: the old copy is kept

# Tank helper: tank = gallons bought ÷ how far the Samsara fuel gauge rose (middle value over recent fill-ups),
# but never less than what the tank has been seen to hold
TANK_DAYS = 30             # fill-ups of the last this many days are used
TANK_WINDOW_MIN = 120      # gauge readings this long before/after a purchase count; purchases closer than this are one stop
TANK_MIN_RISE_PCT = 25     # smaller gauge rises are too noisy to use
TANK_MIN_FILLS = 3         # fewer usable fill-ups -> no estimate (the truck shows in `holes`)

# The rules' settings, as features/engine/road_rules takes them.
RULES = FuelRules(reserve_pct=RESERVE_PCT, worse=WORSE_MPG, above_usual=ABOVE_USUAL_PTS,
                  look_mi=LOOK_MI, part_gap=PART_GAP_USD, part_reach_mi=PART_REACH_MI,
                  part_min_gal=PART_MIN_GAL, part_margin_gal=PART_MARGIN_GAL,
                  low_penalty=LOW_PENALTY_USD, urgent_pct=URGENT_PCT, hold_min=FUEL_HOLD_MIN,
                  near_mi=NEAR_STOP_MI, max_passed=MAX_PASSED, last_pct=LAST_PCT)
DEFAULT_USUAL = UsualLevel(*DEFAULT_USUAL_LEVELS, stops=0)  # a driver whose usual level isn't known yet: the fleet's middle


# A truck as the rules see it: its gauge in gallons, where it is on its road, its MPGs, and its driver's usual level
# (the fleet's middle while his own isn't known).
def truck_now(fuel_pct: float, mile: float, tank_gal: float, forecast_mpg: float, cautious_mpg: float,
              usual: UsualLevel | None) -> TruckNow:
    return TruckNow(fuel_gal=fuel_pct / 100 * tank_gal, mile=mile, tank_gal=tank_gal, forecast_mpg=forecast_mpg,
                    cautious_mpg=cautious_mpg, usual=usual or DEFAULT_USUAL)
