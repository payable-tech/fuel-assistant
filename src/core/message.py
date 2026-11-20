# What the driver is told (pure): the message's words, in plain text and in Telegram's HTML, the map links in it, the
# record kept of it, and the copy the test group sees.
import html
from datetime import datetime
from urllib.parse import urlencode

from core.recommend import arrive_pct, station
from models import NO_LOAD_ORDER, Decision, Order, Recommendation, StoreOnRoute, Truck, TruckNow


# The message the driver would get, in plain words. Every reason in it is true, and the price is the pump price he sees.
def text(truck: TruckNow, d: Decision) -> str:
    return _words(truck, d, lambda words: words, station)


# The same message in Telegram's HTML: the station's name opens it on the map, and `link` starts the road.
def html_text(truck: TruckNow, d: Decision, link: str | None) -> str:
    # The station's name as a link to it on the map.
    def named(s: StoreOnRoute) -> str:
        return f'<a href="{html.escape(place_link(s))}">{html.escape(station(s), quote=False)}</a>'

    body = _words(truck, d, lambda words: html.escape(words, quote=False), named)
    return body + (f'\n\n<a href="{html.escape(link)}">▶ Start the road</a>' if link else "")


# The message's lines. `clean` makes words safe for where they go, `named` writes a station's name. A Love's whose
# highway and exit are known (from its own page) has them after the miles: "📍 In 34 mi, I-90 (Exit 34)". With no load
# there is no road to measure on, so the miles are a rough count: "📍 About 34 mi ahead".
def _words(truck: TruckNow, d: Decision, clean, named) -> str:
    if d.kind == "urgent" and not (d.stop and arrive_pct(truck, d.stop.miles) > 0):  # never a station he'd run dry before
        return clean(f"{_low(truck)}\n\nFind the nearest truck stop now.")
    s = d.stop
    off = f", about {s.off_mi:.0f} mi off your road" if d.reason == "detour" else ""
    miles = f"About {_miles(truck, s)} mi ahead" if d.reason == "no_load" else f"In {_miles(truck, s)} mi{off}"
    where = f"📍 {miles}" + (clean(f", {s.store.way}") if s.store.way else "")
    lines = [clean(_head(truck, d)), "", named(s) + _price(s), "", where, clean(f"🛢 {_todo(d)}"),
             f"🪫 Arrive with about {_level(truck, max(arrive_pct(truck, s.miles), 0))}"]
    # no line for a hard stop: "the next Love's would put you low" was skipped with nothing happening (the user, 2026-11-10)
    why = {"tight": "Fuel is getting low.", "detour": "No Love's on your road is in reach: this one is a short detour."}.get(d.reason)
    if why:
        lines += ["", clean(why)]
    if d.then:
        lines += ["", f"Then fill up at {named(d.then)}{_price(d.then)}", f"📍 {d.then.miles - s.miles:.0f} mi further"]
    return "\n".join(lines)


# The message's first line: low fuel for an emergency, the last Love's in reach, or the fuel stop.
def _head(truck: TruckNow, d: Decision) -> str:
    if d.kind == "urgent":
        return _low(truck)
    if d.reason == "last":
        return f"⚠️ Last Love's you can reach: {d.stop.store.city}, {d.stop.store.state}"
    return f"⛽ Fuel stop: {station(d.stop)}"


# What to do at the stop: buy only part before a cheaper Love's, fill up and not skip the last Love's, or fill up.
def _todo(d: Decision) -> str:
    if d.then:
        return f"Buy about {d.gallons:.0f} gal, don't fill up"
    return "Fill up, don't skip it" if d.reason == "last" else "Fill up"


# The low-fuel warning, with the gauge now: "⚠️ Fuel is low: 8% (12 gal)".
def _low(truck: TruckNow) -> str:
    return f"⚠️ Fuel is low: {_level(truck, 100 * truck.fuel_gal / truck.tank_gal)}"


# A fuel level for the message, the gauge's percent first: "8% (12 gal)".
def _level(truck: TruckNow, pct: float) -> str:
    return f"{pct:.0f}% ({pct / 100 * truck.tank_gal:.0f} gal)"


# A station's pump price for the message; nothing when it has none (a truck stop found by Google).
def _price(s: StoreOnRoute) -> str:
    return f" - ${s.store.retail:.2f}/gal" if s.store.retail else ""


# Whole miles from the truck to a stop.
def _miles(truck: TruckNow, stop: StoreOnRoute) -> int:
    return round(max(stop.miles - truck.mile, 0))


# A Google Maps link showing one station.
def place_link(s: StoreOnRoute) -> str:
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": _at((s.store.lat, s.store.lng))}, safe=",")


# The points a message's link goes through, in road order: the fuel stops and the load's stops ahead (`load`: each with
# its mile on the road), the load's last stop last. Without a load, the fuel stops alone; nothing without a fuel stop.
def link_points(fuel: list[StoreOnRoute], load: list[tuple[float, tuple[float, float]]], max_via: int) -> list[tuple[float, float]]:
    stops = [(s.miles, (s.store.lat, s.store.lng)) for s in fuel]
    if not fuel or not load:
        return [point for _, point in sorted(stops)]
    *others, last = sorted(load)
    via = sorted(stops + others[:max(max_via - len(stops), 0)])  # a phone takes few: the fuel stops, then the nearest others
    return [point for _, point in via] + [last[1]]


# A Google Maps link that starts navigation from the phone's own location (no start is given) through the points to the
# last. Google Maps routes like a car, not a truck.
def road_link(points: list[tuple[float, float]]) -> str | None:
    if not points:
        return None
    *via, last = points
    query = {"api": "1", "destination": _at(last), "travelmode": "driving", "dir_action": "navigate"}
    if via:
        query["waypoints"] = "|".join(_at(p) for p in via)
    return "https://www.google.com/maps/dir/?" + urlencode(query, safe=",")


# A point as Google reads a place: "42.56503,-71.53273".
def _at(point: tuple[float, float]) -> str:
    return f"{point[0]:.5f},{point[1]:.5f}"


# The record of what a truck is told now: the decision, the stop with its prices and place, and the message's words.
# `order` None: the truck has no load (kept under NO_LOAD_ORDER, with no load id).
def record(truck: Truck, order: Order | None, here: TruckNow, d: Decision, now: datetime) -> Recommendation:
    stop = d.stop.store if d.stop else None
    return Recommendation(
        rec_id=None, unit=truck.unit, driver=truck.driver, order_id=order.order_id if order else NO_LOAD_ORDER,
        load_id=order.load_id if order else "", made_at=now,
        kind=d.kind, store_no=stop.store_no if stop else None, station=station(d.stop) if d.stop else None,
        miles_ahead=d.stop.miles - here.mile if d.stop else None, gauge_pct=100 * here.fuel_gal / here.tank_gal,
        arrive_pct=d.arrive_pct, worst_pct=d.worst_pct, gallons=d.gallons, then_station=station(d.then) if d.then else None,
        reason=d.reason, net=stop.net if stop else None, retail=stop.retail if stop else None,
        price_date=stop.price_date if stop else None, forecast_mpg=here.forecast_mpg, cautious_mpg=here.cautious_mpg,
        usual_pct=here.usual.usual_pct, text=text(here, d), status="open", settled_at=None,
        lat=stop.lat if stop else None, lng=stop.lng if stop else None)


# A recommendation as the test group sees it, in Telegram's HTML: whether the driver got it, which truck, then the
# message (`body`; its plain words when there is none).
def test_copy(rec: Recommendation, body: str | None) -> str:
    who = f" · {rec.driver}" if rec.driver else ""
    tag = "📨 Sent to the driver" if rec.sent_at else "🧪 Test"
    load = f"load {rec.load_id}" if rec.load_id else "no load"
    head = f"{tag} · Unit {rec.unit}{who} · {load} · gauge {rec.gauge_pct:.0f}%"
    return f"{html.escape(head, quote=False)}\n--------\n{body if body is not None else html.escape(rec.text, quote=False)}"
