# A pretend eManager for the card agent's test group (AGENT_TEST_CHAT_ID): one fabricated truck, driver and fuel card,
# kept in memory. Nothing real is read or changed; it answers the way features/cards/efs_cards does, so the agent's rules and
# Claude's part can be tried end to end in Telegram (the user, 2026-11-23).
from dataclasses import replace
from datetime import datetime, timezone

from base import config
from base.models import DatatruckDriver, EfsCard, EfsCardRow, Truck

UNIT = "TEST-1"
NOW = datetime.now(timezone.utc)
TRUCK = Truck(UNIT, "", "", f"Unit {UNIT}", "Alex Testov", 6.8, 14.0, NOW, 32.01, -97.13, "I-35, Hillsboro, TX (test)",
              NOW, 150.0, "manual", None, config.AGENT_TEST_CHAT_ID, "manual", None, False)
DRIVERS = [DatatruckDriver(999999, "ALEX TESTOV (test)", "company_driver", "active", "TEST", UNIT)]
ROW = EfsCardRow("test-0001", "700000******0001", "T", UNIT, "0000", "ALEX TESTOV", "", "ACTIVE")
_FRESH = EfsCard("test-0001", "ACTIVE", "POLICY", "CARD", "POLICY", "T", "", "Jan 1, 2030", "", False,
                 (("Unit Number", "Exact Match", UNIT), ("Driver ID", "Exact Match", "0000")))
_card = {"now": _FRESH}


# Card Lookup: the test card when asked for its unit (or what it starts with), in the DT account only.
def cards(account: str, by: str, text: str) -> list[EfsCardRow]:
    return [ROW] if account == "DT" and by == "unit" and UNIT.startswith(text.strip()) else []


# The test card's page as it stands now.
def card(account: str, row: EfsCardRow) -> EfsCard:
    return _card["now"]


# Opens the test card (override mode), as eManager would show it afterwards.
def set_override(account: str, row: EfsCardRow, times: int, hand_enter: bool = False) -> EfsCard:
    _card["now"] = replace(_card["now"], override=True)
    return _card["now"]


# Puts the test card back as it started: active, not open; or in another status, to try that rule.
def reset(status: str = "ACTIVE") -> None:
    _card["now"] = replace(_FRESH, status=status)
