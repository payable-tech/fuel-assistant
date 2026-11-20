# Tests the fuel recommendation's rules on real cases from October: the hard stop beats the driver's habit, stops well
# above his level are never picked, money picks among the rest, and a Love's stop is always a fill-up.
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core import geo, message, recommend
from models import Decision, FuelRules, Order, Recommendation, Store, StoreOnRoute, Truck, TruckNow, UsualLevel

RULES = FuelRules(reserve_pct=10, worse=0.8, above_usual=5, look_mi=150, part_gap=0.50, part_reach_mi=500, part_min_gal=30,
                  part_margin_gal=25, low_penalty=5, urgent_pct=25, hold_min=60, near_mi=2, max_passed=2, last_pct=3)
JACOB = UsualLevel(usual_pct=13, low_pct=8, high_pct=16.25, fill_pct=99, stops=20)
FAR = 5000.0  # a road's end too far to matter


# A Love's along the road.
def at(mile: float, net: float, retail: float | None = None, city: str = "Town") -> StoreOnRoute:
    return StoreOnRoute(store=Store("1" + str(int(mile)), city, "TX", 30.0, -97.0, retail or net + 0.5, net, "2026-10-19"), miles=mile, off_mi=0.1)


# Jacob's truck: 156-gal tank, 6.69 MPG, at a gauge level and a mile of the road.
def jacob(pct: float, mile: float = 0.0, usual: UsualLevel = JACOB) -> TruckNow:
    return TruckNow(fuel_gal=pct / 100 * 156, mile=mile, tank_gal=156, forecast_mpg=6.69, cautious_mpg=6.69 * 0.8, usual=usual)


# Oct 19 at Skippers VA, gauge 30%: Dunn is above his level but the last safe Love's (Dillon would be 7% if MPG drops).
def test_hard_stop_beats_his_habit():
    d = recommend.decide(jacob(30, 3675), [at(3784, 5.25, 5.69, "Dunn"), at(3869, 5.59, 5.59, "Dillon")], FAR, RULES)
    assert (d.kind, d.stop.store.city, d.reason) == ("stop", "Dunn", "hard_stop")
    assert round(d.arrive_pct) == 20 and round(d.worst_pct) == 17
    text = message.text(jacob(30, 3675), d)  # Dillon can still be reached: skipping is harmless, a plain fuel stop
    assert text.startswith("⛽ Fuel stop: Love's Dunn, TX") and "low" not in text and "skip" not in text and "cheaper" not in text


# Oklahoma City, 2026-11-09 (6282): no Love's after the stop is in reach, so skipping it means low fuel. The warning
# comes whether the stop was picked at his level or as the hard stop; not when the load's end is still in reach.
def test_last_loves_in_reach_is_a_warning():
    at_level = recommend.decide(jacob(18), [at(30, 5.5), at(400, 5.5)], FAR, RULES)
    assert (at_level.kind, at_level.reason, at_level.stop.miles) == ("stop", "last", 30)
    assert at_level.worst_pct >= RULES.reserve_pct  # still above the reserve: a warning, not an emergency
    text = message.text(jacob(18), at_level)
    assert "⚠️ Last Love's you can reach: Town, TX" in text and "Fill up, don't skip it" in text
    early = recommend.decide(jacob(30), [at(50, 5.5), at(400, 5.5)], FAR, RULES)
    assert (early.kind, early.reason, early.stop.miles) == ("stop", "last", 50)
    end_in_reach = recommend.decide(jacob(30), [at(50, 5.5)], 200.0, RULES)
    assert end_in_reach.reason == "hard_stop" and "skip" not in message.text(jacob(30), end_in_reach)
    more_ahead = recommend.decide(jacob(18), [at(30, 5.5), at(60, 5.6), at(400, 5.5)], FAR, RULES)
    assert more_ahead.reason == "range"


# Nothing is told until the stop is close: at 60 miles, Dunn at 109 miles is still only being watched.
def test_told_only_when_close():
    later = replace(RULES, look_mi=60)
    d = recommend.decide(jacob(30, 3675), [at(3784, 5.25, 5.69), at(3869, 5.59, 5.59)], FAR, later)
    assert (d.kind, d.reason) == ("watch", "hard_stop")


# A Love's he'd reach well above his level isn't picked while a safe one at his level comes later.
def test_too_early_is_not_picked():
    d = recommend.decide(jacob(25), [at(40, 4.00), at(100, 5.50), at(140, 5.50)], FAR, RULES)
    assert d.stop.miles == 100 and d.reason == "range"


# Among the stops at his level, the one saving the most money.
def test_money_picks_inside_his_range():
    d = recommend.decide(jacob(23), [at(80, 5.60), at(100, 5.30)], FAR, RULES)
    assert d.stop.miles == 100


# Nothing to tell while the stop is still far; nothing at all when the delivery is safely in reach.
def test_watch_then_enough():
    assert recommend.decide(jacob(60), [at(400, 5.5)], FAR, RULES).kind == "watch"
    assert recommend.decide(jacob(60), [at(100, 5.5)], 200.0, RULES).kind == "enough"


# Barstow to Lake Havasu, real prices: a much cheaper Love's ahead, also at the pump, and still a fill-up. Part fills
# were told 12 times and never bought as asked (the user's go, 2026-11-11).
def test_a_loves_stop_is_always_a_fill_up():
    truck = jacob(25, usual=UsualLevel(22, 15, 30, 95, 20))
    d = recommend.decide(truck, [at(50, 7.45, 8.19, "Barstow"), at(220, 6.00, 6.69, "Havasu")], FAR, RULES)
    assert d.kind == "stop" and d.stop.store.city == "Barstow" and d.then is None
    assert d.gallons == 0.95 * 156 - (truck.fuel_gal - 50 / truck.forecast_mpg)
    words = message.text(truck, d)
    assert "🛢 Fill up" in words and "Buy about" not in words and "Then fill up" not in words


# No Love's can be counted on: urgent, naming the next one if any.
def test_urgent():
    d = recommend.decide(jacob(11), [at(100, 5.5)], FAR, RULES)
    assert (d.kind, d.reason) == ("urgent", "low") and d.stop.miles == 100
    assert recommend.decide(jacob(11), [], FAR, RULES).stop is None
    assert f"Fuel is low: 11% ({0.11 * 156:.0f} gal)" in message.text(jacob(11), d)


# 800 miles without a Love's and the tank at 70%: nothing to shout about yet.
def test_long_gap_is_not_urgent_while_there_is_fuel():
    assert recommend.decide(jacob(70), [at(800, 5.5)], FAR, RULES).kind == "watch"
    assert recommend.decide(jacob(20), [at(800, 5.5)], FAR, RULES).kind == "urgent"


# A stop told stands while it can be reached, even under the reserve; only past reach does it change.
def test_told_stop_stands_under_the_reserve():
    assert recommend.in_reach(jacob(14), at(50, 5.5), RULES)
    assert recommend.worst_pct(jacob(14), 50) < 10
    assert not recommend.in_reach(jacob(12), at(100, 5.5), RULES)


# Under the reserve with Love's still in reach is no emergency: the nearest one, then the last with its own words.
def test_elastic_reserve():
    two = recommend.decide(jacob(12), [at(30, 5.5), at(50, 5.0)], FAR, RULES)
    assert (two.kind, two.reason, two.stop.miles) == ("stop", "tight", 30)
    assert "Fuel is getting low" in message.text(jacob(12), two) and "⚠️" not in message.text(jacob(12), two)
    one = recommend.decide(jacob(12), [at(30, 5.5), at(120, 5.0)], FAR, RULES)
    assert (one.kind, one.reason, one.stop.miles) == ("stop", "last", 30)
    assert "Last Love's you can reach: Town, TX" in message.text(jacob(12), one) and "don't skip it" in message.text(jacob(12), one)
    past = recommend.decide(jacob(12), [at(120, 5.0)], FAR, RULES)
    assert (past.kind, past.reason) == ("urgent", "low")


# An emergency never names a station he'd run dry before reaching.
def test_emergency_names_only_what_he_can_reach():
    far = recommend.decide(jacob(6), [at(200, 5.6)], FAR, RULES)
    assert far.kind == "urgent" and "Find the nearest truck stop now" in message.text(jacob(6), far)
    near = recommend.decide(jacob(9), [at(70, 5.6)], FAR, RULES)
    assert near.kind == "urgent" and "Love's Town, TX" in message.text(jacob(9), near)


# The link: from the phone (no start given) through the fuel stop, to the load's last stop.
def test_road_link():
    stop = at(100, 5.5)
    points = message.link_points([stop], [(900.0, (33.0, -96.0))], 3)
    assert points == [(30.0, -97.0), (33.0, -96.0)]
    link = message.road_link(points)
    assert link.startswith("https://www.google.com/maps/dir/?api=1&destination=33.00000,-96.00000")
    assert "waypoints=30.00000,-97.00000" in link and "dir_action=navigate" in link and "origin" not in link


# Things in road order: a pickup before the stop comes first, the delivery always last.
def test_link_keeps_road_order():
    points = message.link_points([at(100, 5.5)], [(900.0, (33.0, -96.0)), (50.0, (31.0, -98.0))], 3)
    assert points == [(31.0, -98.0), (30.0, -97.0), (33.0, -96.0)]


# A phone takes few stops on the way: the fuel stops stay, the load's further ones go, the last stop stays.
def test_link_keeps_the_fuel_stops():
    load = [(float(m), (31.0 + m / 1000, -98.0)) for m in (10, 20, 30, 40, 900)]
    points = message.link_points([at(500, 5.5), at(700, 5.0)], load, 3)
    assert len(points) == 4 and points.count((30.0, -97.0)) == 2 and points[-1] == (31.9, -98.0)


# No stop: no link. No load: the link goes to the fuel stop alone.
def test_no_link_without_a_stop():
    assert message.road_link(message.link_points([], [(9.0, (1.0, 2.0))], 3)) is None
    assert message.road_link(message.link_points([], [], 3)) is None
    assert message.link_points([at(100, 5.5)], [], 3) == [(30.0, -97.0)]


# The message: the station with its pump price, where, what to do, what he arrives with. In Telegram the name shows the
# station, and a separate link starts the road.
def test_message():
    truck = jacob(20)
    d = recommend.decide(truck, [at(60, 5.91, 6.49, "Sparta"), at(120, 5.91, 6.49)], FAR, RULES)
    words = message.text(truck, d).split("\n")
    assert words[0] == "⛽ Fuel stop: Love's Sparta, TX" and words[2] == "Love's Sparta, TX - $6.49/gal"
    arrives = 0.2 * 156 - 60 / 6.69
    assert words[4:7] == ["📍 In 60 mi", "🛢 Fill up", f"🪫 Arrive with about {100 * arrives / 156:.0f}% ({arrives:.0f} gal)"]
    sent = message.html_text(truck, d, "https://x/?a=1&b=2")
    assert 'maps/search/?api=1&amp;query=30.00000,-97.00000">Love\'s Sparta, TX</a> - $6.49/gal' in sent
    assert sent.endswith('<a href="https://x/?a=1&amp;b=2">▶ Start the road</a>')


# The message says a Love's highway and exit after the miles when its page gave them (the user's ask, 2026-11-11), in
# plain text and in Telegram's HTML; without them the line is as before.
def test_message_names_the_exit():
    truck = jacob(20)
    sparta = at(60, 5.91, 6.49, "Sparta")
    known = replace(sparta, store=replace(sparta.store, way="I-90 (Exit 34)"))
    d = recommend.decide(truck, [known, at(120, 5.91, 6.49)], FAR, RULES)
    assert message.text(truck, d).split("\n")[4] == "📍 In 60 mi, I-90 (Exit 34)"
    assert "📍 In 60 mi, I-90 (Exit 34)\n" in message.html_text(truck, d, None)
    plain = recommend.decide(truck, [sparta, at(120, 5.91, 6.49)], FAR, RULES)
    assert message.text(truck, plain).split("\n")[4] == "📍 In 60 mi"


# A truck stop found by Google has no price, and none is made up.
def test_no_price_no_price_line():
    stop = StoreOnRoute(store=Store("g", "Town", "TX", 30.0, -97.0, 0.0, 0.0, "", name="Pilot"), miles=30, off_mi=0.1)
    words = message.text(jacob(20), Decision("urgent", stop=stop, reason="low"))
    assert "\nPilot Town, TX\n" in words and "$" not in words


# With no Love's left in reach but the delivery still is, there's nothing to shout about.
def test_delivery_in_reach_is_no_emergency():
    assert recommend.decide(jacob(9), [at(120, 5.0)], 40.0, RULES).kind == "enough"


# Under the reserve but far from the next Love's: watched until it's close.
def test_tight_is_told_only_when_close():
    d = recommend.decide(jacob(20), [at(100, 5.5), at(800, 5.0)], FAR, replace(RULES, look_mi=60))
    assert (d.kind, d.reason) == ("watch", "last")


# Regions: where fuel will be needed down the road, and a mark where a much cheaper Love's lies past one.
def test_regions():
    stops = [at(m, 6.5, 7.0) for m in range(100, 1500, 100)] + [at(1550, 5.5, 6.0)]
    found = recommend.regions(jacob(60), stops, 2000.0, RULES)
    assert len(found) >= 2
    assert found[0].from_mi <= found[0].to_mi < found[1].from_mi
    assert any(r.cheaper_ahead for r in found)
    assert recommend.regions(jacob(60), stops, 200.0, RULES) == []


# The picture of Jacob at Skippers: Dunn is too early by his level but the stop, Dillon under reserve, and the forecast
# starts from the gauge.
def test_picture():
    seen = recommend.picture(jacob(30, 3675), [at(3600, 5.0), at(3784, 5.25, 5.69), at(3869, 5.59, 5.59)], FAR, RULES)
    assert [v.verdict for v in seen.views] == ["passed", "early", "late"]
    assert recommend.picture(jacob(12), [at(120, 5.0)], FAR, RULES).views[0].verdict == "out"
    assert seen.decision.stop.miles == 3784


# A Love's that fails the safety rule isn't in the region when one that passes is (Tre's Sparta, not Shepherdsville).
def test_region_follows_the_safety_rule():
    tre = TruckNow(fuel_gal=47, mile=0, tank_gal=162, forecast_mpg=8.0, cautious_mpg=5.86, usual=UsualLevel(18, 6, 39, 97, 19))
    found = recommend.regions(tre, [at(56, 6.27), at(161, 5.91), at(238, 5.89)], 1164.0, RULES)
    assert (found[0].from_mi, found[0].to_mi, found[0].fill_mi) == (161, 161, 161)


# The stop told comes first in the regions and the fuel line, with its part fill, whatever the rules would pick now.
def test_told_stop_leads_the_plan():
    tre = TruckNow(fuel_gal=47, mile=0, tank_gal=162, forecast_mpg=8.0, cautious_mpg=5.86, usual=UsualLevel(18, 6, 39, 97, 19))
    stops = [at(56, 6.27), at(161, 5.91), at(368, 5.62)]
    seen = recommend.picture(tre, stops, 1164.0, RULES, (stops[0], 35.0))
    assert seen.regions[0].fill_mi == 56
    assert round(seen.regions[0].fill_pct - recommend.arrive_pct(tre, 56)) == round(100 * 35 / 162)


# The zone of the tank now: from his level at the expected MPG, the reserve and empty at the cautious MPG, so a Love's
# in the green is one the rules call safe and at his level, and one in the red isn't safe.
def test_the_zone_agrees_with_the_verdicts():
    truck = jacob(30, 100)
    stops = [at(m, 5.5) for m in range(110, 500, 10)]
    seen = recommend.picture(truck, stops, FAR, RULES)
    z = seen.zones[0]
    assert z.start_mi < z.reserve_mi < z.end_mi and round(z.end_mi) == 100 + round(0.3 * 156 * 6.69 * 0.8)
    for v in seen.views:
        if v.verdict == "range":
            assert z.start_mi <= v.stop.miles <= z.reserve_mi
        if v.verdict == "late":
            assert v.stop.miles > z.reserve_mi


# A truck already under his level is in its zone at once, and a zone past the road's end isn't drawn.
def test_zone_limits():
    assert recommend.zones(jacob(10), [], FAR, RULES)[0].start_mi == 0
    assert recommend.zones(jacob(90), [], 100.0, RULES) == ()


# A city in capitals on the price sheet reads normally in the message; others stay as written.
def test_station_name():
    assert recommend.station(at(10, 5.0, city="BIG SPRING")) == "Love's Big Spring, TX"
    assert recommend.station(at(10, 5.0, city="McPherson")) == "Love's McPherson, TX"


HOT_SPOT = StoreOnRoute(store=Store("g", "Inman", "SC", 35.08, -82.06, 0.0, 0.0, "", name="HOT SPOT"), miles=18, off_mi=0.3)


# 0226 on Nov 3 at 17%, no Love's in reach: buy just enough at the truck stop to reach Love's Newport with the reserve
# (at least 30 gal), not a fill-up; with no Love's ahead, a fill-up.
def test_backup_buys_only_to_the_next_loves():
    truck, newport = jacob(17), at(133, 5.95, 6.39, "Newport")
    gallons, then = recommend.backup_amount(truck, HOT_SPOT, newport, RULES)
    assert (gallons, then) == (30, newport)
    on_arrival = recommend.worst_pct(truck, 18) / 100 * 156
    assert gallons + on_arrival - 115 / truck.cautious_mpg >= 0.10 * 156     # the reserve holds on the way
    assert recommend.backup_amount(truck, HOT_SPOT, None, RULES) == (0.99 * 156 - on_arrival, None)


# The message for it: how much to buy, and the Love's to fill up at after. No card line (the user's call).
def test_backup_message():
    newport = at(133, 5.95, 6.39, "Newport")
    words = message.text(jacob(17), Decision("urgent", stop=HOT_SPOT, gallons=30, then=newport, reason="low")).split("\n")
    assert words[0].startswith("⚠️ Fuel is low") and words[2] == "HOT SPOT Inman, SC" and words[5] == "🛢 Buy about 30 gal, don't fill up"
    assert words[-2:] == ["Then fill up at Love's Newport, TX - $6.39/gal", "📍 115 mi further"] and "💳" not in "".join(words)


# A told stop at the next look: it stands while ahead and reachable; driven past it ends; a road made anew without it
# replaces it. An urgent message stands even out of reach, and one naming no place stands until he fuels (2026-11-05).
def test_told_now():
    rec = Recommendation(1, "0226", "Jacob", 1, "L", datetime(2026, 11, 5, tzinfo=timezone.utc), "stop", "1100", "Love's Town, TX",
                         100.0, 20.0, 10.0, 8.0, 100.0, None, "range", 5.5, 6.0, "2026-11-05", 6.69, 5.35, 13.0, "text", "open", None)
    near, far, truck = at(100, 5.5), at(1000, 5.5), jacob(20)
    assert recommend.told_now(rec, near, truck, False, RULES) is None
    assert recommend.told_now(rec, None, truck, False, RULES) == "passed"
    assert recommend.told_now(rec, None, truck, True, RULES) == "replaced"
    assert recommend.told_now(rec, far, truck, False, RULES) == "replaced"          # out of reach now
    urgent = replace(rec, kind="urgent", reason="low")
    assert recommend.told_now(urgent, far, truck, False, RULES) is None              # told as an emergency: stands
    assert recommend.told_now(urgent, None, truck, False, RULES) == "passed"
    assert recommend.told_now(replace(urgent, store_no=None), None, truck, False, RULES) is None  # names no place


LINE = [(30.0 + k * 0.1, -97.0) for k in range(20)]  # about 130 miles due north
NOV2 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
TOLD = Recommendation(1, "340", "Ali", 1, "L-1", NOV2, "stop", "140", "Love's Town, TX", 30.0, 20.0, 18.0, 17.0, 30.0, None, "range",
                      5.5, 6.0, "2026-11-02", 7.0, 5.6, 20.0, "Fill up", "open", None)


# The stop told is found on the road while still ahead: a Love's by its number, an urgent message's truck stop by its
# place, so it stands and isn't sent again each look (0226, 2026-11-03). Driven past, it is gone.
def test_told_stop():
    loves = at(40, 5.5)
    assert recommend.told_stop(TOLD, [loves], LINE, 10.0, 2, 0.5) == loves
    assert recommend.told_stop(TOLD, [loves], LINE, 50.0, 2, 0.5) is None                 # driven past
    urgent = replace(TOLD, kind="urgent", store_no="ChIJx", station="HOT SPOT Inman, SC", lat=30.5, lng=-97.0)
    stop = recommend.told_stop(urgent, [loves], LINE, 10.0, 2, 0.5)
    assert stop is not None and 33 < stop.miles < 36 and stop.store.store_no == "ChIJx"
    assert recommend.told_stop(urgent, [], LINE, 50.0, 2, 0.5) is None                    # driven past
    assert recommend.told_stop(replace(urgent, lat=None, lng=None), [], LINE, 10.0, 2, 0.5) is None
    assert recommend.told_stop(replace(urgent, kind="stop"), [], LINE, 10.0, 2, 0.5) is None


# A fuel stop isn't told just after a fill was seen (it may still be going on: 14755 at Tolleson, 2026-11-04), nor when
# the driver is already there; low fuel always is.
def test_quiet():
    here = TruckNow(fuel_gal=60, mile=100.0, tank_gal=150, forecast_mpg=7.0, cautious_mpg=5.6, usual=UsualLevel(30, 20, 40, 95, 9))

    # A decision naming a Love's at a mile of the road.
    def stop(miles, kind="stop", reason="range"):
        return Decision(kind, stop=at(miles, 5.5), reason=reason)

    long_ago = NOV2 - timedelta(hours=2)
    assert recommend.quiet(here, stop(150), NOV2 - timedelta(minutes=10), NOV2, RULES)   # fueled 10 min ago
    assert not recommend.quiet(here, stop(150), long_ago, NOV2, RULES) and not recommend.quiet(here, stop(150), None, NOV2, RULES)
    assert recommend.quiet(here, stop(101.5), None, NOV2, RULES)                          # there
    assert recommend.quiet(here, stop(99.8, reason="hard_stop"), None, NOV2, RULES)
    assert not recommend.quiet(here, stop(101.5, reason="tight"), None, NOV2, RULES)     # under the reserve: told
    assert not recommend.quiet(here, stop(101.5, kind="urgent", reason="low"), NOV2, NOV2, RULES)


# After two stops told and driven past on one tank, a third plain stop isn't told (50779 got 7 in a day, 2026-11-05; of
# 23 third-or-later messages, 1 was followed). The last Love's in reach, a detour and low fuel still are.
def test_quiet_after_two_stops_driven_past():
    here = TruckNow(fuel_gal=60, mile=100.0, tank_gal=150, forecast_mpg=7.0, cautious_mpg=5.6, usual=UsualLevel(30, 20, 40, 95, 9))
    for reason, held in (("range", True), ("hard_stop", True), ("detour", False), ("tight", False), ("last", False)):
        d = Decision("stop", stop=at(150, 5.5), worst_pct=15, reason=reason)
        assert recommend.quiet(here, d, None, NOV2, RULES, passed=2) is held and recommend.skipped(d, 2, RULES) is held
        assert not recommend.quiet(here, d, None, NOV2, RULES, passed=1) and not recommend.skipped(d, 1, RULES)
    urgent = Decision("urgent", stop=at(150, 5.5), reason="low")
    assert not recommend.quiet(here, urgent, None, NOV2, RULES, passed=5) and not recommend.skipped(urgent, 5, RULES)


# The road where a truck stop is looked for: from the truck to where its fuel runs out at the MPG expected.
def test_in_range():
    truck = TruckNow(fuel_gal=10, mile=10.0, tank_gal=150, forecast_mpg=5.0, cautious_mpg=4.0, usual=JACOB)  # 50 mi of fuel
    marks = geo.along(LINE)
    assert recommend.in_range(truck, LINE) == LINE[2:9] and marks[2] >= 10 > marks[1] and marks[8] <= 60 < marks[9]


# With no Love's in reach, a truck stop nearer than the next Love's takes its place, buying just enough to get there;
# none found, or one past that Love's, changes nothing.
def test_with_backup():
    truck, newport = jacob(17, 10), at(133, 5.95, 6.39, "Newport")
    d = Decision("urgent", stop=newport, reason="low")
    backup = recommend.with_backup(truck, d, [replace(HOT_SPOT, miles=8)], RULES)  # 8 mi along the road in range
    assert backup.stop == replace(HOT_SPOT, miles=18) and backup.then == newport
    assert (backup.gallons, backup.then) == recommend.backup_amount(truck, backup.stop, newport, RULES)
    assert backup.arrive_pct == recommend.arrive_pct(truck, 18) and backup.worst_pct == recommend.worst_pct(truck, 18)
    assert recommend.with_backup(truck, d, [], RULES) is d
    assert recommend.with_backup(truck, d, [replace(HOT_SPOT, miles=150)], RULES) is d


# The Love's to fill up at after a part fill: the one the stop told named (a message from before 2026-11-11, or a truck
# stop's), else the rules' own, which name none at a Love's any more.
def test_then_of():
    usual = UsualLevel(22, 15, 30, 95, 20)
    stops = [at(50, 7.45, 8.19, "Barstow"), at(220, 6.00, 6.69, "Havasu")]
    seen = recommend.picture(jacob(25, usual=usual), stops, FAR, RULES)
    assert recommend.then_of(None, seen) is None
    assert recommend.then_of(replace(TOLD, then_station="Love's Barstow, TX"), seen) == "150"
    assert recommend.then_of(TOLD, seen) is None


# What is kept of a message: the stop with its prices and place, the gauge, and the very words the driver gets.
def test_record():
    here = jacob(25, usual=UsualLevel(22, 15, 30, 95, 20))
    havasu = at(220, 6.00, 6.69, "Havasu")
    d = replace(recommend.decide(here, [at(50, 7.45, 8.19, "Barstow"), havasu], FAR, RULES), then=havasu)  # as a truck stop's has
    truck = Truck("340", "1", "V", "Unit 340", "Ali", 7.0, 25.0, NOV2, 30.0, -97.0, None, NOV2, 156.0, "manual", None, -100, "auto",
                  None, True)
    order = Order(7, "L-7", "in_transit", "340", NOV2, ())
    rec = message.record(truck, order, here, d, NOV2)
    assert (rec.unit, rec.driver, rec.order_id, rec.load_id, rec.made_at, rec.status) == ("340", "Ali", 7, "L-7", NOV2, "open")
    assert (rec.store_no, rec.station, rec.then_station) == ("150", "Love's Barstow, TX", "Love's Havasu, TX")
    assert (rec.net, rec.retail, rec.lat, rec.lng, rec.miles_ahead) == (7.45, 8.19, 30.0, -97.0, 50)
    assert round(rec.gauge_pct) == 25 and rec.gallons == d.gallons and rec.text == message.text(here, d)
    nowhere = message.record(truck, order, here, Decision("urgent", reason="low"), NOV2)
    assert (nowhere.store_no, nowhere.station, nowhere.net, nowhere.lat, nowhere.miles_ahead) == (None, None, None, None, None)


# A Love's off the road: `off_mi` from it, its miles counting the way there (as split_by_road gives them).
def off_road(mile: float, off_mi: float, net: float = 6.39, city: str = "Ingalls", no: str = "600") -> StoreOnRoute:
    store = Store(no, city, "IN", 39.99, -85.85, net + 0.41, net, "2026-11-05", "Love's")
    return StoreOnRoute(store=store, miles=mile + off_mi * 1.3, off_mi=off_mi)


# 540201 at Indianapolis, 2026-11-05: 21% of 182 gal, the next Love's on the road 172 mi on (out of reach in the worst
# case), Love's Ingalls 18 mi on and 8.3 mi off the road. A fill-up there, told as a short detour, not low fuel.
def test_detour_before_low_fuel():
    here = TruckNow(fuel_gal=0.21 * 182, mile=83.0, tank_gal=182, forecast_mpg=6.05, cautious_mpg=5.14,
                    usual=UsualLevel(38.5, 17.75, 51.5, 75, 26))
    road, ingalls = [at(83 + 172, 6.0, city="Springfield")], off_road(83 + 18, 8.3)
    assert recommend.decide(here, road, FAR, RULES).kind == "urgent"                        # before: low fuel
    d = recommend.decide(here, road, FAR, RULES, [ingalls])
    assert (d.kind, d.reason, d.stop.store.city) == ("stop", "detour", "Ingalls") and d.worst_pct > 15
    assert round(d.gallons) == round(0.75 * 182 - d.arrive_pct / 100 * 182)                # a fill-up to his level
    words = message.text(here, d)
    assert "📍 In 29 mi, about 8 mi off your road" in words and "short detour" in words and "Fuel is low" not in words
    assert recommend.told_stop(replace(TOLD, store_no="600"), road + [ingalls], LINE, 83.0, 2, 0.5) == ingalls  # stands


# A detour only when no Love's on the road is in reach, and only to one that is in reach itself.
def test_detour_only_when_needed():
    here = jacob(20, 0.0)
    near, far_off = off_road(10, 5), off_road(300, 5)
    assert recommend.decide(here, [at(60, 5.5)], FAR, RULES, [near]).stop.miles == 60      # one on the road: no detour
    assert recommend.decide(here, [], FAR, RULES, [far_off]).kind == "urgent"              # off the road, out of reach
    assert recommend.decide(here, [], 50.0, RULES, [near]).kind == "enough"                # the delivery is in reach
    gap = recommend.decide(jacob(60, 0.0), [], FAR, replace(RULES, look_mi=60), [off_road(500, 5)])
    assert (gap.kind, gap.reason) == ("watch", "no_loves")                                 # out of reach, fuel enough
    watch = recommend.decide(jacob(60, 0.0), [], FAR, replace(RULES, look_mi=60), [off_road(200, 5)])
    assert (watch.kind, watch.reason) == ("watch", "detour")                               # told once within 60 mi


# 14734 at Sonora TX, 2026-11-17: 80% of 153 gal, the next Love's on its road 844 mi on (out of reach), Love's
# Albuquerque 4 mi off the road ~605 mi on. No "last Love's" top-up at Sonora: it waits, and Albuquerque is told when
# close. Without Albuquerque, or with it reached under the reserve, Sonora is still the last Love's warning.
def test_no_top_up_warning_with_a_detour_later():
    def sean(pct: float, mile: float = 0.0) -> TruckNow:
        return TruckNow(fuel_gal=pct / 100 * 153, mile=mile, tank_gal=153, forecast_mpg=7.85, cautious_mpg=6.25,
                        usual=UsualLevel(15.5, 10, 20, 95, 12))
    road, albuquerque = [at(36, 5.07, city="Sonora"), at(844, 5.2, city="Cortez")], off_road(600, 4, city="Albuquerque")
    rules = replace(RULES, look_mi=60)
    d = recommend.decide(sean(80), road, FAR, rules, [albuquerque])
    assert (d.kind, d.reason, d.stop.store.city) == ("watch", "detour", "Albuquerque") and d.worst_pct >= 10
    past_sonora = recommend.decide(sean(80 - 100 * 40 / 7.85 / 153, 40), road, FAR, rules, [albuquerque])
    assert (past_sonora.kind, past_sonora.stop.store.city) == ("watch", "Albuquerque")      # nothing told yet
    close = recommend.decide(sean(80 - 100 * 560 / 7.85 / 153, 560), road, FAR, rules, [albuquerque])
    assert (close.kind, close.reason, close.stop.store.city) == ("stop", "detour", "Albuquerque")
    alone = recommend.decide(sean(80), road, FAR, rules)
    assert (alone.kind, alone.reason, alone.stop.store.city) == ("stop", "last", "Sonora")
    too_far = recommend.decide(sean(80), road, FAR, rules, [off_road(700, 4, city="Albuquerque")])  # 7% at worst
    assert (too_far.kind, too_far.reason, too_far.stop.store.city) == ("stop", "last", "Sonora")


# The Love's near the road split into those on it and those off it, the way there added, nearest first.
def test_split_by_road():
    on, off = at(50, 5.5), replace(at(40, 5.5), off_mi=8.0)
    road, detours = recommend.split_by_road([off, on, replace(at(45, 5.5), off_mi=2.0)], 1.5, 1.3)
    assert road == [on]
    assert [round(s.miles, 1) for s in detours] == [47.6, 50.4] and detours[0].off_mi == 2.0


# The plan drawn shows the detour chosen among the Love's, at its miles with the way there.
def test_picture_shows_the_detour():
    here = jacob(20, 0.0)
    seen = recommend.picture(here, [at(400, 5.5)], FAR, RULES, off_road=[off_road(30, 6), off_road(60, 6, city="Other", no="601")])
    assert seen.decision.reason == "detour"
    assert [v.stop.store.city for v in seen.views] == ["Ingalls", "Town"]                 # only the one chosen joins


# Parked: moved under a mile since then; on its way otherwise; can't tell (no track that far back): not parked.
def test_parked():
    from models import TrackPoint
    then = NOV2 - timedelta(minutes=20)
    track = [TrackPoint(then - timedelta(hours=1), 39.50, -87.38), TrackPoint(then, 39.507, -87.385)]
    assert recommend.parked(track, (39.5068, -87.3844), NOV2 - timedelta(minutes=15), 1.0)   # Terre Haute, 08:00 to 10:00
    assert not recommend.parked(track, (39.55, -86.73), NOV2 - timedelta(minutes=15), 1.0)   # on I-70 again
    assert not recommend.parked(track[1:], (39.507, -87.385), then - timedelta(minutes=1), 1.0)  # track too short


# A parked truck's fuel stop waits till it moves (540201 was told at 08:18 and passed it 3 h later, 2026-11-05); low
# fuel doesn't wait.
def test_quiet_while_parked():
    here = TruckNow(fuel_gal=60, mile=100.0, tank_gal=150, forecast_mpg=7.0, cautious_mpg=5.6, usual=UsualLevel(30, 20, 40, 95, 9))
    for reason, held in (("range", True), ("hard_stop", True), ("detour", True), ("tight", False), ("last", False)):
        d = Decision("stop", stop=at(150, 5.5), reason=reason)
        assert recommend.quiet(here, d, None, NOV2, RULES, parked=True) is held
        assert not recommend.quiet(here, d, None, NOV2, RULES, parked=False)
    # the last Love's in reach with the reserve kept is no low fuel yet: it waits like any stop; under it, it doesn't
    assert recommend.quiet(here, Decision("stop", stop=at(150, 5.5), worst_pct=15, reason="last"), None, NOV2, RULES, parked=True)
    assert not recommend.quiet(here, Decision("stop", stop=at(150, 5.5), worst_pct=8, reason="last"), None, NOV2, RULES, parked=True)
    assert not recommend.quiet(here, Decision("urgent", stop=at(150, 5.5), reason="low"), None, NOV2, RULES, parked=True)
