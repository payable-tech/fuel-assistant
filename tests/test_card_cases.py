# Tests which messages of a truck group become test cases for the card agent: a card message of the truck's own driver,
# one per burst. Telegram itself is never reached here.
from datetime import datetime, timedelta, timezone

from base.models import DatatruckDriver
from features.cards import cases

AT = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
JOHN = DatatruckDriver(1, "JOHN DOE (CD team)", "company_driver", "active", "DT", "3189")


# A case is a card message written by the truck's own driver: not the office's, not the assistant's fuel stop messages,
# not a driver's message about something else.
def test_only_the_drivers_own_card_messages():
    assert cases.is_case("my card declined at Pilot", "John Doe", [JOHN])
    assert cases.is_case("Card not working", "john doe", [JOHN])
    assert not cases.is_case("card is ready, try again", "Bob Office", [JOHN])       # the office's answer
    assert not cases.is_case("Fuel stop: Love's Dunn, NC", "Migo", [JOHN])          # the assistant's own message
    assert not cases.is_case("I am at the pump", "John Doe", [JOHN])                 # no card in it
    assert not cases.is_case("card declined", "John Doe", [])                        # no driver on the truck


# Several card messages a few minutes apart are one case, its last message; a later one is a case of its own.
def test_one_case_per_burst():
    hits = [(10, AT), (11, AT + timedelta(minutes=3)), (12, AT + timedelta(minutes=9)), (40, AT + timedelta(hours=5))]
    assert cases.last_of_bursts(hits, timedelta(minutes=15)) == [12, 40]
    assert cases.last_of_bursts([], timedelta(minutes=15)) == []
