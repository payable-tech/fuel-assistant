# Route (pure): the points a planned load drives through in road order (fuel stops, pickups, deliveries), how many
# of them the truck has passed, and Google Maps links: one place, or navigation through what is still ahead.
from datetime import datetime
from urllib.parse import urlencode

from core import geo
from models import LoadPlan, Store, TrackPoint, Waypoint

MAPS = "https://www.google.com/maps"

# Datatruck writes states in full ("Massachusetts"); messages use the postal code. Anything else is kept as written.
STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY",
    "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


# The plan's fuel stops and the load's stops ahead, in the order the planned road reaches them. All are measured on
# the same saved road line, and a fuel stop never after the last stop (the plan buys fuel before the end); one at the
# same mile as a pickup or delivery comes first.
def waypoints(p: LoadPlan) -> list[Waypoint]:
    line = list(p.line)
    marks = geo.along(line)
    stops = p.plan.stops if p.plan else ()
    load = _miles_on(line, marks, [(s.lat, s.lng) for s in p.stops_ahead])
    end = load[-1] if load else marks[-1]
    fuel = [Waypoint("fuel", store_label(s.store), s.store.lat, s.store.lng, min(mile, end))
            for s, mile in zip(stops, _miles_on(line, marks, [(s.store.lat, s.store.lng) for s in stops]))]
    places = [Waypoint(s.kind, f"{s.city}, {STATE_CODES.get(s.state, s.state)}", s.lat, s.lng, mile)
              for s, mile in zip(p.stops_ahead, load)]
    return sorted(fuel + places, key=lambda w: w.miles)  # a stable sort keeps the fuel stops first on a tie


# A fuel stop as messages name it: "Love's #614 Westfield, MA", or another station by its name, "Cenex Zip Trip
# Clarkston, WA". A town the price sheet writes in capitals reads like the others ("LAUREL" -> "Laurel").
def store_label(store: Store) -> str:
    name = store.name or f"Love's #{store.store_no}"
    town = store.city.title() if store.city.isupper() else store.city
    return f"{name} {town}, {store.state}"


# How far along the road line (miles `marks`) each of `points` is, in order: each is looked for only from the one
# before on, since the road reaches them in that order and can pass the same place twice.
def _miles_on(line: list[geo.Point], marks: list[float], points: list[geo.Point]) -> list[float]:
    found, start = [], 0
    for point in points:
        start = min(range(start, len(line)), key=lambda k: geo.miles(line[k], point))
        found.append(marks[start])
    return found


# When the truck passed each waypoint it has passed so far, from its GPS track since the plan (in time order); the
# list is as long as the number passed. They count in road order: a pickup or delivery once the truck has been
# within `reached_mi` of it after the waypoints before it. A fuel stop also counts once the truck has reached a later
# one before the next pickup or delivery (it went past another way), and reaching a pickup or delivery passes every
# fuel stop before it. So a delivery near the road to the pickup isn't counted before the pickup. Each piece of track
# between two GPS points is cut into `step_mi` steps so no gap jumps a stop; a stop reached on it gets its end time.
def passed_at(points: list[Waypoint], track: list[TrackPoint], reached_mi: float, step_mi: float) -> list[datetime]:
    times: list[datetime] = []
    for a, b in zip(track[:1] + track[:-1], track):
        for spot in geo.densify([(a.lat, a.lng), (b.lat, b.lng)], step_mi):
            while len(times) < len(points):
                hit = max((j for j in _next_ones(points, len(times))
                           if geo.miles(spot, (points[j].lat, points[j].lng)) <= reached_mi), default=None)
                if hit is None:
                    break
                times += [b.at] * (hit + 1 - len(times))
    return times


# How far along the road a point is: the road's nearest point to it, looking only from `from_mile` on (the road can
# pass near the same place twice).
def mile_of(road: LoadPlan, point: geo.Point, from_mile: float) -> float:
    line = list(road.line)
    marks = geo.along(line)
    ahead = [k for k in range(len(line)) if marks[k] >= from_mile] or [len(line) - 1]
    return marks[min(ahead, key=lambda k: geo.miles(line[k], point))]


# The waypoints the truck can pass next, once `done` are behind it: up to and with the next pickup or delivery.
def _next_ones(points: list[Waypoint], done: int) -> range:
    stop = next((j for j in range(done, len(points)) if points[j].kind != "fuel"), len(points) - 1)
    return range(done, stop + 1)


# A Google Maps link to one place; on a phone it opens the Maps app there, ready to navigate.
def place_link(lat: float, lng: float) -> str:
    return f"{MAPS}/search/?" + urlencode({"api": "1", "query": f"{lat:.5f},{lng:.5f}"}, safe=",")


# A Google Maps link that starts navigation from the phone's own location (no start is given) through `points` in
# order, ending at the last. Google takes 9 stops on the way (3 in a phone's browser, without the Maps app).
def navigate_link(points: list[Waypoint]) -> str:
    *via, last = points
    query = {"api": "1", "destination": _at(last), "travelmode": "driving", "dir_action": "navigate"}
    if via:
        query["waypoints"] = "|".join(_at(w) for w in via)
    return f"{MAPS}/dir/?" + urlencode(query, safe=",")


# A waypoint as Google reads a place: "42.56503,-71.53273".
def _at(w: Waypoint) -> str:
    return f"{w.lat:.5f},{w.lng:.5f}"
