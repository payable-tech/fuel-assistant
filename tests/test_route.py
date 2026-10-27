# Tests a plan's waypoints (road order, which ones the truck passed, the Google Maps links), following a sent plan
# (stops reached, fuel bought on or off plan, stops missed, a re-plan, fuel now), and its messages.
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from core import follow, message, route
from models import (Event, Fill, FuelPlan, FuelReading, LoadPlan, Order, PlanStop, Stop, Store, TrackPoint, Truck,
                    Waypoint)

T0 = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)
# A straight road east along the equator, a point every 0.1 degree (about 6.9 mi): mile ~ 69 x lng.
LINE = tuple((0.0, k / 10) for k in range(0, 101))
REACHED, STEP, MISSED = 1.0, 0.5, timedelta(hours=1)


# A Love's at longitude `lng` on the road, selling at $5.
def store(no: str, lng: float) -> Store:
    return Store(store_no=no, city="Town", state="TX", lat=0.0, lng=lng, retail=5.5, net=5.0, price_date="2026-10-21")


# A plan along LINE from longitude `start`: a pickup at lng 3 (unless `start` is past it) and a delivery at lng 9,
# with a 60-gal fuel stop at each of `fuel_lngs` (Love's #600, #601, ... in order).
def load_plan(*fuel_lngs: float, start: float = 0.0, numbers: int = 600) -> LoadPlan:
    stops = (Stop(1, 1, 1, "pickup", 0.0, 3.0, "Ayer", "Massachusetts"),
             Stop(2, 1, 2, "delivery", 0.0, 9.0, "Warrensville Heights", "Ohio"))
    truck = Truck("0226", "s", "V", "Unit 0226", "Jacob", 6.5, 34, None, 0, start, "1 Main St, Lowell, MA, 01850", None,
                  156, "auto", 9, -1, "auto", None, True)
    plan = FuelPlan(stops=tuple(PlanStop(store=store(f"{k}", lng), miles=(lng - start) * 69.1, arrive_gal=30,
                                         gallons=60, cost=300) for k, lng in enumerate(fuel_lngs, start=numbers)),
                    end_gal=42, fuel_cost=300 * len(fuel_lngs))
    return LoadPlan(made_at=T0, truck=truck, order=Order(1, "5016640", "dispatched", "0226", None, stops),
                    stops_ahead=tuple(s for s in stops if s.lng > start), line=tuple(p for p in LINE if p[1] >= start),
                    route_mi=(9 - start) * 69.1, candidates=(), mpg=6.5, price_date="2026-10-21", end_price=5.0,
                    plan=plan)


# The truck's GPS from longitude `a` to `b`, a point every 0.5 degree (gaps of ~35 mi), 30 min apart from `at`.
def drove(a: float, b: float, at: datetime = T0) -> list[TrackPoint]:
    steps = int(round((b - a) * 2))
    return [TrackPoint(at + timedelta(minutes=30 * k), 0.0, a + k / 2) for k in range(steps + 1)]


# The truck standing at longitude `lng` from `at` for `minutes`, a GPS point every 10 minutes.
def parked(lng: float, at: datetime, minutes: int) -> list[TrackPoint]:
    return [TrackPoint(at + timedelta(minutes=m), 0.0, lng) for m in range(0, minutes + 1, 10)]


# A fill-up at longitude `lng` at time `at`: at Love's #`store` (a planned one if its number is), else at a Pilot.
def fill(lng: float, at: datetime, store_no: str | None = None, gallons: float = 60, first: datetime | None = None,
         lat: float | None = 0.0) -> Fill:
    station = f"LOVES #{store_no} TRAVEL STOP" if store_no else "PILOT TRAVEL CENTER #452"
    return Fill(at=at, lat=lat, lng=lng if lat is not None else None, gallons=gallons, billed=gallons * 5.5,
                station=station, city="ABILENE", state="TX", plan_stop=None, first_at=first or at, pump=gallons * 6.0)


# Looks at a plan's progress with the test's distances.
def look(prog, track, fills, now):
    return follow.look(prog, track, fills, now, REACHED, STEP, MISSED)


# Fuel stops slot in where the road reaches them: before the pickup, between pickup and delivery; one close to the
# end never sorts after the delivery.
def test_waypoints_in_road_order():
    assert [w.kind for w in route.waypoints(load_plan(1.5, 6.0))] == ["fuel", "pickup", "fuel", "delivery"]
    assert [w.kind for w in route.waypoints(load_plan(4.0, 6.0))] == ["pickup", "fuel", "fuel", "delivery"]
    assert [w.kind for w in route.waypoints(load_plan(9.0))][-1] == "delivery"


# A stop counts as passed once the truck has been within a mile of it, also across GPS gaps, at the time of the GPS
# point after it; reaching the pickup passes a fuel stop before it that the truck went past another way.
def test_passed_in_order():
    points = route.waypoints(load_plan(1.5, 6.0))
    assert route.passed_at(points, [], REACHED, STEP) == []
    assert route.passed_at(points, drove(0, 2), REACHED, STEP) == [T0 + 90 * MIN]           # fuel stop 1
    assert len(route.passed_at(points, drove(0, 7), REACHED, STEP)) == 3                    # + PU and stop 2
    around = [TrackPoint(T0, 5.0, 0.0), TrackPoint(T0 + 60 * MIN, 0.0, 3.0)]                # never near stop 1
    assert len(route.passed_at(points, around, REACHED, STEP)) == 2


# A delivery near the road before the pickup doesn't count until the pickup is done.
def test_delivery_not_before_pickup():
    points = route.waypoints(load_plan())
    assert route.passed_at(points, drove(9, 9), REACHED, STEP) == []
    assert len(route.passed_at(points, drove(9, 9) + drove(3, 3) + drove(9, 9), REACHED, STEP)) == 2


# The navigation link starts from the phone's own location (no origin) and ends at the last point given.
def test_navigate_link():
    points = [Waypoint("fuel", "a", 1.0, 2.0, 0), Waypoint("pickup", "b", 3.0, 4.0, 1), Waypoint("delivery", "c", 5.0, 6.0, 2)]
    q = parse_qs(urlparse(route.navigate_link(points)).query)
    assert q["destination"] == ["5.00000,6.00000"] and q["waypoints"] == ["1.00000,2.00000|3.00000,4.00000"]
    assert "origin" not in q and q["dir_action"] == ["navigate"]
    assert "waypoints" not in parse_qs(urlparse(route.navigate_link(points[2:])).query)


# Reaching the pickup is an event; fuel bought at planned Love's #600 is stop 1, told once even when looked at again.
def test_follow_pickup_and_purchase():
    prog, new = look(follow.start(load_plan(1.5, 6.0)), drove(0, 4), [fill(1.5, T0 + 90 * MIN, "600")], T0 + 240 * MIN)
    assert [(e.kind, e.stop_no) for e in new] == [("bought", 1), ("pickup", None)] and prog.passed == 2
    again, new = look(prog, drove(0, 4), [fill(1.5, T0 + 90 * MIN, "600")], T0 + 300 * MIN)
    assert new == [] and again == prog


# A purchase is at a planned stop by the Love's store number: a Pilot at the same exit is off plan, and the planned
# Love's counts even when the GPS had a gap then.
def test_purchase_matched_by_store():
    start = follow.start(load_plan(1.5, 6.0))
    assert look(start, drove(0, 2), [fill(1.5, T0 + 90 * MIN)], T0 + 100 * MIN)[1][0].stop_no is None
    assert look(start, drove(0, 2), [fill(1.5, T0 + 90 * MIN, "601", lat=None)], T0 + 100 * MIN)[1][0].stop_no == 2


# A planned stop counts as missed an hour after the truck left it with nothing bought (its fuel line may lag);
# standing there (a break, a 10-hour rest) is not missing it.
def test_missed_after_leaving():
    start = follow.start(load_plan(1.5, 6.0))
    rest = drove(0, 1.5) + parked(1.5, T0 + 90 * MIN, 600)         # 10 hours at stop 1
    assert look(start, rest, [], T0 + 690 * MIN)[1] == []
    went = rest + drove(2.0, 2.0, T0 + 700 * MIN)                  # then left
    assert look(start, went, [], T0 + 730 * MIN)[1] == []          # half an hour after leaving
    _, new = look(start, went, [], T0 + 761 * MIN)
    assert [(e.kind, e.stop_no) for e in new] == [("missed", 1)] and follow.off_plan(new)


# When the gauge since leaving shows no fill, the stop is missed 15 minutes after leaving, not an hour: the re-plan
# comes while the truck can still reach another Love's. A gauge that rose (a fill whose fuel line hasn't come in) or
# no readings after leaving leaves it to the hour. Stop 1 is reached at T0+90 (lng 1.5) and left at T0+120 (lng 2).
def test_missed_sooner_by_the_gauge():
    start = follow.start(load_plan(1.5, 6.0))
    track, left = drove(0, 2), T0 + 120 * MIN

    def quick(gauge, minutes):
        return look_with(start, track, gauge, left + minutes * MIN)

    flat = [FuelReading(T0 + 80 * MIN, 30), FuelReading(left + 6 * MIN, 28)]
    assert quick(flat, 10) == [] and [(e.kind, e.stop_no) for e in quick(flat, 16)] == [("missed", 1)]
    filled = [FuelReading(T0 + 80 * MIN, 30), FuelReading(left + 6 * MIN, 70)]
    assert quick(filled, 16) == [] and quick(filled, 61) != []          # rose: wait for its fuel line, then the hour
    assert quick([FuelReading(T0 + 80 * MIN, 30)], 16) == []            # nothing read since leaving: can't tell


# Looks with the gauge readings and the quick rule (15 min, a rise under 5 points means no fill).
def look_with(prog, track, gauge, now):
    return follow.look(prog, track, [], now, REACHED, STEP, MISSED, gauge, timedelta(minutes=15), 5)[1]


# A fuel line coming in after the stop was told missed makes it bought: the message tells it as done only.
def test_late_line_after_missed():
    p = load_plan(1.5, 6.0)
    missed, _ = look(follow.start(p), drove(0, 2), [], T0 + 300 * MIN)
    later, new = look(missed, drove(0, 2), [fill(1.5, T0 + 90 * MIN, "600")], T0 + 320 * MIN)
    assert [(e.kind, e.stop_no) for e in new] == [("bought", 1)]
    assert [e.kind for e in follow.as_told(later.events)] == ["bought"]
    assert "drove past" not in message.plan_text(p, later, new, 80, 140)


# Purchases a few minutes apart are one stop: a line that joins a stop already told updates its gallons, even once
# the lines span more than the 2-hour grouping window; it isn't told again.
def test_late_line_joins_stop():
    prog, _ = look(follow.start(load_plan(1.5, 6.0)), drove(0, 2), [fill(1.5, T0 + 90 * MIN, "600", gallons=50)],
                   T0 + 100 * MIN)
    joined = fill(1.5, T0 + 300 * MIN, "600", gallons=150, first=T0 + 90 * MIN)  # lines 08:00 ... 11:30 as one stop
    after, new = look(prog, drove(0, 2), [joined], T0 + 310 * MIN)
    assert new == [] and [e.gallons for e in after.events if e.kind == "bought"] == [150]


# The road can pass near the delivery before the pickup: that doesn't end the trip, and later purchases still count.
def test_delivery_passed_early_doesnt_end():
    early = drove(9, 9) + drove(0, 4, T0 + 30 * MIN)                # near the DEL first, then down the road
    prog, new = look(follow.start(load_plan(1.5, 6.0)), early, [fill(1.5, T0 + 120 * MIN, "600")], T0 + 300 * MIN)
    assert ("bought", 1) in [(e.kind, e.stop_no) for e in new] and not follow.finished(prog)


# Fuel bought elsewhere is off plan. The re-plan from there drops stop 2 (the new road doesn't use it), leaves the
# stop already passed alone (a fuel line may still come in), numbers its new Love's 3, and starts the new road.
def test_off_plan_and_replan():
    p = load_plan(1.5, 6.0)
    prog, new = look(follow.start(p), drove(0, 2), [fill(2.0, T0 + 95 * MIN)], T0 + 100 * MIN)
    assert [(e.kind, e.stop_no) for e in new] == [("bought", None)] and follow.off_plan(new)
    assert new[0].label == "Pilot Travel Center #452 Abilene, TX"
    assert look(follow.start(p), [], [fill(2.0, T0, "473")], T0)[1][0].label == "Love's #473 Abilene, TX"
    road = load_plan(7.5, start=2.0, numbers=700)
    after, more = follow.replanned(prog, replace(road, made_at=T0 + 100 * MIN), T0 + 100 * MIN)
    assert [(e.kind, e.stop_no) for e in more] == [("dropped", 2), ("replanned", None)]
    text = message.plan_text(p, after, new + more, 100, 0)
    assert "🔁 Rest of the road re-planned · from near Lowell, MA" in text  # the headline tells the re-plan ...
    assert "⛽ Pilot Travel Center #452 Abilene, TX · 60 gal · $6.00 (not on plan)" in text
    assert "no longer needed" not in text and "Re-planned from near" not in text  # ... the body only what was done
    assert "Still to buy: 60 gal · ~$330 · 1 stop\nBought so far: 60 gal · $360 · 1 stop, 0 on plan" in text
    assert "⛽ 1. <a" in text  # ahead counts from 1
    road = after.road
    assert after.passed == 0 and after.road is road and follow.number(after, route.waypoints(road)[1]) == 3
    assert [s.kind for s in follow.stops_left(after)] == ["pickup", "delivery"]


# A re-plan that stops at the same Love's in the same order only changes the amounts: nothing new to tell. The
# Love's told as ahead are the ones a re-plan keeps when they still work (planner.plan's `keep`).
def test_same_stops():
    prog = follow.start(load_plan(1.5, 6.0))
    assert follow.same_stops(prog, load_plan(1.5, 6.0, start=0.5))      # same two Love's from a bit further on
    assert not follow.same_stops(prog, load_plan(6.0, start=0.5))        # one of them dropped
    assert follow.same_stops(replace(prog, passed=1), load_plan(6.0, numbers=601, start=2.0))  # stop 1 behind
    assert follow.stores_ahead(prog) == {"600", "601"} and follow.stores_ahead(replace(prog, passed=1)) == {"601"}


# The road ahead is re-planned when it no longer fits the fuel on board: a planned fill would overflow the tank, or
# the truck would arrive under the reserve. Not when it keeps the reserve, not when a truck already under the reserve
# is on its way to its next fuel stop, and not within an hour of the road being made (a truck idling in a yard or a
# wobbling gauge would re-plan it again and again); a road with no safe plan is tried again after that hour too.
def test_needs_replan():
    p = load_plan(1.5, 6.0)  # 156-gal tank: reserve 15.6 gal
    hour = timedelta(hours=1)

    def check(prog, gal, here, now=T0 + 2 * hour):
        return follow.needs_replan(prog, gal, here, 15.6, 156, 5, now, hour)

    start = follow.start(p)
    skipped = (Event("missed", "Love's #600 Town, TX", T0, 1),)
    assert not check(start, 53, 0)                                  # as planned: never under the reserve
    assert check(start, 150, 0)                                     # bought elsewhere: stop 1's 60 gal won't fit
    assert not check(start, 150, 0, T0 + 30 * MIN)                  # but not within the hour after the road was made
    assert check(replace(start, passed=2, events=skipped), 20, 207)  # stop 1 missed: it would run dry before stop 2
    assert not check(replace(start, passed=2), 20, 207)             # stop 1 just passed, its fuel line not in: wait
    assert not check(replace(start, passed=2, events=skipped), 14, 380)  # under the reserve, near stop 2: fine
    no_plan = follow.start(replace(p, plan=None))
    assert not check(no_plan, 10, 0, T0) and check(no_plan, 10, 0)


# Fuel now is the gauge while it is fresh and nothing was just bought; else the estimate from the plan: its start,
# less the miles driven at its MPG, plus what was bought.
def test_fuel_now():
    p = load_plan(1.5)
    args = (timedelta(hours=2), timedelta(minutes=30), 0.1)
    bought = (Event("bought", "x", T0, None, 50, 275),)
    estimate = follow.fuel_gal(p, drove(0, 1), bought, 0.1)
    assert abs(estimate - (0.34 * 156 - 1.0 * 69.1 / 6.5 + 50)) < 1
    assert follow.fuel_now(p, drove(0, 1), (), 40, T0, T0 + 10 * MIN, *args) == 0.40 * 156
    assert follow.fuel_now(p, drove(0, 1), bought, 90, T0, T0 + 10 * MIN, *args) == estimate  # just bought
    assert follow.fuel_now(p, drove(0, 1), (), 40, T0, T0 + 60 * MIN, *args) == follow.fuel_gal(p, drove(0, 1), (), 0.1)


# The first message: what happened, the load and fuel, the road in order, the totals and the link, split by
# "--------" lines; PU and DEL with state codes, each stop with the fuel expected on arrival and what to buy, at the
# pump price only (the store's discounted $5.00 never shows).
def test_first_message():
    text = message.first_text(load_plan(1.5, 6.0))
    assert text.startswith("<b>⛽ New fuel plan · Unit 0226</b>") and text.count(message.LINE) == 3
    assert "Load 5016640 · Lowell, MA → Warrensville Heights, OH · 622 mi" in text
    assert "📦 PU Ayer, MA · in 207 mi" in text and "buy 60 gal · $5.50" in text and "$5.00" not in text
    assert "Total: 120 gal · ~$660 · 2 stops" in text and "▶ Start the road" in text


# An update tells what happened first, crosses out what is done and links only what is ahead; the last one, at the
# delivery, sets what was bought beside the plan, with no link. An older message's link is taken off.
def test_update_and_final_messages():
    p = load_plan(1.5, 6.0)
    prog, new = look(follow.start(p), drove(0, 4), [fill(1.5, T0 + 90 * MIN, "600")], T0 + 240 * MIN)
    text = message.plan_text(p, prog, new, 80, 4 * 69.1)
    assert text.startswith("<b>✅ Stop done · Unit 0226</b> · bought 60 gal at Love's #600 Town, TX\n✅ PU Ayer, MA done")
    assert "<s>⛽ Love's #600 Town, TX ✓ 60 gal · $360</s>" in text and "<s>📦 PU Ayer, MA ✓</s>" in text
    assert "⛽ 1. <a" in text and "⛽ 2. <a" not in text  # the one Love's still ahead is stop 1 now
    assert "Still to buy: 60 gal · ~$330 · 1 stop\nBought so far: 60 gal · $360 · 1 stop, 1 on plan" in text  # at the pump
    assert "Plan:" not in text and "▶ Continue the road" in text
    assert message.superseded(text).endswith(message.NEWER)
    done, new = look(prog, drove(0, 9.5), [fill(6.0, T0 + 360 * MIN, "601")], T0 + 540 * MIN)
    final = message.plan_text(p, done, new, 40, 9 * 69.1)
    assert final.startswith("<b>🏁 Delivered · Unit 0226</b> · plan followed") and "▶" not in final
    assert "🏁 DEL Warrensville Heights, OH ✓ arrived with ~40 gal" in final
    # at the pump: $720 bought vs the plan's $660, and 2 gal less left at $5.00 (no pump price kept near the end)
    assert "Extra cost vs plan: +$70 (2 gal less left, counted at $5.00)" in final
    pumped = message.plan_text(replace(p, end_pump=6.0), done, new, 40, 9 * 69.1)
    assert "Extra cost vs plan: +$72 (2 gal less left, counted at $6.00)" in pumped


# With no Love's in reach the plan's first stop is another station (Google Places): the message names it, says why,
# and shows its pump price, or that none is known. A fill-up where its GPS place was counts as that stop; anywhere
# else, any station other than a planned Love's stays off plan.
def test_station_that_is_not_a_loves():
    p = load_plan(1.5, 6.0)
    first = replace(p.plan.stops[0].store, store_no="ChIJ1", name="Stinker Stores", retail=6.5, net=6.5)
    p = replace(p, plan=replace(p.plan, stops=(replace(p.plan.stops[0], store=first),) + p.plan.stops[1:]))
    text = message.first_text(p)
    assert ">Stinker Stores Town, TX</a> · in 104 mi · no Love's in reach" in text and "buy 60 gal · $6.50" in text
    unknown = replace(p, plan=replace(p.plan, stops=(replace(p.plan.stops[0], store=replace(first, price_date="")),)
                                      + p.plan.stops[1:]))
    assert "buy 60 gal · pump price not known" in message.first_text(unknown)
    there = replace(fill(1.5, T0 + 90 * MIN), station="STINKER STORE #12", plan_stop=1)
    _, new = look(follow.start(p), drove(0, 4), [there], T0 + 240 * MIN)
    assert [(e.kind, e.stop_no, e.label) for e in new if e.kind == "bought"] == [("bought", 1, "Stinker Stores Town, TX")]
    elsewhere = replace(fill(6.0, T0 + 300 * MIN), plan_stop=2)  # a Pilot by planned Love's stop 2
    _, new = look(follow.start(p), drove(0, 7), [elsewhere], T0 + 400 * MIN)
    assert [e.stop_no for e in new if e.kind == "bought"] == [None]


# The driver's own route (the road's via) is kept by re-plans while it is ahead, and dropped once the truck is there.
def test_via_ahead():
    road = replace(load_plan(1.5, 6.0), via=((0.0, 5.0),))  # a point at mile ~345
    assert follow.via_ahead(road, 2 * 69.1, 1.0) == ((0.0, 5.0),)
    assert follow.via_ahead(road, 5 * 69.1, 1.0) == () and follow.via_ahead(road, 7 * 69.1, 1.0) == ()


# A stop passed with nothing to tell yet only moves the message's link on: it no longer leads through that stop.
def test_link_moves_on():
    p = load_plan(1.5, 6.0)
    text = message.first_text(p)
    moved = message.with_link(text, replace(follow.start(p), passed=1))
    assert moved.count("%7C") == text.count("%7C") - 1 and "▶ Continue the road" in moved
