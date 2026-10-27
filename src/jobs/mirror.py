# Refreshes one source copy in the DB. A failed or empty fetch keeps the previous copy instead of wiping it.
import logging

import db

log = logging.getLogger(__name__)


# Fetches rows from a source and replaces its table whole. Returns True when the copy was refreshed.
def refresh(name: str, fetch, write) -> bool:
    try:
        rows = fetch()
        if not rows:
            raise ValueError("source returned no rows")
    except Exception as error:  # a source being down must not stop the other refreshes
        log.warning("%s not refreshed, keeping the previous copy: %r", name, error)
        return False
    with db.connect() as conn:
        write(conn, rows)
    log.info("%s refreshed: %d rows", name, len(rows))
    return True
