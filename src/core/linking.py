# Linking rules (pure): Samsara vehicles <-> Datatruck trucks by VIN, and trucks <-> Telegram groups by unit number
# and driver name.
import re
from collections import Counter, defaultdict

from models import ChatMatch, DatatruckDriver, DatatruckTruck, SamsaraVehicle, TelegramGroup

INACTIVE = re.compile(r"INACTIVE", re.IGNORECASE)  # groups of former drivers are titled "**INACTIVE** ..."


# Pairs vehicles and trucks with the same VIN. Empty VINs, repeated Datatruck VINs and repeated unit numbers
# are left out, because any choice between them would be a guess; the `holes` view lists them.
def link_by_vin(vehicles: list[SamsaraVehicle], trucks: list[DatatruckTruck]) -> list[tuple[SamsaraVehicle, DatatruckTruck]]:
    vehicles_by_vin = _newest_by_vin(vehicles)
    trucks_by_vin = _only_unique(trucks, lambda t: t.vin)
    unique_units = _only_unique(trucks, lambda t: t.unit)
    return [(vehicles_by_vin[vin], trucks_by_vin[vin])
            for vin in sorted(vehicles_by_vin.keys() & trucks_by_vin.keys())
            if trucks_by_vin[vin].unit in unique_units]


# Finds each unit's Telegram group: the one group not marked INACTIVE whose title names the unit number (no other fleet
# unit) and one of its active drivers, since old groups of former drivers keep the number. Else a note, never a guess.
def match_chats(units: list[str], groups: list[TelegramGroup], drivers: list[DatatruckDriver]) -> dict[str, ChatMatch]:
    unit_numbers = Counter(_number(u) for u in units)
    open_groups = [g for g in groups if not INACTIVE.search(g.title)]
    # per group: the numbers in its title that are fleet unit numbers ("Unit 340 2024" -> {"340"})
    title_units = {g.chat_id: _numbers_in(g.title) & unit_numbers.keys() for g in open_groups}
    # Dispatch renames a group before Datatruck catches up: a unit Datatruck has no driver on may match on an active
    # driver it puts on no truck (`free`). Nothing contradicts it, and the note says so, for `holes`.
    names, free = defaultdict(list), []  # unit -> its active drivers' names; active drivers on no truck
    for d in drivers:
        if d.employee_status == "active":
            (names[d.unit] if d.unit else free).append(d.full_name)
    return {unit: _match_one(unit, unit_numbers, open_groups, title_units, names[unit], free) for unit in units}


# Decides the group for one unit, or explains why there is none.
def _match_one(unit: str, unit_numbers: Counter, groups: list[TelegramGroup], title_units: dict,
               drivers: list[str], free: list[str]) -> ChatMatch:
    number = _number(unit)
    if unit_numbers[number] > 1:
        return ChatMatch(None, f"several units share number {number}")
    hits = [g for g in groups if title_units[g.chat_id] == {number} and any(_names(g.title, d) for d in drivers or free)]
    if len(hits) > 1:
        return ChatMatch(None, "several groups name the unit and its driver: " + " | ".join(g.title for g in hits))
    if hits:
        return ChatMatch(hits[0].chat_id, None if drivers else
                         f"driver only in the group title '{hits[0].title}': Datatruck has no driver on this truck")
    if not drivers:
        return ChatMatch(None, "no active driver on this unit in Datatruck")
    return ChatMatch(None, f"no group title names unit {number} with {' or '.join(drivers)}")


# True when a title has at least two words of a driver's name, in any order ("Kendrick Williams (LP)" is named by
# "TTL: Williams Kendrick | Unit 50779"). Tags after the name, such as "(LO) REEFER", don't count.
def _names(title: str, driver: str) -> bool:
    return len(_words(driver.split("(")[0]) & _words(title)) >= 2


# The words of a text that can be parts of a name: letters only, at least 3 long, lower-case.
def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)}


# One Samsara vehicle per VIN: the one whose GPS reported last, since an old duplicate record stops reporting
# once its device moves. A VIN is left out when its top two records tie, e.g. neither ever reported.
def _newest_by_vin(vehicles: list[SamsaraVehicle]) -> dict[str, SamsaraVehicle]:
    records = defaultdict(list)
    for v in vehicles:
        if v.vin:
            records[v.vin].append(v)
    newest = {}
    for vin, group in records.items():
        group.sort(key=_last_seen, reverse=True)
        if len(group) == 1 or _last_seen(group[0]) > _last_seen(group[1]):
            newest[vin] = group[0]
    return newest


# Last GPS time as a number for comparing; 0 when the vehicle never reported.
def _last_seen(vehicle: SamsaraVehicle) -> float:
    return vehicle.last_gps_at.timestamp() if vehicle.last_gps_at else 0.0


# Maps key -> item for the items whose key is non-empty and appears exactly once.
def _only_unique(items: list, key) -> dict:
    counts = Counter(key(i) for i in items)
    return {key(i): i for i in items if key(i) and counts[key(i)] == 1}


# A unit number without leading zeros, so "0140" and "140" compare equal.
def _number(unit: str) -> str:
    return unit.lstrip("0") or "0"


# All numbers in a text, without leading zeros: "Unit 0340 / 2024" -> {"340", "2024"}.
def _numbers_in(text: str) -> set[str]:
    return {_number(n) for n in re.findall(r"\d+", text)}
