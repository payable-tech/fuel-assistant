# Tests the database rules: your values beat synced and helper values, survive re-syncs, and gaps show in `holes`.
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import config
import db

from models import (BurnFactor, DatatruckDriver, DatatruckTruck, FuelLine, FuelStop, Order, Recommendation, Region, SamsaraLive, TruckWatch,
                    Stop, Store, SyncedTruck, TankEstimate, TelegramGroup, FillLookup)


# Points the database at a temporary file so tests never touch data/fuel.db.
@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")


# Builds a synced truck with fixed test values; only the unit and auto chat vary.
def synced(unit: str, auto_chat_id: int | None = None) -> SyncedTruck:
    return SyncedTruck(unit=unit, samsara_id=f"s-{unit}", vin=f"VIN{unit}", name=f"Unit {unit}",
                       mpg=7.0, auto_chat_id=auto_chat_id, chat_note=None if auto_chat_id else "no group")


# Writes a full sync of the given trucks.
def sync(*trucks: SyncedTruck) -> None:
    with db.connect() as conn:
        db.replace_trucks(conn, list(trucks))


# Returns the fleet as {unit: Truck}.
def fleet() -> dict:
    with db.connect() as conn:
        return {t.unit: t for t in db.fleet(conn)}


# Puts linked trucks in the pilot.
def join_pilot(*units: str) -> None:
    with db.connect() as conn:
        for unit in units:
            db.add_pilot(conn, unit, None)


# With no manual setting, the auto-matched chat is used.
def test_auto_chat_used():
    sync(synced("340", auto_chat_id=-100))
    assert (fleet()["340"].chat_id, fleet()["340"].chat_source) == (-100, "auto")


# A manual chat wins over the auto-matched one.
def test_manual_chat_wins():
    sync(synced("340", auto_chat_id=-100))
    join_pilot("340")
    with db.connect() as conn:
        db.set_chat(conn, "340", -200)
    assert (fleet()["340"].chat_id, fleet()["340"].chat_source) == (-200, "manual")


# Clearing the manual chat falls back to the auto-match.
def test_clearing_manual_falls_back_to_auto():
    sync(synced("340", auto_chat_id=-100))
    join_pilot("340")
    with db.connect() as conn:
        db.set_chat(conn, "340", -200)
        db.set_chat(conn, "340", None)
    assert (fleet()["340"].chat_id, fleet()["340"].chat_source) == (-100, "auto")


# A truck with neither link shows as unlinked, with the reason.
def test_unlinked_truck():
    sync(synced("340"))
    truck = fleet()["340"]
    assert (truck.chat_id, truck.chat_source, truck.chat_note) == (None, None, "no group")


# A re-sync replaces synced data but keeps the pilot list and your chat and tank values.
def test_resync_keeps_manual_settings():
    sync(synced("340", auto_chat_id=-100))
    join_pilot("340")
    with db.connect() as conn:
        db.set_chat(conn, "340", -200)
        db.set_tank(conn, "340", 250)
    sync(synced("340", auto_chat_id=-999))
    truck = fleet()["340"]
    assert (truck.pilot, truck.chat_id, truck.chat_source, truck.tank_gal) == (True, -200, "manual", 250)


# The tank helper's estimate is used until you set a tank size; yours wins, and clearing it brings the estimate back.
def test_manual_tank_beats_estimate():
    sync(synced("340"))
    join_pilot("340")
    with db.connect() as conn:
        db.replace_tank_estimates(conn, [TankEstimate(unit="340", tank_gal=151, fills=14)])
    assert (fleet()["340"].tank_gal, fleet()["340"].tank_source, fleet()["340"].tank_fills) == (151, "auto", 14)
    with db.connect() as conn:
        db.set_tank(conn, "340", 180)
    assert (fleet()["340"].tank_gal, fleet()["340"].tank_source) == (180, "manual")
    with db.connect() as conn:
        db.set_tank(conn, "340", None)
    assert (fleet()["340"].tank_gal, fleet()["340"].tank_source) == (151, "auto")


# A truck's row carries its latest Samsara reading and its active drivers (a team shows both names).
def test_fleet_row_has_live_reading_and_drivers():
    sync(synced("340"))
    at = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    with db.connect() as conn:
        db.replace_samsara_live(conn, [SamsaraLive("s-340", 32.7, -96.8, "Dallas, TX", at, 45, at)])
        db.replace_dt_drivers(conn, [DatatruckDriver(1, "Ali", "lease", "active", "TTL", "340"),
                                     DatatruckDriver(2, "Bek", "lease", "active", "TTL", "340"),
                                     DatatruckDriver(3, "Old", "lease", "inactive", "TTL", "340")])
    truck = fleet()["340"]
    assert (truck.fuel_pct, truck.fuel_at, truck.place, truck.pilot) == (45, at, "Dallas, TX", False)
    assert sorted(truck.driver.split(" & ")) == ["Ali", "Bek"]


# Only linked trucks can join the pilot, and only pilot trucks take your tank and chat values.
def test_pilot_values_need_a_pilot_truck():
    sync(synced("340"))
    with db.connect() as conn, pytest.raises(LookupError):
        db.add_pilot(conn, "34O", None)
    with db.connect() as conn, pytest.raises(LookupError):
        db.set_tank(conn, "340", 150)


# A pilot truck is found by its unit; a truck outside the pilot, or no truck at all, is not.
def test_pilot_truck():
    sync(synced("340"), synced("341"))
    join_pilot("340")
    with db.connect() as conn:
        assert db.pilot_truck(conn, "340").unit == "340"
        assert db.pilot_truck(conn, "341") is None and db.pilot_truck(conn, "999") is None


# Removing a truck from the pilot drops it and your values for it; removing it twice fails loudly.
def test_remove_pilot():
    sync(synced("340"))
    join_pilot("340")
    with db.connect() as conn:
        db.set_tank(conn, "340", 150)
        db.remove_pilot(conn, "340")
    assert (fleet()["340"].pilot, fleet()["340"].tank_gal) == (False, None)
    with db.connect() as conn, pytest.raises(LookupError):
        db.remove_pilot(conn, "340")


# A pilot truck missing a tank size, a Telegram group or a fuel reading is listed in `holes`; other trucks are not.
def test_pilot_holes():
    sync(synced("340"), synced("717"))
    join_pilot("340")
    with db.connect() as conn:
        found = {(h["hole"], h["item"]) for h in db.holes(conn) if h["hole"].startswith("Pilot")}
    assert {item for _, item in found} == {"340"} and len(found) == 3


# Trucks missing from a new sync disappear from the fleet.
def test_resync_drops_removed_trucks():
    sync(synced("340"), synced("717"))
    sync(synced("717"))
    assert list(fleet()) == ["717"]


# The holes view lists a Datatruck truck with no Samsara match and a Telegram group no truck uses.
def test_holes_lists_unlinked_items():
    with db.connect() as conn:
        db.replace_dt_trucks(conn, [DatatruckTruck(dt_id=1, unit="717", vin="VIN717", status="available", ownership="company")])
        db.replace_tg_groups(conn, [TelegramGroup(chat_id=-5, title="Unit 999")])
        found = {(h["hole"], h["item"]) for h in db.holes(conn)}
    assert ("Datatruck: truck without Samsara vehicle", "717") in found
    assert ("Telegram: group without truck", "Unit 999") in found


# Group search finds titles containing the text in any case, sorted by title.
def test_find_groups():
    with db.connect() as conn:
        db.replace_tg_groups(conn, [TelegramGroup(-2, "TTL: Ali | Unit 1756"), TelegramGroup(-1, "**INACTIVE** Unit 1756"),
                                    TelegramGroup(-3, "Unit 717")])
        assert [g.chat_id for g in db.find_groups(conn, "1756")] == [-1, -2]
        assert [g.chat_id for g in db.find_groups(conn, "ttl: ali")] == [-2]


# A schema change drops and rebuilds the refreshed tables, but your pilot list and values survive it.
def test_schema_change_keeps_manual_settings():
    sync(synced("340"))
    join_pilot("340")
    with db.connect() as conn:
        db.set_tank(conn, "340", 180)
        conn.execute("PRAGMA user_version = 1")  # pretend the file was made by an older version
    db._schema_ready.discard(str(config.DB_PATH))  # the check runs at program start; act like a fresh start
    with db.connect() as conn:
        assert db.fleet(conn) == []  # trucks were dropped, to be refilled by sync
        assert conn.execute("SELECT tank_gal FROM pilot_trucks WHERE unit = '340'").fetchone()[0] == 180


# Price sheets build a history (a store's price for a day already there is replaced), and the sheet with the newest
# price date is the newest, whatever order the files were read in. A day's network discount averages every store.
def test_price_history():
    def sheet(day, net):
        return [Store("1", "Town", "TX", 30.0, -97.0, net + 0.5, net, day), Store("2", "Town", "OK", 35.0, -97.0, net, net, day)]
    with db.connect() as conn:
        db.add_price_sheet(conn, "new.xlsx", 10, 2.0, sheet("2026-10-20", 5.0))
        db.add_price_sheet(conn, "old.xlsx", 10, 3.0, sheet("2026-10-14", 5.5))
        db.add_price_sheet(conn, "old.xlsx", 10, 3.0, sheet("2026-10-14", 5.4))
        assert db.newest_price_file(conn) == "new.xlsx"
        assert db.price_files(conn)["old.xlsx"] == (10, 3.0)
        assert tuple(conn.execute("SELECT COUNT(*), MIN(net) FROM price_history WHERE price_date = '2026-10-14'").fetchone()) == (2, 5.4)
        assert db.network_discounts(conn, "2026-10-15") == {"2026-10-20": 0.25}  # (0.50 + 0.00) / 2 stores
        assert db.price_sheets(conn, "2026-10-15") == {"2026-10-20": {"1": 5.0, "2": 5.0}}
        db.replace_stores(conn, sheet("2026-10-20", 5.0))  # the newest sheet becomes the stores, read back as they went in
        assert sorted(db.stores(conn), key=lambda s: s.store_no) == sheet("2026-10-20", 5.0)


# The test trucks' fills come back as they went in, by fuel line id (a fill with nothing known still counts as done).
def test_fill_lookups_round_trip():
    fills = [FillLookup(7, 35.1, -97.2, 18.0), FillLookup(8, None, None, None)]
    with db.connect() as conn:
        db.add_fill_lookups(conn, fills)
        assert db.fill_lookups(conn) == {7: fills[0], 8: fills[1]}


# Fuel stops come back as they went in, with times as datetimes and Love's as a real true/false.
def test_fuel_stops_round_trip():
    s = FuelStop(7, "Ali", "340", datetime(2026, 10, 19, 12, tzinfo=timezone.utc), 120.0, 660.0, True, "TX", 18.0, 96.0)
    with db.connect() as conn:
        db.replace_fuel_stops(conn, [s])
        assert db.fuel_stops(conn) == [s]


# Active orders come back from the database as they went in, stops in route order.
def test_orders_round_trip():
    stops = (Stop(11, 1, 1, "pickup", 32.7, -96.8, "Dallas", "TX"), Stop(12, 1, 2, "delivery", None, None, "Atlanta", "GA"))
    order = Order(1, "L-1", "in_transit", "340", datetime(2026, 10, 19, 12, tzinfo=timezone.utc), stops)
    with db.connect() as conn:
        db.replace_orders(conn, [order])
        assert db.orders(conn) == [order]


# Many threads opening a brand-new database at once (the dashboard's parallel requests plus the scheduler)
# all succeed: the tables and views are set up once, not raced.
def test_parallel_first_connections():
    errors = []

    # Opens the database and reads from it, keeping any error for the test to see.
    def open_and_read():
        try:
            with db.connect() as conn:
                db.status(conn)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=open_and_read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# A recent refresh replaces only the lines from its first day on; older lines are left alone.
def test_replace_fuel_lines_since():
    old = FuelLine(1, "2026-10-10 08:00", "fuel", "ULSD", 100.0, 560.0, 500.0, 0.0, True, "LOVES #1", "", "TX", "TTL",
                   "340", "company", 7, "", "lease", None)
    recent = FuelLine(2, "2026-10-18 08:00", "fuel", "ULSD", 50.0, 280.0, 250.0, 0.0, True, "LOVES #1", "", "TX", "TTL",
                      "340", "company", 7, "", "lease", None)
    updated = FuelLine(2, "2026-10-18 08:00", "fuel", "ULSD", 55.0, 300.0, 270.0, 0.0, True, "LOVES #1", "", "TX", "TTL",
                       "340", "company", 7, "", "lease", None)
    with db.connect() as conn:
        db.replace_fuel_lines(conn, [old, recent])
        db.replace_fuel_lines_since(conn, "2026-10-16", [updated])
        assert db.fuel_lines(conn, since_day="2026-01-01") == [old, updated]


# Fuel lines come back from the database as they went in, billable as a real true/false.
def test_fuel_lines_round_trip():
    f = FuelLine(line_id=1, fueled_at="2026-10-13 10:00", transaction_type="fuel", product="ULSD", gallons=100.0,
                 pump_total=560.0, billed=500.0, fee=0.0, billable=True, location="LOVES #1", city="", state="TX",
                 company="TTL", unit="340", truck_ownership="company", driver_id=7, driver_name="", driver_type="lease",
                 card_id=None)
    with db.connect() as conn:
        db.replace_fuel_lines(conn, [f])
        assert db.fuel_lines(conn, since_day="2026-10-01") == [f]
        assert db.fuel_lines(conn, since_day="2026-10-14") == []


# A truck's look comes back as saved, road and regions included; saving again replaces it.
def test_truck_watch_round_trip():
    at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    look = TruckWatch(unit="340", at=at, state="watch", order_id=1, load_id="L", road_made_at=at, line=[(30.0, -97.0), (31.0, -97.0)],
                      route_mi=69.0, mile=10.0, fuel_pct=50.0, regions=(Region(10.0, 40.0, 2, "Love's Town, TX", True),))
    with db.connect() as conn:
        assert db.truck_watch(conn, "340") is None
        db.save_truck_watch(conn, look)
        assert db.truck_watch(conn, "340") == look
        db.save_truck_watch(conn, TruckWatch(unit="340", at=at, state="no load"))
        assert db.truck_watch(conn, "340").state == "no load" and len(db.truck_watches(conn)) == 1


# A recommendation stays open until settled, and is listed with what became of it.
def test_recommendations():
    at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    rec = Recommendation(None, "340", "Ali", 1, "L", at, "stop", "412", "Love's Dunn, NC", 109.0, 30.0, 20.0, 17.0, 130.0, None, "hard_stop",
                         5.25, 5.69, "2026-10-19", 6.69, 5.35, 13.0, "text", "open", None)
    with db.connect() as conn:
        db.add_recommendation(conn, rec)
        told = db.open_recommendation(conn, "340")
        assert told.station == "Love's Dunn, NC" and told.made_at == at
        db.settle_recommendation(conn, told.rec_id, "passed", at)
        assert db.open_recommendation(conn, "340") is None
        assert db.recommendations(conn, "2026-10-19")[0].status == "passed"


# The stops a truck drove past are counted from a moment on: not earlier ones, an emergency, a stop fueled at, or
# another truck's.
def test_passed_stops():
    at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    rec = Recommendation(None, "340", "Ali", 1, "L", at, "stop", "412", "Love's Dunn, NC", 109.0, 30.0, 20.0, 17.0, 130.0, None, "range",
                         5.25, 5.69, "2026-10-19", 6.69, 5.35, 13.0, "text", "passed", None)
    with db.connect() as conn:
        for hours, change in ((0, {}), (1, {}), (2, {}), (3, {"kind": "urgent"}), (4, {"status": "fueled"}), (5, {"unit": "341"})):
            db.add_recommendation(conn, replace(rec, made_at=at + timedelta(hours=hours), **change))
        assert db.passed_stops(conn, "340", at - timedelta(hours=1)) == 3
        assert db.passed_stops(conn, "340", at) == 2
        assert db.passed_stops(conn, "340", at + timedelta(hours=2)) == 0


# The engine factors are read back by unit.
def test_burn_factors():
    with db.connect() as conn:
        db.replace_burn_factors(conn, [BurnFactor("340", 1e-7, 4)])
        assert db.burn_factors(conn) == {"340": 1e-7}
