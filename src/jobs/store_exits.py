# Love's exits job: reads the own page of each Love's store not read yet (sources/loves_web) and keeps its highway and
# exit in `store_exits`, for the driver's message ("📍 In 34 mi, I-90 (Exit 34)"). A store is read once: after the
# first run (all stores, ~10 min) only new stores are.
import logging
import time

import config
import db
from sources import loves_web

log = logging.getLogger(__name__)
MAX_FAILS = 5  # this many pages in a row that can't be read: the site is down or changed, the rest waits for the next run


# Reads the pages still missing. A page that can't be read is tried again at the next run. Returns how many were kept.
def run() -> int:
    with db.connect() as conn:
        todo = db.stores_without_exit(conn)
    kept = fails = 0
    for store_no in todo:
        try:
            way = loves_web.exit_of(store_no)
        except Exception as error:
            log.warning("Love's page of store %s not read: %r", store_no, error)
            fails += 1
            if fails >= MAX_FAILS:
                break
        else:
            fails = 0
            with db.connect() as conn:
                db.save_store_exit(conn, store_no, way)
            kept += 1
        time.sleep(config.EXITS_PAUSE_SEC)
    if todo:
        log.info("Love's exits read: %d of %d stores", kept, len(todo))
    return kept
