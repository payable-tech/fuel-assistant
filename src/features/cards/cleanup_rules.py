# The card cleanup's rule (pure; the user, 2026-11-24): every Datatruck unit keeps its card, and every other EFS card is
# parked: INACTIVE, unit 99999, driver ID 99999, driver name ALIF UZ CORP. A card still in use on a unit Datatruck
# doesn't have is left for a person. The doer is features/cards/cleanup.
from features.cards.rules import same_person
from features.cards.settings import PARKED_PROMPTS  # the prompts of a parked card, by fuel_cards.PROMPTS' names

# What is done with a card (decide).
KEEP, LEAVE, PARK, PARKED = "keep", "leave", "park", "parked already"


# What is done with one EFS card, and why, in a few words. A card in use (any status but INACTIVE) is the unit's card
# when it is on a Datatruck unit, else a person decides. An inactive card stays only as the unit's card: the one
# Datatruck lists on that unit (`listed`: unit and last 4), or one in the name of that unit's driver (`drivers`: each
# Datatruck unit with its active drivers), whom the card agent may activate it for. `driver_id` is None when not known.
def decide(status: str, unit: str | None, last4: str, name: str | None, driver_id: str | None,
           drivers: dict[str, list[str]], listed: set[tuple[str, str]]) -> tuple[str, str]:
    unit = (unit or "").strip()
    if status == "INACTIVE" and _parked(unit, name, driver_id):
        return PARKED, "already 99999 / ALIF UZ CORP"
    if status != "INACTIVE":
        if unit in drivers:
            return KEEP, "in use on its unit"
        return LEAVE, "in use, on a unit Datatruck doesn't have: for a person"
    if (unit, last4) in listed:
        return KEEP, "Datatruck lists it on this unit"
    if any(same_person(name, driver) for driver in drivers.get(unit, ())):
        return KEEP, "in the name of this unit's driver"
    return PARK, "inactive, not this unit's card" if unit in drivers else "inactive, on no Datatruck unit"


# The units that end with no card: no card of theirs is kept (`kept_units`: the unit of every kept card).
def left_without_card(drivers: dict[str, list[str]], kept_units: set[str]) -> list[str]:
    return sorted(unit for unit in drivers if unit not in kept_units)


# True when a card's prompts are a parked card's already (a driver ID that isn't known doesn't count against it).
def _parked(unit: str, name: str | None, driver_id: str | None) -> bool:
    return (unit == PARKED_PROMPTS["unit"] and (name or "").strip().upper() == PARKED_PROMPTS["driver"]
            and driver_id in (None, PARKED_PROMPTS["driver-id"]))
