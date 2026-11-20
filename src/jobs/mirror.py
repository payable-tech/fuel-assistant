# Refreshes one source copy in the DB. A failed or empty fetch keeps the previous copy instead of wiping it, and every
# try is recorded in source_health, so a source that keeps failing is seen (the heartbeat alerts on it).
import logging
from datetime import datetime, timezone

import db

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
