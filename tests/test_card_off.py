# Turning cards off (features/cards/card_off_rules): who is parked, what X-Ref each card gets, and which cards are due.
from datetime import date, datetime, timezone

from features.cards import card_off_rules as rules

DAY = date(2026, 11, 26)


# Only a driver Datatruck has as inactive is parked, with QUIT and his Datatruck ID; anyone else (active, an
# applicant, no Datatruck card) gets HOMETIME and keeps the card's prompts. Both fit eManager's 15 characters.
def test_what_each_card_gets():
    assert rules.action("inactive", 17481, DAY) == (rules.QUIT, "QUIT 17481 1126")
    assert rules.action("active", 17481, DAY) == (rules.HOMETIME, "HOMETIME 11-26")
    assert rules.action("applicant", 9, DAY)[0] == rules.HOMETIME and rules.action(None, None, DAY)[0] == rules.HOMETIME
    assert rules.action("inactive", None, DAY)[0] == rules.HOMETIME  # no Datatruck ID to write: not parked


# Due: ACTIVE cards whose latest check says off and is recent; not one already off, on, unsure or checked long ago.
def test_which_cards_are_due():
    card = lambda status, should_be, at: {"status": status, "should_be": should_be, "checked_at": at}
    cards = [card("ACTIVE", "off", "2026-11-26 16:20:00+00:00"), card("INACTIVE", "off", "2026-11-26 16:20:00+00:00"),
             card("ACTIVE", "on", "2026-11-26 16:20:00+00:00"), card("ACTIVE", "off", "2026-11-24 10:00:00+00:00"),
             card("ACTIVE", None, None)]
    assert rules.due(cards, datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc)) == cards[:1]
