# Fuel stops for a truck with no load (pure): which way it is going by its GPS, and, once its fuel is down to the
# driver's usual level, the nearest Love's ahead in that direction that it can reach (the user's rule, 2026-11-18).
from core import geo
from core.recommend import arrive_pct, fill_up, in_reach, worst_pct
from models import Decision, FuelRules, Recommendation, Store, StoreOnRoute, TrackPoint, TruckNow


# The direction the truck is going (compass degrees): from where its GPS `track` was `back_mi` before its `position`
# to it. None when the track doesn't reach that far back (it has hardly moved).
def heading(track: list[TrackPoint], position: geo.Point, back_mi: float) -> float | None:
    for p in reversed(track):  # newest first: the latest stretch of road says where it goes now
        if geo.miles((p.lat, p.lng), position) >= back_mi:
            return geo.bearing((p.lat, p.lng), position)
    return None


# The Love's ahead of a truck going `toward` (compass degrees): within `cone_deg` of its way, either side, as stops with
# their miles counting the way there (straight-line miles times `road_factor`: there is no road to measure on), nearest
# first.
def loves_ahead(position: geo.Point, toward: float, stores: list[Store], cone_deg: float,
                road_factor: float) -> list[StoreOnRoute]:
    found = [StoreOnRoute(s, miles=geo.miles(position, (s.lat, s.lng)) * road_factor, off_mi=0.0) for s in stores
             if geo.turn(geo.bearing(position, (s.lat, s.lng)), toward) <= cone_deg]
    return sorted(found, key=lambda s: s.miles)


# What to do for a truck with no load: nothing while its fuel is above the driver's usual level ("no load"); at it,
# the nearest Love's ahead (`ahead`, nearest first) if it can reach it, told once within `look_mi` ("stop", "watch"
# before). `toward` None: parked or hardly moved, so its way isn't known: told once it moves. The truck's mile is 0.
def decide(truck: TruckNow, toward: float | None, ahead: list[StoreOnRoute], rules: FuelRules) -> Decision:
    if 100 * truck.fuel_gal / truck.tank_gal > truck.usual.usual_pct:
        return Decision("no load")
    if toward is None:
        return Decision("no load, parked")
    if not ahead or not in_reach(truck, ahead[0], rules):  # the nearest out of reach: every one further is too
        return Decision("no load, no Love's ahead")
    stop = ahead[0]
    return Decision("stop" if stop.miles <= rules.look_mi else "watch", stop=stop, arrive_pct=arrive_pct(truck, stop.miles),
                    worst_pct=worst_pct(truck, stop.miles), gallons=fill_up(truck, stop), reason="no_load")


# What becomes of a stop told to a truck with no load, at a new look: None while it stands; "passed" once it is behind
# the truck (more than `near_mi` away, more than a right angle off its way); "replaced" once out of reach. While the
# truck's way isn't known (`toward` None: parked), it stands.
def told_now(told: Recommendation, position: geo.Point, toward: float | None, truck: TruckNow, rules: FuelRules,
             road_factor: float) -> str | None:
    place = (told.lat, told.lng)
    away = geo.miles(position, place)
    if toward is not None and away > rules.near_mi and geo.turn(geo.bearing(position, place), toward) > 90:
        return "passed"
    return None if worst_pct(truck, away * road_factor) >= rules.last_pct else "replaced"
