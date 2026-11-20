# Tests the fleet status rules: on duty, the truck's type, whether Samsara works for it, and its fuel card.
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core import fleet_status
from models import FleetTruck

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(hours=24)
# A truck with nothing wrong: driven, linked to Samsara, both readings an hour old, a card assigned.
GOOD = FleetTruck(unit="101", status="in_transit", driver="ALI (LO)", driver_type="lease", samsara_name="TTL Unit 101",
                  gps_at=NOW - timedelta(hours=1), fuel_pct=60.0, fuel_at=NOW - timedelta(hours=1), has_card=True,
                  fueled_at="2026-11-19 08:00")


# On duty needs both a working status and a driver.
def test_on_duty():
    assert fleet_status.on_duty(GOOD) and fleet_status.on_duty(replace(GOOD, status="available"))
    assert not fleet_status.on_duty(replace(GOOD, status="shop"))
    assert not fleet_status.on_duty(replace(GOOD, driver=None, driver_type=None))


# Each Datatruck driver type has the office's name; an unknown or missing type is "Other", no driver is "none".
def test_truck_type():
    types = {"lease": "LO", "company_driver": "C", "company_owner": "OO", "other": "Other", None: "Other"}
    assert {t: fleet_status.truck_type(replace(GOOD, driver_type=t)) for t in types} == types
    assert fleet_status.truck_type(replace(GOOD, driver=None, driver_type=None)) == "none"


# The last word of each Samsara name is its unit; a blank name names nothing.
def test_named_units():
    assert fleet_status.named_units(["TTL Unit 101", "Unit 33 SUB 555", " ", ""]) == {"101", "555"}


# The checks in order: no link (named in Samsara or not), no GPS, gauge never, gauge silent, working.
def test_samsara_state():
    state = lambda truck, named=frozenset(): fleet_status.samsara_state(truck, set(named), NOW, DAY)
    unlinked = replace(GOOD, samsara_name=None, gps_at=None, fuel_pct=None, fuel_at=None)
    assert state(unlinked) == "none"
    assert state(unlinked, {"101"}) == "mismatch"
    assert state(replace(unlinked, unit="..101"), {"101"}) == "mismatch"  # dots around a unit don't hide it
    assert state(replace(unlinked, unit=".."), {"101"}) == "none"
    assert state(replace(GOOD, gps_at=None)) == "nogps"
    assert state(replace(GOOD, gps_at=NOW - timedelta(hours=25))) == "nogps"
    assert state(replace(GOOD, fuel_pct=None, fuel_at=None)) == "never"
    assert state(replace(GOOD, fuel_at=NOW - timedelta(hours=25))) == "silent"
    assert state(GOOD) == "working"


# A card assigned wins; without one, a purchase on or after the day counted from tells the two other groups apart.
def test_card_state():
    since = "2026-11-06 06:00"
    assert fleet_status.card_state(GOOD, since) == "card"
    assert fleet_status.card_state(replace(GOOD, has_card=False), since) == "fueled"
    assert fleet_status.card_state(replace(GOOD, has_card=False, fueled_at="2026-11-01 08:00"), since) == "nocard"
    assert fleet_status.card_state(replace(GOOD, has_card=False, fueled_at=None), since) == "nocard"
