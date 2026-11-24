# Tests the fleet status rules: on duty, the truck's type, whether Samsara works for it, how its card stands in EFS, and
# whether Datatruck's cards and EFS's match.
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from base.models import Unit, UnitCard
from features.dashboard import fleet_status

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(hours=24)
MINE = UnitCard("7539", "ACTIVE", "ALI", "ALIF")
# A unit with nothing wrong: driven, linked to Samsara, both readings an hour old, the same active card on both sides.
GOOD = Unit(unit="101", status="in_transit", driver="ALI (LO)", driver_type="lease", samsara_name="TTL Unit 101",
            gps_at=NOW - timedelta(hours=1), fuel_pct=60.0, fuel_at=NOW - timedelta(hours=1), cards=("7539",), efs=(MINE,))


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


# The card in EFS: an active one wins; else one on hold; else only inactive ones; else none.
def test_card_state():
    old, held = UnitCard("1111", "INACTIVE", "GONE", "ALIF"), UnitCard("2222", "HOLD FOR FRAUD", "ALI", "DT")
    assert fleet_status.card_state(replace(GOOD, efs=(old, held, MINE))) == "active"
    assert fleet_status.card_state(replace(GOOD, efs=(old, held))) == "held"
    assert fleet_status.card_state(replace(GOOD, efs=(old,))) == "inactive"
    assert fleet_status.card_state(replace(GOOD, efs=())) == "none"


# Datatruck's cards against EFS's cards in use, by their last four digits; a leftover inactive card in EFS is not
# counted.
def test_cards_match():
    old, other = UnitCard("1111", "INACTIVE", "GONE", "ALIF"), UnitCard("0482", "HOLD", "ALI", "DT")
    assert fleet_status.cards_match(replace(GOOD, efs=(MINE, old))) == "match"
    assert fleet_status.cards_match(replace(GOOD, efs=(MINE, other))) == "differ"
    assert fleet_status.cards_match(replace(GOOD, efs=(other,))) == "differ"
    assert fleet_status.cards_match(replace(GOOD, efs=(old,))) == "datatruck"
    assert fleet_status.cards_match(replace(GOOD, cards=())) == "efs"
    assert fleet_status.cards_match(replace(GOOD, cards=(), efs=(old,))) == "none"
