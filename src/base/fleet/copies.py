# The copies: each outside service's rows copied whole into its own table. `refresh` is the safe step every copy goes
# through: a failed or empty fetch keeps the previous copy instead of wiping it, and every try is recorded in
# source_health, so a source that keeps failing is seen (the heartbeat alerts on it). Under it, the plain copies: the
# trucks' positions and fuel, the active loads, the fuel purchases and cards.
import logging
from datetime import date, datetime, timedelta, timezone

from base import config
from base.sources import datatruck, datatruck_web, samsara
from base.store import db

log = logging.getLogger(__name__)


# Fetches rows from a source and replaces its table whole. Returns True when the copy was refreshed.
def refresh(name: str, fetch, write) -> bool:
    tried = datetime.now(timezone.utc)
    try:
        rows = fetch()
        if not rows:
            raise ValueError("source returned no rows")
    except Exception as error:  # a source being down must not stop the other refreshes
        log.warning("%s not refreshed, keeping the previous copy: %r", name, error)
        _record(name, tried, f"{type(error).__name__}: {error}")
        return False
    with db.connect() as conn:
        write(conn, rows)
        db.record_source(conn, name, tried, None)
    log.info("%s refreshed: %d rows", name, len(rows))
    return True


# Records a failed try; a database too busy to take it doesn't stop the refreshes (the next try records again).
def _record(name: str, tried: datetime, error: str) -> None:
    try:
        with db.connect() as conn:
            db.record_source(conn, name, tried, error[:500])
    except Exception:
        log.exception("Could not record that %s failed", name)


# Copies every truck's latest Samsara GPS point and fuel level into `samsara_live`. Returns True when it was refreshed.
def live() -> bool:
    return refresh("Samsara live", samsara.live, db.replace_samsara_live)


# Copies all active Datatruck orders and their stops into `dt_orders` / `dt_stops`. Returns True when it was refreshed.
def orders() -> bool:
    return refresh("Datatruck orders", datatruck.active_orders, db.replace_orders)


# Copies every Datatruck fuel line and fuel card in full (a few minutes; catches late edits to older lines).
def fuel() -> None:
    refresh("Datatruck fuel lines", datatruck_web.fuel_lines, db.replace_fuel_lines)
    refresh("Datatruck fuel cards", datatruck_web.fuel_cards, db.replace_fuel_cards)


# Copies only the last RECENT_FUEL_DAYS days of fuel lines (seconds), which is what the live view needs.
def recent_fuel() -> None:
    since = (date.today() - timedelta(days=config.RECENT_FUEL_DAYS)).isoformat()
    refresh("Datatruck fuel lines, last days", lambda: datatruck_web.fuel_lines_since(since),
            lambda conn, lines: db.replace_fuel_lines_since(conn, since, lines))
