# Tests the linking rules: VIN pairing, and Telegram group matching (unit number + driver name) that never guesses.
from datetime import datetime, timezone

from base.fleet.linking import link_by_vin, match_chats
from base.models import DatatruckDriver, DatatruckTruck, SamsaraVehicle, TelegramGroup


# Builds a Samsara vehicle with only the fields linking uses; `gps_day` is the October day of its last GPS.
def vehicle(sid: str, vin: str, gps_day: int | None = None) -> SamsaraVehicle:
    last_gps = datetime(2026, 10, gps_day, tzinfo=timezone.utc) if gps_day else None
    return SamsaraVehicle(samsara_id=sid, name=f"Unit {sid}", vin=vin, mpg=None, last_gps_at=last_gps)


# Builds a Datatruck truck with only the fields linking uses.
def truck(dt_id: int, unit: str, vin: str) -> DatatruckTruck:
    return DatatruckTruck(dt_id=dt_id, unit=unit, vin=vin, status="available", ownership="company")


# Same VIN on both sides links; a VIN on one side only does not.
def test_vin_pairs():
    pairs = link_by_vin([vehicle("a", "V1"), vehicle("b", "V2")], [truck(1, "340", "V1"), truck(2, "717", "V9")])
    assert [(v.samsara_id, t.unit) for v, t in pairs] == [("a", "340")]


# Empty VINs are never linked, nor a repeated Samsara VIN whose records tie (neither ever reported GPS).
def test_vin_empty_or_tied_not_linked():
    vehicles = [vehicle("a", ""), vehicle("b", "V2"), vehicle("c", "V2")]
    trucks = [truck(1, "340", ""), truck(2, "717", "V2")]
    assert link_by_vin(vehicles, trucks) == []


# When Samsara has an old and a new record for one VIN, the one with the latest GPS is linked.
def test_vin_duplicate_latest_gps_wins():
    pairs = link_by_vin([vehicle("old", "V1", gps_day=1), vehicle("new", "V1", gps_day=18)], [truck(1, "700", "V1")])
    assert [(v.samsara_id, t.unit) for v, t in pairs] == [("new", "700")]


# A VIN listed twice in Datatruck is never linked.
def test_vin_repeated_in_datatruck_not_linked():
    assert link_by_vin([vehicle("a", "V1", gps_day=18)], [truck(1, "340", "V1"), truck(2, "717", "V1")]) == []


# A unit number used by two Datatruck trucks is never linked.
def test_repeated_unit_not_linked():
    pairs = link_by_vin([vehicle("a", "V1"), vehicle("b", "V2")], [truck(1, "340", "V1"), truck(2, "340", "V2")])
    assert pairs == []


# An active driver of a unit, as Datatruck writes the name.
def driver(unit: str, name: str, status: str = "active") -> DatatruckDriver:
    return DatatruckDriver(driver_id=0, full_name=name, driver_type="lease", employee_status=status,
                           company="TTL", unit=unit)


# The group naming the unit and its driver is picked; leading zeros and the order of the name words don't matter.
def test_chat_unit_and_driver_match():
    groups = [TelegramGroup(-1, "TTL: Ali Karimov (LO) | Unit 340"), TelegramGroup(-2, "TTL: Williams Kendrick (LP) | Unit 717")]
    drivers = [driver("0340", "ALI KARIMOV (LO)"), driver("717", "Kendrick Williams (LP)")]
    result = match_chats(["0340", "717"], groups, drivers)
    assert (result["0340"].chat_id, result["717"].chat_id) == (-1, -2)


# Old groups of former drivers keep the unit number: the current driver's group wins, an INACTIVE one is skipped.
def test_chat_former_drivers_ignored():
    groups = [TelegramGroup(-1, "TTL: Bob Stone (C) | Unit 340"), TelegramGroup(-2, "**INACTIVE** Ali Karimov | Unit 340"),
              TelegramGroup(-3, "TTL: Ali Karimov (LO) | Unit 340")]
    assert match_chats(["340"], groups, [driver("340", "Ali Karimov (LO) REEFER")])["340"].chat_id == -3


# Numbers in a title that aren't fleet units (years, phones) don't block a match.
def test_chat_ignores_non_unit_numbers():
    result = match_chats(["340"], [TelegramGroup(-1, "Ali Karimov | Unit 340 since 2024")], [driver("340", "Ali Karimov")])
    assert result["340"].chat_id == -1


# Not certain, so no chat and a note says why: only a former driver's group, two groups naming the driver,
# a group naming two units, no active driver, or just one shared word of the name.
def test_chat_not_guessed():
    groups = [TelegramGroup(-1, "TTL: Bob Stone | Unit 340"), TelegramGroup(-2, "Ali Karimov | Unit 555"),
              TelegramGroup(-3, "HOME TIME Ali Karimov | Unit 555"), TelegramGroup(-4, "Team Joe Doe 717 + 777"),
              TelegramGroup(-5, "Sam Lee | Unit 888")]
    drivers = [driver("340", "Ali Karimov"), driver("555", "Ali Karimov"), driver("717", "Joe Doe"),
               driver("777", "Old Driver", status="inactive"), driver("888", "Sam Smith")]
    result = match_chats(["340", "555", "717", "777", "888"], groups, drivers)
    assert all(result[u].chat_id is None and result[u].note for u in ["340", "555", "717", "777", "888"])


# Datatruck has no driver on the truck yet, but dispatch renamed the group: a title naming the unit and an active
# driver Datatruck puts on no truck links (with a note saying so). A driver Datatruck has on another truck doesn't.
def test_chat_from_title_when_datatruck_has_no_driver():
    groups = [TelegramGroup(-1, "HOME TIME TTL: Evans Dolce (LO)|Unit 6135"), TelegramGroup(-2, "TTL: Bob Stone | Unit 717")]
    drivers = [DatatruckDriver(1, "Evans Dolce (LO)", "lease", "active", "TTL", None),
               DatatruckDriver(2, "Bob Stone", "lease", "active", "TTL", "999")]
    result = match_chats(["6135", "717", "999"], groups, drivers)
    assert result["6135"].chat_id == -1 and "group title" in result["6135"].note
    assert result["717"].chat_id is None


# Two units that are the same number ("03" and "3") can't be told apart, so neither is matched.
def test_chat_shared_unit_number():
    result = match_chats(["03", "3"], [TelegramGroup(-1, "Ali Karimov | Unit 3")], [driver("3", "Ali Karimov")])
    assert result["03"].chat_id is None and result["3"].chat_id is None
