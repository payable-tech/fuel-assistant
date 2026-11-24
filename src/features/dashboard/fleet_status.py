# Fleet status (pure): what one unit of the master is, as short keys the dashboard names and colors: whether it is on
# duty, its type, whether Samsara works for it, how its card stands in EFS, and whether Datatruck's cards and EFS's
# are the same.
from datetime import datetime, timedelta

from base.models import Unit

ON_DUTY = ("in_transit", "available")  # Datatruck statuses of a truck that is working, when somebody drives it
TYPES = {"lease": "LO", "company_driver": "C", "company_owner": "OO"}  # Datatruck's driver type -> the office's name


# True for a truck that is working: in transit or available, with an active driver.
def on_duty(truck: Unit) -> bool:
    return truck.status in ON_DUTY and truck.driver is not None


# The truck's type, from its driver's type in Datatruck: "LO", "C", "OO" or "Other"; "none" when nobody drives it.
def truck_type(truck: Unit) -> str:
    if truck.driver is None:
        return "none"
    return TYPES.get(truck.driver_type, "Other")


# The unit numbers Samsara's vehicle names end with ("TTL Unit 101" -> "101"): a truck that isn't linked by VIN but is
# named in Samsara has a device, with the wrong VIN on one side.
def named_units(samsara_names: list[str]) -> set[str]:
    return {name.split()[-1] for name in samsara_names if name.split()}


# Whether Samsara works for the truck; the first check that fails names it. "none": no Samsara vehicle has its VIN or
# its unit number; "mismatch": one is named for the unit, under another VIN; "nogps": no position for `stale`;
# "never": the gauge never reported; "silent": the gauge's last reading is older than `stale`; else "working".
def samsara_state(truck: Unit, named: set[str], now: datetime, stale: timedelta) -> str:
    if truck.samsara_name is None:
        return "mismatch" if truck.unit.strip(".") in named else "none"  # retired duplicates carry dots: "..101"
    if truck.gps_at is None or now - truck.gps_at > stale:
        return "nogps"
    if truck.fuel_pct is None or truck.fuel_at is None:
        return "never"
    return "silent" if now - truck.fuel_at > stale else "working"


# How the unit's card stands in EFS: "active" when a card carrying its unit number is ACTIVE; "held" when none is but
# one is on hold (HOLD, HOLD FOR FRAUD); "inactive" when its cards are all INACTIVE; "none" when no card carries it.
def card_state(truck: Unit) -> str:
    statuses = {card.status for card in truck.efs}
    if "ACTIVE" in statuses:
        return "active"
    if statuses - {"INACTIVE"}:
        return "held"
    return "inactive" if statuses else "none"


# Whether Datatruck's cards for the unit and EFS's are the same, by their last four digits. EFS's are its cards in use
# (any status but INACTIVE: a leftover card of an earlier driver is inactive). "match": the same cards on both sides;
# "differ": cards on both, not the same; "datatruck" / "efs": cards on that side only; "none": on neither.
def cards_match(truck: Unit) -> str:
    datatruck = set(truck.cards)
    efs = {card.last4 for card in truck.efs if card.status != "INACTIVE"}
    if not datatruck and not efs:
        return "none"
    if not efs:
        return "datatruck"
    if not datatruck:
        return "efs"
    return "match" if datatruck == efs else "differ"
