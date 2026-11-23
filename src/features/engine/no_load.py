# Fuel stops for a truck with no load (pure): which way it is going by its GPS, and, once its fuel is down to the
# driver's usual level, the nearest Love's ahead in that direction that it can reach (the user's rule, 2026-11-18).
from datetime import datetime, timedelta

from base import geo
from base.models import Decision, FuelRules, Recommendation, Store, StoreOnRoute, TrackPoint, TruckNow
from features.engine.recommend import arrive_pct, fill_up, in_reach, worst_pct


# The direction the truck is going (compass degrees): from where its GPS `track` was `back_mi` before its `position`
# to it. None when it hasn't driven that far since `since` (just left a stop: the road before it may run the other
# way), or at all.
def heading(track: list[TrackPoint], position: geo.Point, back_mi: float,
            since: datetime | None = None) -> float | None:
    for p in reversed(track):  # newest first: the latest stretch of road says where it goes now
        if since is not None and p.at < since:
            return None
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


# When the truck last set off after a stop (its GPS within `stop_mi` for `stop_min` or more: a pickup, a delivery, a
# break), by its `track`; None when the track shows no such stop. The way it came says nothing of the way after it.
def set_off(track: list[TrackPoint], stop_mi: float, stop_min: timedelta) -> datetime | None:
    if not track:
        return None
    anchor = track[-1]
    for p in reversed(track[:-1]):  # back in time: `anchor` is the newest point of the stretch it stayed near
        if geo.miles((p.lat, p.lng), (anchor.lat, anchor.lng)) > stop_mi:
            anchor = p
        elif anchor.at - p.at >= stop_min:
            return anchor.at
    return None


# What to do for a truck with no load: nothing while its fuel is above the driver's usual level ("no load"); at it,
# the nearest Love's ahead (`ahead`, nearest first) if it can reach it, told once within `look_mi` ("stop", "watch"
# before). `toward` None: parked or hardly moved, so its way isn't known: told once it moves. The truck's mile is 0.
# The same rule serves a truck off its load's road: `label` names its states and `reason` its message ("heading").
def decide(truck: TruckNow, toward: float | None, ahead: list[StoreOnRoute], rules: FuelRules,
           label: str = "no load", reason: str = "no_load") -> Decision:
    if 100 * truck.fuel_gal / truck.tank_gal > truck.usual.usual_pct:
        return Decision(label)
    if toward is None:
        return Decision(f"{label}, parked")
    if not ahead or not in_reach(truck, ahead[0], rules):  # the nearest out of reach: every one further is too
        return Decision(f"{label}, no Love's ahead")
    stop = ahead[0]
    return Decision("stop" if stop.miles <= rules.look_mi else "watch", stop=stop, arrive_pct=arrive_pct(truck, stop.miles),
                    worst_pct=worst_pct(truck, stop.miles), gallons=fill_up(truck, stop), reason=reason)


# What becomes of a stop told to a truck with no load, at a new look: None while it stands; "passed" once it is behind
# the truck (more than `near_mi` away, more than a right angle off its way); "replaced" once out of reach. While the
# truck's way isn't known (`toward` None: parked), it stands.
def told_now(told: Recommendation, position: geo.Point, toward: float | None, truck: TruckNow, rules: FuelRules,
             road_factor: float) -> str | None:
    place = (told.lat, told.lng)
    if geo.behind(position, toward, place, rules.near_mi, 90):
        return "passed"
    return None if worst_pct(truck, geo.miles(position, place) * road_factor) >= rules.last_pct else "replaced"
