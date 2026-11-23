# Prices job: reads every Love's sheet in data/love's/ not read before into `price_history`, then puts the sheet with
# the newest price date into `stores`. Each sheet is read once, so dropping in many old sheets costs time only the
# first time.
import logging
from pathlib import Path

from base.fleet import mirror
from base.sources import loves
from base.store import db

log = logging.getLogger(__name__)


# Adds new sheets to the history and refreshes `stores` from the newest one. Returns True when `stores` was refreshed.
def run() -> bool:
    with db.connect() as conn:
        known = db.price_files(conn)
    added = 0
    for path in loves.sheets():
        stat = path.stat()
        if known.get(str(path)) == (stat.st_size, stat.st_mtime):
            continue  # read before and unchanged
        try:
            stores = loves.stores(path)
        except ValueError as bad:  # e.g. a sheet missing columns: report it, keep reading the others
            log.warning("Price sheet not read: %s", bad)
            continue
        with db.connect() as conn:
            db.add_price_sheet(conn, str(path), stat.st_size, stat.st_mtime, stores)
        added += 1
    if added:
        log.info("Price history: %d new sheets read", added)
    with db.connect() as conn:
        newest = db.newest_price_file(conn)
    return newest is not None and mirror.refresh("Love's stores", lambda: loves.stores(Path(newest)), db.replace_stores)
