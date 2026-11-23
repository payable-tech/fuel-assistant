# Tests the no-load rule: a truck with no load is told the nearest Love's ahead in the direction it is going, once its
# fuel is down to the driver's usual level, and the stop told ends when it is behind the truck or out of reach.
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from base.models import Decision, FuelRules, Recommendation, Store, TrackPoint, TruckNow, UsualLevel
from features.engine import message, no_load, recommend

RULES = FuelRules(reserve_pct=10, worse=0.8, above_usual=1, look_mi=60, part_gap=0.50, part_reach_mi=500, part_min_gal=30,
                  part_margin_gal=25, low_penalty=5, urgent_pct=25, hold_min=60, near_mi=2, max_passed=2, last_pct=3)
USUAL = UsualLevel(usual_pct=22, low_pct=15, high_pct=30, fill_pct=95, stops=20)
AT = datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)
HERE = (35.0, -100.0)  # on I-40 in the Texas panhandle; a degree of longitude is about 57 mi here
FACTOR = 1.3


# A Love's at a point.
def loves(no: str, lat: float, lng: float, way: str | None = None) -> Store:
    return Store(no, "Town", "TX", lat, lng, 6.0, 5.5, "2026-11-18", way=way)


EAST_20 = loves("20", 35.0, -99.65, "I-40 (Exit 1)")  # ~20 mi east
EAST_80 = loves("80", 35.0, -98.6)                    # ~80 mi east
WEST_10 = loves("10", 35.0, -100.18)                  # behind a truck going east
NORTHEAST = loves("45", 35.3, -99.7)                  # ~40 degrees off the way east


# A truck with a 150-gal tank at 6.5 MPG, at a gauge level.
def truck(pct: float) -> TruckNow:
    return TruckNow(fuel_gal=pct / 100 * 150, mile=0.0, tank_gal=150, forecast_mpg=6.5, cautious_mpg=6.5 * 0.8, usual=USUAL)


# A GPS track ending at `end`, `miles_back` behind it to the west, a point every mile.
def track_east(end: tuple[float, float], miles_back: int) -> list[TrackPoint]:
    return [TrackPoint(AT - timedelta(minutes=k), end[0], end[1] - k / 57) for k in range(miles_back, -1, -1)]


# Its direction is where the last stretch of GPS goes; a truck that hardly moved has none.
def test_heading():
    assert round(no_load.heading(track_east(HERE, 30), HERE, 15)) == 90
    assert no_load.heading(track_east(HERE, 5), HERE, 15) is None


# Ahead: the Love's within the cone of its way, nearest first, the miles counting the way there; not behind, not wide.
def test_loves_ahead():
    found = no_load.loves_ahead(HERE, 90, [EAST_80, WEST_10, NORTHEAST, EAST_20], 30, FACTOR)
    assert [s.store.store_no for s in found] == ["20", "80"]
    assert round(found[0].miles) == round(20 * FACTOR)


# Above his usual level nothing is told; at it, the nearest Love's ahead, a fill-up; parked, it waits for the way.
def test_decide():
    ahead = no_load.loves_ahead(HERE, 90, [EAST_20, EAST_80], 30, FACTOR)
    assert no_load.decide(truck(40), 90, ahead, RULES).kind == "no load"
    assert no_load.decide(truck(20), None, ahead, RULES).kind == "no load, parked"
    d = no_load.decide(truck(20), 90, ahead, RULES)
    assert (d.kind, d.reason, d.stop.store.store_no) == ("stop", "no_load", "20")
    assert d.gallons == recommend.fill_up(truck(20), d.stop)


# The nearest ahead further than the telling distance is watched; out of reach, none ahead counts.
def test_decide_far_or_out_of_reach():
    far = no_load.loves_ahead(HERE, 90, [EAST_80], 30, FACTOR)
    assert no_load.decide(truck(20), 90, far, RULES).kind == "watch"
    assert no_load.decide(truck(4), 90, far, RULES).kind == "no load, no Love's ahead"
    assert no_load.decide(truck(20), 90, [], RULES).kind == "no load, no Love's ahead"


# The message: the usual fuel stop, with the miles as a rough count ahead, and the exit.
def test_message():
    d = no_load.decide(truck(20), 90, no_load.loves_ahead(HERE, 90, [EAST_20], 30, FACTOR), RULES)
    text = message.text(truck(20), d)
    assert text.startswith("⛽ Fuel stop: Love's Town, TX") and "📍 About 26 mi ahead, I-40 (Exit 1)" in text
    assert "🛢 Fill up" in text


# A stop told stands while ahead; once behind the truck (past it, or it turned around) it was passed; while parked it
# stands; once out of reach it is replaced.
def test_told_now():
    told = Recommendation(1, "340", None, 0, "", AT, "stop", "20", "Love's Town, TX", 26.0, 20.0, 17.0, 15.0, 110.0, None,
                          "no_load", 5.5, 6.0, "2026-11-18", 6.5, 5.2, 22.0, "x", "open", None, lat=35.0, lng=-99.65)
    before, past = (35.0, -99.8), (35.0, -99.5)
    assert no_load.told_now(told, before, 90, truck(20), RULES, FACTOR) is None
    assert no_load.told_now(told, past, 90, truck(20), RULES, FACTOR) == "passed"
    assert no_load.told_now(told, before, 270, truck(20), RULES, FACTOR) == "passed"  # turned around
    assert no_load.told_now(told, past, None, truck(20), RULES, FACTOR) is None       # parked: its way isn't known
    assert no_load.told_now(told, before, 90, truck(1), RULES, FACTOR) == "replaced"


# Like any plain stop, it isn't told again after two passed on this tank; under the reserve it is told anyway.
def test_held_after_two_passed_unless_low():
    d = no_load.decide(truck(20), 90, no_load.loves_ahead(HERE, 90, [EAST_20], 30, FACTOR), RULES)
    assert not recommend.quiet(truck(20), d, None, AT, RULES, passed=1)
    assert recommend.quiet(truck(20), d, None, AT, RULES, passed=2)
    low = replace(d, worst_pct=8.0)
    assert not recommend.quiet(truck(20), low, None, AT, RULES, passed=2)


# Its way counts only the miles driven lately: a truck that drove in from the west hours ago and has just left going back
# west has no way yet (the old miles would say east).
def test_heading_ignores_the_miles_before_a_stop():
    came = [TrackPoint(AT - timedelta(hours=3, minutes=k), HERE[0], HERE[1] - k / 57) for k in range(30, -1, -1)]
    left = [TrackPoint(AT - timedelta(minutes=k), HERE[0], HERE[1] - (3 - k) / 57) for k in range(3, -1, -1)]
    now_at = (left[-1].lat, left[-1].lng)
    assert round(no_load.heading(came + left, now_at, 10)) == 90                   # with no limit: east, the wrong way
    assert no_load.heading(came + left, now_at, 10, AT - timedelta(minutes=30)) is None


# When the truck last set off after a stop: the newest point of the last stretch it stayed near for the stop's length;
# a truck that kept driving made no stop.
def test_set_off_after_a_stop():
    stop_at = [TrackPoint(AT - timedelta(minutes=40 - k), HERE[0], HERE[1]) for k in range(0, 21)]       # 20 min still
    drive = [TrackPoint(AT - timedelta(minutes=19 - k), HERE[0], HERE[1] + (k + 1) / 57) for k in range(20)]
    assert no_load.set_off(stop_at + drive, 1, timedelta(minutes=15)) == AT - timedelta(minutes=20)
    assert no_load.set_off(track_east(HERE, 60), 1, timedelta(minutes=15)) is None
    assert no_load.set_off([], 1, timedelta(minutes=15)) is None
