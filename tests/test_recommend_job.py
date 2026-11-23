# Tests that recommendations reach the driver only on live trucks, and the test group always.
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from base import config
from base.models import Decision, FuelLine, Order, Recommendation, Stop, SyncedTruck, Trip, Truck, TruckWatch
from base.store import db
from features.engine import job, message

TEST_GROUP = -5383830098
AT = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
REC = Recommendation(1, "340", "Ali", 1, "L-1", AT, "stop", "7", "Love's Near, TX", 34.0, 20.0, 18.0, 17.0, 30.0, None, "range",
                     5.5, 6.0, "2026-11-02", 7.0, 5.6, 20.0, "Fill up at Love's Near, TX", "open", None)


# Every send is caught, so a test never reaches Telegram.
@pytest.fixture
def sent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "TEST_CHAT_ID", TEST_GROUP)
    monkeypatch.setattr(job.telegram, "send", lambda chat, text: calls.append((chat, text)))
    return calls


# A truck failing on the network gets one log line, a fault in the code its full trace; every truck ticks the watchdog.
def test_failures_are_logged_and_each_truck_ticks(sent, monkeypatch, caplog):
    failures = iter([httpx.ConnectError("getaddrinfo failed"), ValueError("a fault")])

    # Stands in for one truck's look: fails with the next failure.
    def look(*args):
        raise next(failures)

    ticks = []
    monkeypatch.setattr(job.db, "pilot", lambda conn: [SimpleNamespace(unit="340"), SimpleNamespace(unit="341")])
    monkeypatch.setattr(job, "_look", look)
    monkeypatch.setattr(job.watchdog, "tick", lambda: ticks.append(1))
    assert job.run() == 2
    network, fault = [r for r in caplog.records if r.name == "features.engine.job"]
    assert network.exc_info is None and "unit 340" in network.getMessage() and "ConnectError" in network.getMessage()
    assert fault.exc_info is not None and "unit 341" in fault.getMessage()
    assert len(ticks) == 2


# It goes to the test group, naming the truck above the driver's own words.
def test_copy_goes_to_the_test_group(sent):
    job.copy_to_test_group(REC)
    assert len(sent) == 1 and sent[0][0] == TEST_GROUP
    assert "Unit 340" in sent[0][1] and sent[0][1].endswith("Fill up at Love's Near, TX")


# The message as built goes under the truck's line, untouched.
def test_copy_carries_the_message(sent):
    job.copy_to_test_group(REC, '<a href="https://x">Love\'s Near, TX</a>')
    assert sent[0][1].endswith('<a href="https://x">Love\'s Near, TX</a>')


# With no test group set, nothing is sent.
def test_no_test_group_no_send(sent, monkeypatch):
    monkeypatch.setattr(config, "TEST_CHAT_ID", None)
    job.copy_to_test_group(REC)
    assert sent == []


# If that chat is ever a truck's own group, nothing is sent: a driver must not get these.
def test_refuses_a_trucks_own_group(sent):
    with db.connect() as conn:
        db.replace_trucks(conn, [SyncedTruck("340", "1", "V", "Unit 340", 7.0, TEST_GROUP, None)])
    job.copy_to_test_group(REC)
    assert sent == []


# A failed send doesn't stop anything.
def test_failed_send_is_only_logged(sent, monkeypatch):
    def fail(chat, text):
        raise RuntimeError("Telegram down")

    monkeypatch.setattr(job.telegram, "send", fail)
    job.copy_to_test_group(REC)


# The words for the group keep the driver's message whole.
def test_the_copy_keeps_the_message():
    assert message.test_copy(REC, None).split("--------\n")[1] == REC.text


# Telegram's HTML can't break on what a driver's name or a station holds.
def test_the_copy_is_safe_html():
    rec = replace(REC, driver="A & B", text="Love's <Near> & Far")
    assert "A &amp; B" in message.test_copy(rec, None) and "Love's &lt;Near&gt; &amp; Far" in message.test_copy(rec, None)


def truck(unit: str, chat: int | None) -> Truck:
    return Truck(unit, "1", "V", f"Unit {unit}", "Ali", 7.0, 30.0, AT, 30.0, -97.0, None, AT, 160.0, "manual", None, chat, "auto", None, True)


# A live truck's driver gets the message in their own group.
def test_live_truck_gets_it(sent, monkeypatch):
    monkeypatch.setattr(config, "LIVE_UNITS", ("340",))
    assert job.send_to_driver(truck("340", -100), "Fill up") and sent == [(-100, "Fill up")]


# Any other truck, a truck without a group, or a group that is the test group: nothing goes out.
def test_not_live_or_no_group_no_send(sent, monkeypatch):
    monkeypatch.setattr(config, "LIVE_UNITS", ("340",))
    assert not job.send_to_driver(truck("341", -100), "x")
    assert not job.send_to_driver(truck("340", None), "x")
    assert not job.send_to_driver(truck("340", TEST_GROUP), "x")
    assert sent == []


# A failed send to the driver is reported as not sent, not raised.
def test_failed_driver_send_is_not_sent(sent, monkeypatch):
    monkeypatch.setattr(config, "LIVE_UNITS", ("340",))
    monkeypatch.setattr(job.telegram, "send", lambda chat, text: (_ for _ in ()).throw(RuntimeError("Telegram down")))
    assert not job.send_to_driver(truck("340", -100), "x")


# The test group sees which messages the driver really got.
def test_the_copy_says_if_sent():
    assert message.test_copy(REC, None).startswith("🧪 Test")
    assert message.test_copy(replace(REC, sent_at=AT), None).startswith("📨 Sent to the driver")


# A recommendation keeps when it was sent.
def test_sent_is_recorded(sent):
    with db.connect() as conn:
        rec_id = db.add_recommendation(conn, replace(REC, rec_id=None))
        db.mark_sent(conn, rec_id, AT)
        assert db.recommendations(conn, "2026-11-01")[0].sent_at == AT


# A road for the truck's road tests: the truck sits on it, the load's stops at its end.
def on_road(stops, monkeypatch, saved_stops, now=AT):
    calls = []
    monkeypatch.setattr(job.google, "route", lambda points: calls.append(points) or [points[0], points[-1]])
    order = Order(7, "L-7", "in_transit", "340", AT, tuple(Stop(i, 7, i, "delivery", lat, lng, "X", "TX") for i, (lat, lng) in enumerate(stops)))
    last = TruckWatch(unit="340", at=AT, state="watch", order_id=7, road_made_at=AT, line=[(30.0, -97.0), (29.8, -95.4)],
                      mile=0.0, road_stops=saved_stops)
    road = job._road(truck("340", -100), order, list(order.stops), last, now)
    return road, calls


# The same stops: the road is kept, no new Google call.
def test_road_kept_while_stops_same(monkeypatch):
    road, calls = on_road([(29.8, -95.4)], monkeypatch, ((29.8, -95.4),))
    assert calls == [] and road.made_at == AT and not road.new


# The delivery moved in Datatruck: a new road from the truck to the new place, made now.
def test_new_road_when_stops_change(monkeypatch):
    later = AT.replace(hour=13)
    road, calls = on_road([(32.7, -96.8)], monkeypatch, ((29.8, -95.4),), later)
    assert calls == [[(30.0, -97.0), (32.7, -96.8)]] and (road.made_at, road.mile, road.stops, road.new) == (later, 0.0, ((32.7, -96.8),), True)


# A road saved before its stops were kept isn't remade for that alone.
def test_old_road_without_stops_kept(monkeypatch):
    road, calls = on_road([(29.8, -95.4)], monkeypatch, ())
    assert calls == [] and road.stops == ((29.8, -95.4),)


# With the low-fuel message switched off, an emergency is only the truck's state: nothing is sent or recorded.
def test_low_fuel_alarm_off_tells_nothing(sent, monkeypatch):
    monkeypatch.setattr(config, "LOW_FUEL_ALARM", False)
    monkeypatch.setattr(config, "LIVE_UNITS", ("340",))
    state = job._act(truck("340", -100), None, [], None, Decision("urgent", reason="low"), [], None, False, [], AT)
    with db.connect() as conn:
        assert state == "urgent" and sent == [] and db.recommendations(conn, "2026-11-01") == []


# A recommendation keeps where its stop is.
def test_stop_place_is_recorded(sent):
    with db.connect() as conn:
        db.add_recommendation(conn, replace(REC, rec_id=None, lat=30.5, lng=-97.0))
        rec = db.recommendations(conn, "2026-11-01")[0]
    assert (rec.lat, rec.lng) == (30.5, -97.0)


# The stops driven past count for this tank only: those told since the last fill-up, by the gauge or by a purchase.
def test_passed_counts_since_the_last_fill(sent):
    def line(when: str) -> FuelLine:
        return FuelLine(1, when, "fuel", "ULSD", 100.0, 600.0, 550.0, 0.0, False, "LOVES #7 TRAVEL STOP", "Near", "TX", "TTL", "340",
                        "company", 7, "Ali", "company", None)

    with db.connect() as conn:
        for hours in (5, 3, 1):  # told 5, 3 and 1 hours ago, each driven past
            db.add_recommendation(conn, replace(REC, rec_id=None, made_at=AT - timedelta(hours=hours), status="passed"))
    assert job._passed(truck("340", -100), None, [], AT) == 3
    assert job._passed(truck("340", -100), AT - timedelta(hours=4), [], AT) == 2      # the gauge saw a fill 4 hours ago
    assert job._passed(truck("340", -100), None, [line("2026-11-02 04:00")], AT) == 1  # bought 04:00 Central, 2 hours ago
    assert job._passed(truck("340", -100), None, [], AT + timedelta(days=4)) == 0      # too long ago to be this tank


# A look that can't judge the fuel (no fresh gauge) keeps the level the last full look judged by, not Samsara's newest
# reading, so a fill-up in between is seen as a rise at the next full look (4482 at Joplin, 2026-11-11). A full look
# saves its own level; a truck never looked at starts from Samsara's reading.
def test_stale_look_keeps_the_level_judged_by(sent):
    full_tank = replace(truck("340", -100), fuel_pct=98.0)  # Samsara's newest reading, delivered late
    last = TruckWatch(unit="340", at=AT, state="told", fuel_pct=16.0)
    job._save(full_tank, "no fresh gauge", last, AT + timedelta(minutes=5))
    with db.connect() as conn:
        kept = db.truck_watch(conn, "340")
    assert (kept.state, kept.fuel_pct) == ("no fresh gauge", 16.0)
    assert job._filling(kept, 98.0)  # the next full look sees the fill
    job._save(full_tank, "enough", kept, AT + timedelta(minutes=10), 98.0)
    job._save(full_tank, "no load", None, AT, None)
    with db.connect() as conn:
        assert db.truck_watch(conn, "340").fuel_pct == 98.0


# A truck's look keeps when it last fueled.
def test_look_keeps_fueled_at(sent):
    with db.connect() as conn:
        db.save_truck_watch(conn, TruckWatch(unit="340", at=AT, state="watch", fueled_at=AT))
        assert db.truck_watch(conn, "340").fueled_at == AT


# A trip starts at its first look and keeps that start; later looks move its end, and keep the road unless a new one comes.
def test_trip_is_kept(sent):
    trip = Trip("340", 7, "L-7", (("pickup", "Dallas", "TX", 32.7, -96.8),), AT, AT, [(32.7, -96.8), (33.7, -84.4)])
    later = AT + timedelta(hours=3)
    with db.connect() as conn:
        db.save_trip(conn, trip)
        db.save_trip(conn, replace(trip, started_at=later, ended_at=later, line=None))
        kept = db.trips(conn, "340", "2026-11-01")
    assert len(kept) == 1 and kept[0].started_at == AT and kept[0].ended_at == later
    assert kept[0].line == [(32.7, -96.8), (33.7, -84.4)] and kept[0].stops == (("pickup", "Dallas", "TX", 32.7, -96.8),)


# A saved look holding a field the code has since dropped still loads (or every look of the engine would fail quietly).
def test_old_look_still_loads(sent):
    import json
    with db.connect() as conn:
        db.save_truck_watch(conn, TruckWatch(unit="340", at=AT, state="watch"))
        look = json.loads(conn.execute("SELECT look FROM truck_watch").fetchone()[0])
        conn.execute("UPDATE truck_watch SET look = ?", (json.dumps(look | {"gone_field": 1}),))
        assert db.truck_watch(conn, "340").state == "watch"


# The GPS is kept between looks: the first fetches from `since`, later ones only after the last point kept; a look that
# needs an earlier start fetches it whole again; points before `since` drop off (2026-11-05: looks took minutes).
def test_track_kept_between_looks(monkeypatch):
    from base.models import TrackPoint
    calls = []

    def fetch(samsara_id, start, end):
        calls.append(start)
        return [TrackPoint(start + timedelta(minutes=10 * k), 30.0 + 0.01 * k, -97.0) for k in range(int((end - start).total_seconds() // 600) + 1)]

    monkeypatch.setattr(job.samsara, "gps_history", fetch)
    monkeypatch.setattr(job, "_tracks", {})
    t = truck("340", -100)
    first = job._track(t, AT - timedelta(hours=2), AT)
    later = job._track(t, AT - timedelta(hours=1), AT + timedelta(minutes=30))
    assert calls == [AT - timedelta(hours=2), first[-1].at]                     # the second look fetched only what's new
    assert later[0].at >= AT - timedelta(hours=1) and later[-1].at == AT + timedelta(minutes=30)
    job._track(t, AT - timedelta(hours=5), AT + timedelta(minutes=30))
    assert calls[-1] == AT - timedelta(hours=5)                                 # an earlier start: fetched whole again


# A truck with no load, its gauge at the driver's usual level, driving east: the nearest Love's east is told to its
# driver and kept under no load; the next look finds it told; once the truck is past it, it was passed.
def test_no_load_truck_is_told_the_loves_ahead(sent, monkeypatch):
    from base.models import NO_LOAD_ORDER, Store, TrackPoint
    monkeypatch.setattr(config, "LIVE_UNITS", ("340",))
    monkeypatch.setattr(job, "_steady_fuel", lambda truck, now: truck.fuel_pct)
    east = Store("7", "Seguin", "TX", 30.0, -96.7, 6.0, 5.5, "2026-11-18", way="I-10 (Exit 610)")
    west = Store("8", "Columbus", "TX", 30.0, -97.4, 6.0, 5.5, "2026-11-18")

    # The truck at a longitude at a moment, having driven east along latitude 30 for the hour before (a point a minute).
    def look(lng: float, at: datetime) -> tuple[Truck, list[TrackPoint]]:
        here = replace(truck("340", -100), fuel_pct=20.0, fuel_at=at, lng=lng)
        return here, [TrackPoint(at - timedelta(minutes=k), 30.0, lng - k / 60 * 60 / 58) for k in range(60, -1, -1)]

    t, track = look(-97.0, AT)
    job._no_load(t, track, [east, west], None, None, None, [], AT)
    with db.connect() as conn:
        rec = db.open_recommendation(conn, "340")
        state = db.truck_watch(conn, "340").state
    assert (state, rec.order_id, rec.load_id, rec.store_no, rec.reason) == ("stop", NO_LOAD_ORDER, "", "7", "no_load")
    assert rec.sent_at is not None and [chat for chat, _ in sent] == [-100, TEST_GROUP]
    assert "About" in sent[0][1] and "I-10 (Exit 610)" in sent[0][1] and "destination=30.00000,-96.70000" in sent[0][1]

    later = AT + timedelta(minutes=5)
    t, track = look(-96.9, later)
    with db.connect() as conn:
        last = db.truck_watch(conn, "340")
    job._no_load(t, track, [east, west], None, rec, last, [], later)
    with db.connect() as conn:
        assert db.truck_watch(conn, "340").state == "told" and len(sent) == 2

    past = AT + timedelta(minutes=30)
    t, track = look(-96.6, past)
    job._no_load(t, track, [east, west], None, rec, last, [], past)
    with db.connect() as conn:
        assert db.recommendations(conn, "2026-11-01")[0].status == "passed"
        assert db.truck_watch(conn, "340").state == "no load, no Love's ahead"


# A stop told on a load ends with that load once the truck has none; a parked truck at its level waits for its way.
def test_no_load_ends_a_loads_stop_and_waits_while_parked(sent, monkeypatch):
    from base.models import TrackPoint
    monkeypatch.setattr(job, "_steady_fuel", lambda truck, now: truck.fuel_pct)
    with db.connect() as conn:
        db.add_recommendation(conn, replace(REC, rec_id=None))
        told = db.open_recommendation(conn, "340")
    t = replace(truck("340", -100), fuel_pct=20.0)
    parked = [TrackPoint(AT - timedelta(minutes=k), 30.0, -97.0) for k in range(60, -1, -1)]
    job._no_load(t, parked, [], None, told, None, [], AT)
    with db.connect() as conn:
        assert db.recommendations(conn, "2026-11-01")[0].status == "load ended"
        assert db.truck_watch(conn, "340").state == "no load, parked" and sent == []
