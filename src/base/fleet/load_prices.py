# Prices job: pulls the sheets newly posted in the Love's Telegram group, reads every Love's sheet not read before into
# `price_history`, then puts the sheet with the newest price date into `stores`. Each sheet is read once, so dropping
# in many old sheets costs time only the first time.
import logging
from pathlib import Path

from base import config
from base.fleet import mirror
from base.sources import loves, telegram
from base.store import db

log = logging.getLogger(__name__)


# Pulls new sheets from Telegram, adds new sheets to the history and refreshes `stores` from the newest one. Returns True
# when `stores` was refreshed.
def run() -> bool:
    pull_from_telegram()
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


# Saves the sheets posted in the Love's Telegram group since the newest one already in its folder (its message id is in
# the file name). Telegram down or logged out is reported, and the sheets already here are read anyway.
def pull_from_telegram() -> None:
    folder = config.TG_PRICES_DIR
    after = max((int(p.stem[3:]) for p in folder.glob("tg-*.xlsx")), default=0)
    try:
        saved = telegram.save_sheets(config.TG_PRICES_CHAT_ID, after, folder)
    except Exception as error:  # Telegram unreachable or the login gone: the local sheets still count
        log.warning("Love's sheets not pulled from Telegram: %r", error)
        return
    if saved:
        log.info("Love's sheets pulled from Telegram: %d", len(saved))
