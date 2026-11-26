# Copies EFS's cards into the database for the dashboard: each account's whole list as Card Lookup gives it; for the
# cards in use, what only a card's own page shows (the day EFS last saw it used, override mode); and which EFS card each
# Datatruck fuel card is. Run by whichever program holds the eManager window: the card agent, or the EFS login window
# (`efs-login`) while the agent is off.
import logging
from datetime import datetime, timedelta, timezone

from base.models import EfsCardRow
from base.store import db
from features.cards import settings
from features.cards.emanager import fuel_cards, window

log = logging.getLogger(__name__)


# One round. An account whose list can't be read now (eManager logged out, a page that didn't load) or comes back
# empty keeps its old copy and is tried next round; its pages are read only after its list was. Then the Datatruck
# cards not linked yet are looked up, in the accounts whose lists were read.
def copy() -> None:
    prefixes = {}  # the first six digits of an account's card numbers -> the account ("556748" -> "ALIF")
    for account in settings.EMANAGER_USERS:
        try:
            with window.held():
                cards = fuel_cards.cards(account, "all")
        except Exception as failure:
            log.warning("EFS cards of %s not copied: %r", account, failure)
            continue
        if not cards:
            log.warning("EFS cards of %s not copied: the list came back empty", account)
            continue
        with db.connect() as conn:
            db.replace_efs_cards(conn, account, cards)
        log.info("EFS cards of %s copied: %d", account, len(cards))
        prefixes.update({row.number[:6]: account for row in cards})
        _read_pages(account, cards)
    if prefixes:
        _link(prefixes)


# Reads the page of each of the account's cards in use that wasn't read in the last EFS_PAGE_HOURS (a page takes about
# 2 s; the day of last use changes once a day at most). A page that can't be read is skipped and tried next round.
def _read_pages(account: str, cards: list[EfsCardRow]) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=settings.EFS_PAGE_HOURS)
    with db.connect() as conn:
        fresh = db.efs_pages_read_since(conn, account, since)
    due = [row for row in cards if row.status != "INACTIVE" and row.card_id not in fresh]
    read = 0
    for row in due:
        try:
            with window.held():
                page = fuel_cards.card(account, row)
            last_used = _day(page.last_used)
        except Exception as failure:
            log.warning("EFS card %s of %s: page not read: %r", row.number[-4:], account, failure)
            continue
        with db.connect() as conn:
            db.save_efs_card_page(conn, account, row.card_id, last_used, page.override)
        read += 1
    if due:
        log.info("EFS card pages of %s read: %d of %d", account, read, len(due))


# Finds the EFS card of each Datatruck card not linked yet (or whose last four digits changed): EFS's lists show only
# the last four digits, which repeat across cards, so Card Lookup is asked for Datatruck's full number (its copy,
# fuel_cards), in the account whose numbers start the same way (one search, 3 to 7 s). A number no account's start, or
# that EFS doesn't find, is linked to no card; a card whose number isn't copied yet waits. An eManager error ends
# this round's linking; the next round carries on.
def _link(prefixes: dict[str, str]) -> None:
    with db.connect() as conn:
        due = [card for card in db.cards_to_link(conn) if card[2]]
    linked = 0
    for dt_card_id, last4, number in sorted(due, key=lambda card: prefixes.get(card[2][:6], "")):
        account = prefixes.get(number[:6])
        try:
            found = _search(account, number) if account else []
        except Exception as failure:
            log.warning("Datatruck cards not linked to EFS this round (%d of %d done): %r", linked, len(due), failure)
            return
        efs_card_id = found[0].card_id if len(found) == 1 else None
        with db.connect() as conn:
            db.save_card_link(conn, dt_card_id, last4, account if efs_card_id else None, efs_card_id)
        linked += 1
    if due:
        log.info("Datatruck cards linked to EFS: %d", linked)


# EFS's cards with exactly this full number in one account (Card Lookup by card number).
def _search(account: str, number: str) -> list[EfsCardRow]:
    with window.held():
        return fuel_cards.cards(account, "card", number)


# The day as the card page prints it ("Nov 25, 2026") as "2026-11-25"; None for a card never used (""). Any other
# text raises, so a changed page is noticed rather than read wrong.
def _day(text: str) -> str | None:
    return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat() if text.strip() else None
