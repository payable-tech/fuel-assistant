# What came of the messages (pure): the fill-up after each one, whether it was at the stop told and what that saved,
# the fill-ups no message asked for, and the Live tab's sum of the messages sent to drivers.
from collections import defaultdict
from datetime import datetime, timedelta

from base import geo
from base.fuel import CENTRAL, is_diesel, is_loves, purchase_stops, store_no, summarize, utc
from base.models import FuelLine, FuelStop, Recommendation, TrackPoint


# One fill-up (the purchases of one stop) in figures: when, where (and whether at a Love's), gallons, and the pump price,
# what the company paid and the discount between them, per gallon and in all.
def purchase(stop: list[FuelLine]) -> dict:
    gallons = sum(l.gallons for l in stop)
    paid_total = sum(l.billed for l in stop)
    pump_total = sum(l.pump_total for l in stop)
    return {"at": utc(stop[-1].fueled_at).isoformat(), "where": f"{stop[0].location} {stop[0].city}, {stop[0].state}",
            "loves": is_loves(stop[0]),
            "gallons": gallons, "paid": paid_total / gallons, "paid_total": paid_total, "pump": pump_total / gallons,
            "pump_total": pump_total, "discount": (pump_total - paid_total) / gallons, "discount_total": pump_total - paid_total}


# What really happened after a recommendation: the truck's first diesel stop after it, within `within`, and what going
# where we said would have saved (0 when it did). None until there is such a stop.
def outcome(rec: Recommendation, lines: list[FuelLine], window: timedelta, within: timedelta) -> dict | None:
    diesel = [l for l in lines if l.unit == rec.unit and is_diesel(l)]
    for stop in purchase_stops(diesel, window):
        if rec.made_at <= utc(stop[-1].fueled_at) <= rec.made_at + within:
            bought = purchase(stop)
            there = rec.store_no is not None and store_no(stop[0].location) == rec.store_no
            saved = 0.0 if there or rec.net is None else bought["gallons"] * (bought["paid"] - rec.net)
            return bought | {"there": there, "saved": saved}
    return None


# What came of each message, by its id. A purchase belongs to the newest message before it, so one fill-up isn't counted
# for every stop told on the way to it. A message sent again by mistake ("repeat") has none: the first one keeps it.
def outcomes(recs: list[Recommendation], lines: list[FuelLine], window: timedelta, within: timedelta) -> dict[int, dict]:
    found = {}
    ordered = sorted((r for r in recs if r.status != "repeat"), key=lambda r: r.made_at)
    for rec in ordered:
        later = next((r for r in ordered if r.unit == rec.unit and r.made_at > rec.made_at), None)
        came = outcome(rec, lines, window, min(within, later.made_at - rec.made_at) if later else within)
        if came:
            found[rec.rec_id] = came
    return found


# A truck's fill-ups that no message asked for (none was standing, or the driver had already fueled for it), oldest
# first: the driver's own choices. `came`: what came of the truck's messages (`outcomes`).
def own_fills(unit: str, came: dict[int, dict], lines: list[FuelLine], window: timedelta) -> list[dict]:
    asked = {o["at"] for o in came.values()}
    diesel = [l for l in lines if l.unit == unit and is_diesel(l)]
    return [p for p in map(purchase, purchase_stops(diesel, window)) if p["at"] not in asked]


# What became of a message sent: fueled at our stop, at another Love's or outside Love's (its purchase is in
# Datatruck), drove past, fueled by the gauge with the purchase not in Datatruck yet, still on the way, or called off by
# us (road remade, load ended).
def became(rec: Recommendation, bought: dict | None) -> str:
    if bought:
        return "there" if bought["there"] else "loves" if bought.get("loves") else "outside"
    return {"passed": "passed", "fueled": "waiting", "open": "open"}.get(rec.status, "off")


# A fill-up with the gauge before and after it, from the driver's `stops` (the one within `window` of it): those are
# refreshed daily, so the newest fills get it a day later at most (None until then).
def with_gauge(bought: dict, stops: list[FuelStop], window: timedelta) -> dict:
    at = datetime.fromisoformat(bought["at"])
    stop = next((s for s in stops if abs(s.at - at) <= window), None)
    return bought | {"gauge_before": stop.gauge_before if stop else None, "gauge_after": stop.gauge_after if stop else None}


# The fill-ups between two moments, placed where the truck's GPS `track` was when it paid; `told` marks those at a stop
# we told (`came`: what became of each message). None without a track to place them on (an empty list).
def fills(lines: list[FuelLine], track: list[TrackPoint], start: datetime, end: datetime, came: dict[int, dict],
          window: timedelta) -> list[dict]:
    where_told = {o["at"] for o in came.values() if o["there"]}
    found = []
    for stop in purchase_stops(lines, window):
        at = utc(stop[0].fueled_at)
        if not start <= at <= end or not track:
            continue
        near = geo.where_at(track, at)
        gallons = sum(l.gallons for l in stop)
        found.append({"at": at.isoformat(), "lat": near.lat, "lng": near.lng, "gallons": gallons, "station": stop[0].location,
                      "city": stop[0].city, "state": stop[0].state, "paid": sum(l.billed for l in stop) / gallons,
                      "told": utc(stop[-1].fueled_at).isoformat() in where_told})
    return found


# From when to show what a truck really did: its road's start (a day back without a road), or its last message if that
# is earlier and still within `within` (the window a purchase is matched to it).
def watch_from(road_made_at: datetime | None, recs: list[Recommendation], now: datetime, within: timedelta) -> datetime:
    road = road_made_at or now - timedelta(days=1)
    # so what the driver did after it shows even when a detour remade the road (4482 to a tire shop, 2026-11-04)
    told = [r.made_at for r in recs if now - r.made_at <= within]
    return min([road, max(told)]) if told else road


# The messages sent to drivers, in sum (`came`: what became of each): each one, the discount on the fills at our stops
# (also by day), and the live trucks' Love's share and discount since their first message beside the whole fleet's.
def messages_sent(recs: list[Recommendation], came: dict[int, dict], lines: list[FuelLine]) -> dict:
    sent = sorted(((r, came.get(r.rec_id)) for r in recs if r.sent_at and r.status != "repeat"),  # oldest first; a message
                  key=lambda x: x[0].sent_at)                                                    # sent again by mistake isn't a plan
    there = [o for _, o in sent if o and o["there"]]
    by_day = defaultdict(float)
    for o in there:
        by_day[datetime.fromisoformat(o["at"]).astimezone(CENTRAL).date().isoformat()] += o["discount_total"]
    first = {}  # each truck's first message sent
    for r, _ in sent:
        first[r.unit] = min(first.get(r.unit, r.sent_at), r.sent_at)
    diesel = [l for l in lines if is_diesel(l)]
    live = [l for l in diesel if l.unit in first and utc(l.fueled_at) >= first[l.unit]]
    return {"messages": [{"unit": r.unit, "driver": r.driver, "kind": r.kind, "reason": r.reason or r.kind, "station": r.station,
                          "miles": r.miles_ahead, "sent_at": r.sent_at.isoformat(), "became": became(r, o)} for r, o in sent],
            "at_stops": {"gallons": sum(o["gallons"] for o in there), "discount": sum(o["discount_total"] for o in there),
                         "paid": sum(o["paid_total"] for o in there)},
            "by_day": by_day, "live": _scope(live), "fleet": _scope(diesel)}


# Some diesel fills in figures: gallons, Love's share, the discount, what the company paid, and how many trucks bought them.
def _scope(lines: list[FuelLine]) -> dict:
    s = summarize(lines)
    return {"gallons": s["gallons"], "loves_share": s["loves_share"], "discount": s["discount"], "paid": s["spend"],
            "trucks": len({l.unit for l in lines})}
