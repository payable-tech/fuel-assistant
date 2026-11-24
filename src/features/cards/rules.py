# The card agent's rules (pure): when a tag is worth waking it for, whose card a request is for (the group's driver; on
# a team truck the one writing), which card is theirs (on the truck's unit, in their name when one is), what is done
# with it, and whether a reply may go out. Claude reads the chat and talks to the driver; these rules decide what is
# done to a card, whatever the chat says. The words are in features/cards/wording.
# The user, 2026-11-24: a driver who asks about his fuel card gets it opened for any location, without the office.
import re
from datetime import datetime, timedelta

from base.models import DatatruckDriver, EfsCard, EfsCardRow

# Words of a card request. A reply to one of the account's own fuel messages ("ok", "thanks") wakes nothing without them;
# a tag by name always wakes it.
CARD_WORDS = re.compile(r"card|declin|open|override|pump|activ|not work|doesn.?t work|try again|fuel|diesel|kart",
                        re.IGNORECASE)
# What is done with the driver's card (verdict). The user, 2026-11-24: it is put in override mode for any location,
# whatever its status (an override works on a held or fraud-flagged card too); an inactive card is activated first; a
# card already in override mode is open as it is. WATCH_ONLY: the agent's switch is off, it says what it would do.
OPEN, ACTIVATE_AND_OPEN, ALREADY_OPEN, WATCH_ONLY = "open", "activate and open", "already open", "watch only"
# Why a reply to the driver may not go out (reply_refused).
NOT_A_CARD_REQUEST, ALREADY_REPLIED, HAS_NUMBER, NOT_OPENED = ("not a card request", "already replied", "has a number",
                                                               "not opened")


# A request the rules can't settle on their own; the message says why, for the person who will.
class NeedsPerson(Exception):
    pass


# True when a tag is worth waking the agent for: named outright, or a reply to its messages that sounds like a card
# request (the account sends every fuel stop message, so most replies to it are an "ok").
def woken(text: str, named: bool) -> bool:
    return named or bool(CARD_WORDS.search(text or ""))


# True when a message is only tags ("@desk"), no words of its own.
def only_a_tag(text: str) -> bool:
    return not re.sub(r"@\w+", "", text or "").strip()


# The driver a request is for: the truck's one active driver; on a team truck, the one writing, by name (when the name
# fits both, the one it fits word for word). None when that can't be told: no active driver, or a team and the writer
# is neither clearly (the asker may be the office, or his Telegram name differs).
def whose(drivers: list[DatatruckDriver], sender: str) -> DatatruckDriver | None:
    if len(drivers) == 1:
        return drivers[0]
    writing = [d for d in drivers if same_person(sender, d.full_name)]
    if len(writing) > 1:
        writing = [d for d in writing if _words(sender) == _words(d.full_name)]
    return writing[0] if len(writing) == 1 else None


# The driver's card among those Card Lookup found, in either account: on the truck's unit exactly (a lookup by 318 also
# lists 3189), and the one in his name. When none or several are in his name, the only one of them still in use (not
# INACTIVE): a leftover card of an earlier driver is inactive. Returns the account, the card, and whether it is in his
# name. A person decides when that still leaves no one card.
def their_card(found: list[tuple[str, EfsCardRow]], unit: str,
               driver: DatatruckDriver | None) -> tuple[str, EfsCardRow, bool]:
    on_unit = [(a, r) for a, r in found if r.unit.strip() == unit]
    theirs = [(a, r) for a, r in on_unit if driver and same_person(r.driver_name, driver.full_name)]
    if len(theirs) == 1:
        return *theirs[0], True
    in_use = [(a, r) for a, r in theirs or on_unit if r.status != "INACTIVE"]
    if len(in_use) == 1:
        return *in_use[0], bool(theirs)
    who = plain_name(driver.full_name) if driver else "the driver who wrote"
    seen = ", ".join(f"{named(a, r)} {r.status}" for a, r in on_unit) or "none"
    raise NeedsPerson(f"can't tell which card on unit {unit} is for {who} (cards on that unit: {seen})")


# What is done with the driver's card as it stands (the user, 2026-11-24): a card already in override mode is open; an
# inactive one is activated and opened, but only when it is in his own name (`own`); any other status is opened as it
# is. WATCH_ONLY when the agent's switch is off.
def verdict(card: EfsCard, account: str, row: EfsCardRow, own: bool, may_act: bool) -> str:
    if card.override:
        return ALREADY_OPEN
    if card.status == "INACTIVE" and not own:
        raise NeedsPerson(f"{named(account, row)} is INACTIVE and not in the driver's name; the fuel desk activates "
                          "only a driver's own card")
    if not may_act:
        return WATCH_ONLY
    return ACTIVATE_AND_OPEN if card.status == "INACTIVE" else OPEN


# How long ago the agent last opened this card, when that was within `hours`: the office is told of a repeat. None
# otherwise.
def repeat(last_opened: datetime | None, now: datetime, hours: float) -> timedelta | None:
    if last_opened and now - last_opened < timedelta(hours=hours):
        return now - last_opened
    return None


# Why a reply may not go to the driver, or None when it may: only to a card request (`card_request`: declined_card was
# called; the user, 2026-11-24: anything else gets no answer); only when the card is open (the user, 2026-11-24: an
# opening that failed gets no reply, only an alarm to the office); one reply to a request; never empty and never a
# long number (a card number, a driver ID).
def reply_refused(text: str, card_request: bool, replied: bool, opened: bool) -> str | None:
    if not card_request:
        return NOT_A_CARD_REQUEST
    if not opened:
        return NOT_OPENED
    if replied:
        return ALREADY_REPLIED
    if not text or re.search(r"\d{5,}", text):
        return HAS_NUMBER
    return None


# True when two names are the same person: two words in common, or one when either name has only one ("Mike" and
# "MIKE JOHNSON (LO)"). Datatruck's bracketed additions don't count.
def same_person(one: str | None, other: str | None) -> bool:
    mine, theirs = _words(one), _words(other)
    if not mine or not theirs:
        return False
    shared = mine & theirs
    return len(shared) >= 2 or (min(len(mine), len(theirs)) == 1 and bool(shared))


# A card in a few words, as the office reads it: "card …0806 (DT, unit 3189, JOHN DOE)". Last four digits only.
def named(account: str, row: EfsCardRow) -> str:
    who = ", ".join(p for p in (account, f"unit {row.unit}" if row.unit else "", row.driver_name) if p)
    return f"card …{row.number[-4:]} ({who})"


# A driver's name as Card Lookup can search it: without what Datatruck adds in brackets ("JOHN DOE (CD team)").
def plain_name(name: str | None) -> str:
    return " ".join(re.sub(r"\(.*?\)", "", name or "").split())


# The words of a name, lower case, without Datatruck's bracketed additions and anything not a letter.
def _words(name: str | None) -> frozenset[str]:
    return frozenset(w for w in re.split(r"[^a-z]+", plain_name(name).lower()) if len(w) > 1)


# A span of time in words: "12 min", "3 h 5 min".
def ago(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"
