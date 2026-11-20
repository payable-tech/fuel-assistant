# Fleet status (pure): what one Datatruck truck is, as short keys the dashboard names and colors: whether it is on
# duty, its type, whether Samsara works for it, and whether it has a fuel card.
from datetime import datetime, timedelta

from models import FleetTruck

ON_DUTY = ("in_transit", "available")  # Datatruck statuses of a truck that is working, when somebody drives it
TYPES = {"lease": "LO", "company_driver": "C", "company_owner": "OO"}  # Datatruck's driver type -> the office's name


# True for a truck that is working: in transit or available, with an active driver.
def on_duty(truck: FleetTruck) -> bool:
    return truck.status in ON_DUTY and truck.driver is not None


# The truck's type, from its driver's type in Datatruck: "LO", "C", "OO" or "Other"; "none" when nobody drives it.
def truck_type(truck: FleetTruck) -> str:
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
def samsara_state(truck: FleetTruck, named: set[str], now: datetime, stale: timedelta) -> str:
    if truck.samsara_name is None:
        return "mismatch" if truck.unit.strip(".") in named else "none"  # retired duplicates carry dots: "..101"
    if truck.gps_at is None or now - truck.gps_at > stale:
        return "nogps"
    if truck.fuel_pct is None or truck.fuel_at is None:
        return "never"
    return "silent" if now - truck.fuel_at > stale else "working"


# Whether the truck has a fuel card: "card" when one is assigned; "fueled" when none is but the truck bought fuel on
# or after `fueled_since` (Central "YYYY-MM-DD HH:MM", as purchases are stamped), so it has one in hand; else "nocard".
def card_state(truck: FleetTruck, fueled_since: str) -> str:
    if truck.has_card:
        return "card"
    return "fueled" if truck.fueled_at and truck.fueled_at >= fueled_since else "nocard"
