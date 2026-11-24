# Tests the Recommend view's numbers: a truck's plan to draw, with and without a road, and a stop told earlier standing.
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from base import config
from base.models import FuelLine, Recommendation, Region, Store, SyncedTruck, TruckWatch, UsualLevel
from base.store import db
from features.dashboard import dashboard, settings as dashboard_settings

AT = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
LINE = [(30.0 + k * 0.1, -97.0) for k in range(40)]  # about 270 miles due north


# A test truck with a tank, and two Love's on its road.
@pytest.fixture(autouse=True)
def truck(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    with db.connect() as conn:
        db.replace_trucks(conn, [SyncedTruck("340", "1", "V", "Unit 340", 7.0, None, None)])
        db.add_pilot(conn, "340", None)
        db.set_tank(conn, "340", 150.0)
        db.replace_stores(conn, [Store("7", "Near", "TX", 30.5, -97.0, 6.0, 5.5, "2026-11-02"), Store("8", "Far", "TX", 31.5, -97.0, 5.5, 5.0, "2026-11-02")])


# The look of a truck on that road, at a gauge level.
def look(fuel_pct: float) -> TruckWatch:
    return TruckWatch(unit="340", at=AT, state="watch", order_id=1, load_id="L", road_made_at=AT, line=LINE, route_mi=2000.0, mile=0.0,
                      fuel_pct=fuel_pct, forecast_mpg=7.0, cautious_mpg=5.6, usual_known=True,
                      usual=UsualLevel(20, 15, 25, 95, 9), regions=(Region(30.0, 110.0, 2, "x", False, 30.0),))


# A truck nobody knows is a 404 for the page, not a crash.
def test_unknown_truck():
    with pytest.raises(LookupError):
        dashboard.recommend_truck("999")


# No road yet: its place and history, nothing to draw.
def test_truck_without_a_road():
    d = dashboard.recommend_truck("340")
    assert d["road"] is None and d["state"] == "not looked at yet" and d["recommendations"] == [] and d["own_fills"] == [] and d["trips"] == []


# With a road: every Love's with its verdict, the chosen one, the forecast, and nothing said as told.
def test_truck_with_a_road():
    with db.connect() as conn:
        db.save_truck_watch(conn, look(20.0))
    r = dashboard.recommend_truck("340")["road"]
    assert {v["stop"]["store"]["store_no"] for v in r["loves"]} == {"7", "8"}
    assert r["chosen"] in ("7", "8") and r["told"] is False and r["would_say"]
    assert len(r["line"]) > 1
    assert r["zones"][0]["end_mi"] == 0.2 * 150 * 5.6 and len(r["zones"][0]["safe"]) > 1


# A stop told earlier stays the chosen one, with its own words, and its follow-up Love's is marked.
def test_told_stop_stands(monkeypatch):
    monkeypatch.setattr(dashboard, "today", lambda: date(2026, 11, 3))  # the message stays within the days the tab lists
    rec = Recommendation(None, "340", "Ali", 1, "L", AT, "stop", "7", "Love's Near, TX", 34.0, 20.0, 18.0, 17.0, 30.0, "Love's Far, TX", "range",
                         5.5, 6.0, "2026-11-02", 7.0, 5.6, 20.0, "the words", "open", None)
    with db.connect() as conn:
        db.save_truck_watch(conn, look(20.0))
        db.add_recommendation(conn, rec)
    r = dashboard.recommend_truck("340")["road"]
    assert r["told"] is True and r["chosen"] == "7" and r["then"] == "8" and r["would_say"] == "the words"


# The plans on the Live view: a message sent and followed counts its fill's discount, one called off by us is marked so;
# the live trucks' Love's share counts their fills after their first message, the whole fleet's every fill.
def test_messages_sent(monkeypatch):
    monkeypatch.setattr(dashboard_settings, "LIVE_FROM", "2026-11-02")

    def line(at: str, store: str, unit: str) -> FuelLine:
        return FuelLine(int(store), at, "fuel", "ULSD", 100, 600, 550, 0.0, False, f"LOVES #{store} TRAVEL STOP", "Near", "TX", "TTL",
                        unit, "company", 7, "Ali", "company", None)

    rec = Recommendation(None, "340", "Ali", 1, "L", AT, "stop", "7", "Love's Near, TX", 30.0, 30.0, 20.0, 17.0, 130.0, None,
                         "range", 5.5, 6.0, "2026-11-02", 7.0, 5.6, 20.0, "text", "open", None, sent_at=AT)
    with db.connect() as conn:
        db.add_recommendation(conn, rec)
        db.add_recommendation(conn, replace(rec, unit="342", status="replaced", sent_at=AT + timedelta(hours=1)))
        db.replace_fuel_lines(conn, [line("2026-11-02 05:00", "6", "340"), line("2026-11-02 08:00", "7", "340"),
                                     line("2026-11-02 09:00", "8", "341")])
    p = dashboard.live_payload(date(2026, 11, 5))["plans"]  # the messages sent come with the Live view
    assert [m["became"] for m in p["messages"]] == ["there", "off"]
    assert p["at_stops"] == {"gallons": 100, "discount": 50, "paid": 550} and p["by_day"] == {"2026-11-02": 50}
    assert p["live"] == {"gallons": 100, "loves_share": 1, "discount": 50, "paid": 550, "trucks": 1}  # 05:00 Central is before the message
    assert p["fleet"] == {"gallons": 300, "loves_share": 1, "discount": 150, "paid": 1650, "trucks": 2}


# The list of trucks says where each one is, for the map of all trucks; nowhere until Samsara has its position.
def test_truck_list_has_positions():
    from base.models import SamsaraLive
    assert dashboard.recommend_payload()["trucks"][0]["where"] is None
    with db.connect() as conn:
        db.replace_samsara_live(conn, [SamsaraLive("1", 30.2, -97.1, "Austin, TX", AT, 40.0, AT)])
    row = dashboard.recommend_payload()["trucks"][0]
    assert (row["where"], row["place"], row["fuel_pct"]) == ([30.2, -97.1], "Austin, TX", 40.0)


# The fleet status has every Datatruck truck, linked to Samsara or not: a driven truck that reports, one whose only
# card sits on a driver who left but that bought fuel yesterday, and one in the shop that Samsara names under another VIN.
def test_fleet_status():
    from base.fuel import CENTRAL
    from base.models import DatatruckDriver, DatatruckTruck, FuelCard, SamsaraLive, SamsaraVehicle
    now = datetime.now(timezone.utc)
    bought = FuelLine(1, f"{now.astimezone(CENTRAL) - timedelta(days=1):%Y-%m-%d %H:%M}", "fuel", "ULSD", 100, 600, 550, 0.0, False,
                      "LOVES #7 TRAVEL STOP", "Near", "TX", "TTL", "900", "company", 8, "Gone", "lease", 2)
    with db.connect() as conn:
        db.replace_dt_trucks(conn, [DatatruckTruck(1, "340", "V", "in_transit", "company"), DatatruckTruck(2, "900", "W", "available", "company"),
                                    DatatruckTruck(3, "901", "X", "shop", None)])
        db.replace_dt_drivers(conn, [DatatruckDriver(7, "ALI (LO)", "lease", "active", "TTL", "340"),
                                     DatatruckDriver(8, "GONE", "lease", "inactive", "TTL", "900")])
        db.replace_fuel_cards(conn, [FuelCard(1, "TTL", "driver", 7, "340", True, "retail_plus_fee", True, "7539"),
                                     FuelCard(3, "TTL", "driver", 7, "340", True, "retail_plus_fee", True, "0482"),
                                     FuelCard(2, "TTL", "driver", 8, "900", True, "retail_plus_fee", True, "1111")])
        db.replace_samsara_vehicles(conn, [SamsaraVehicle("9", "TTL Unit 901", "Z", None, None)])
        db.replace_samsara_live(conn, [SamsaraLive("1", 30.2, -97.1, "Austin, TX", now, 40.0, now)])
        db.replace_fuel_lines(conn, [bought])
    d = dashboard.fleet_payload()
    rows = {t["unit"]: (t["on_duty"], t["type"], t["samsara"], t["card"]) for t in d["trucks"]}
    assert rows == {"340": (True, "LO", "working", "card"), "900": (False, "none", "none", "fueled"),
                    "901": (False, "none", "mismatch", "nocard")}
    assert d["samsara_at"] == now.isoformat(timespec="seconds") and d["synced_at"] and d["trucks"][0]["driver"] == "ALI (LO)"
    # the cards of a truck's active drivers by their last four digits; a card on a driver who left is not the truck's
    assert {t["unit"]: sorted(t["cards"]) for t in d["trucks"]} == {"340": ["0482", "7539"], "900": [], "901": []}
    # the diesel each truck bought lately, for its column: unit 900 bought 100 gal yesterday, the others none
    assert {t["unit"]: t["gallons"] for t in d["trucks"]} == {"340": 0, "900": 100, "901": 0} and d["gallons_days"] == 30
