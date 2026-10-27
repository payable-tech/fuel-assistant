# Fuel jobs: the full copy of every Datatruck fuel line and card, and a cheap copy of just the last few days.
from datetime import date, timedelta

import config
import db
from jobs import mirror
from sources import datatruck_web


# Refreshes the fuel lines and fuel cards copies in full (a few minutes; catches late edits to older lines).
def run() -> None:
    mirror.refresh("Datatruck fuel lines", datatruck_web.fuel_lines, db.replace_fuel_lines)
    mirror.refresh("Datatruck fuel cards", datatruck_web.fuel_cards, db.replace_fuel_cards)


# Refreshes only the last RECENT_FUEL_DAYS days of fuel lines (seconds), which is what the live view needs.
def run_recent() -> None:
    since = (date.today() - timedelta(days=config.RECENT_FUEL_DAYS)).isoformat()
    mirror.refresh("Datatruck fuel lines, last days", lambda: datatruck_web.fuel_lines_since(since),
                   lambda conn, lines: db.replace_fuel_lines_since(conn, since, lines))
