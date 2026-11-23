# The card agent's rules (pure), as bob-agent's fuel card worker has them (owner, 2026-10-11): when a tag is worth waking
# it for, whose card a request is for (the group's driver; on a team truck the one writing), which card is theirs (the
# one on the truck's unit in their name), what is done with a declined card, and whether a reply may go out. Claude
# reads the chat and talks to the driver; these rules decide what is done to a card, whatever the chat says. The words
# are in features/cards/wording.
import re
from datetime import datetime, timedelta

from base.models import DatatruckDriver, EfsCard, EfsCardRow

# Words of a card request. A reply to one of the account's own fuel messages ("ok", "thanks") wakes nothing without them;
# a tag by name always wakes it.
CARD_WORDS = re.compile(r"card|declin|open|override|pump|activ|not work|doesn.?t work|try again|fuel|diesel|kart",
                        re.IGNORECASE)
# owner, 2026-10-11: what Bob does for a declined card, by its status and whether an override is on: the change, and
# whether a person is asked first. Anything not here goes to a person.
OPEN, ACTIVATE_AND_OPEN = "open", "activate and open"
RULES = {("ACTIVE", False): (OPEN, False), ("HOLD", False): (ACTIVATE_AND_OPEN, True),
         ("INACTIVE", False): (ACTIVATE_AND_OPEN, True)}
# What is done with a declined card (verdict): opened now, the office asked first, or only watched (the agent's switch
# is off: it says what it would do).
OPEN_NOW, ASK_FIRST, WATCH_ONLY = "open now", "ask first", "watch only"
# Why a reply to the driver may not go out (reply_refused).
ALREADY_REPLIED, HAS_NUMBER, NOT_OPENED = "already replied", "has a number", "not opened"


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


# The driver a request is for: the truck's one active driver; on a team truck, the one writing, by name (owner,
# 2026-10-11: the asker's Telegram name may differ from the driver's, so a team with no clear match goes to a person).
def whose(drivers: list[DatatruckDriver], sender: str) -> DatatruckDriver:
    if not drivers:
        raise NeedsPerson("Datatruck has no active driver on this truck")
    if len(drivers) == 1:
        return drivers[0]
    writing = [d for d in drivers if same_person(sender, d.full_name)]
    if len(writing) != 1:
        raise NeedsPerson(f"this truck has {len(drivers)} drivers and {sender} is not clearly one of them")
    return writing[0]


# The driver's own card: the one card, in either account, on the truck's unit exactly (a lookup by 318 also lists 3189)
# and in the driver's name. A card on the unit in another name is never touched.
def their_card(found: list[tuple[str, EfsCardRow]], unit: str, driver: DatatruckDriver) -> tuple[str, EfsCardRow]:
    on_unit = [(a, r) for a, r in found if r.unit.strip() == unit]
    theirs = [(a, r) for a, r in on_unit if same_person(r.driver_name, driver.full_name)]
    if len(theirs) != 1:
        seen = ", ".join(f"{named(a, r)} {r.status}" for a, r in on_unit) or "none"
        raise NeedsPerson(f"{len(theirs)} cards on unit {unit} are in {plain_name(driver.full_name)}'s name "
                          f"(cards on that unit: {seen})")
    return theirs[0]


# What the owner's table does with a card as it stands: the change and whether a person says yes first. A card it has
# no line for goes to a person.
def rule(card: EfsCard, account: str, row: EfsCardRow) -> tuple[str, bool]:
    found = RULES.get((card.status, card.override))
    if found is None:
        on = ", with an override already on" if card.override else ""
        raise NeedsPerson(f"{named(account, row)} is {card.status}{on}; that is not for the fuel desk to fix")
    return found


# Why the agent may not open a card again now, or None when it may: not within `reopen_hours` of opening it itself
# (a second request so soon is the office's to judge).
def too_soon(last_opened: datetime | None, now: datetime, reopen_hours: float) -> str | None:
    if last_opened and now - last_opened < timedelta(hours=reopen_hours):
        return f"the fuel desk opened this card {ago(now - last_opened)} ago"
    return None


# What is done with a declined card, the driver's own, as it stands: the owner's table first (a card it has no line for
# goes to a person), then the wait after the agent's own last opening (a second request so soon is the office's to
# judge), then whether the table wants a person's yes first (ASK_FIRST), then whether the agent may act at all
# (WATCH_ONLY when its switch is off), else OPEN_NOW.
def verdict(card: EfsCard, account: str, row: EfsCardRow, last_opened: datetime | None, now: datetime,
            reopen_hours: float, may_act: bool) -> str:
    _, ask_first = rule(card, account, row)
    soon = too_soon(last_opened, now, reopen_hours)
    if soon:
        raise NeedsPerson(f"{named(account, row)}: {soon}")
    if ask_first:
        return ASK_FIRST
    return OPEN_NOW if may_act else WATCH_ONLY


# Why a reply may not go to the driver, or None when it may: one reply to a request; never empty and never a long
# number (a card number, a driver ID); never "open", "ready" or "try again" when no card was opened for this request.
def reply_refused(text: str, replied: bool, opened: bool) -> str | None:
    if replied:
        return ALREADY_REPLIED
    if not text or re.search(r"\d{5,}", text):
        return HAS_NUMBER
    if not opened and re.search(r"\b(open|ready|try again)\b", text, re.IGNORECASE):
        return NOT_OPENED
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
