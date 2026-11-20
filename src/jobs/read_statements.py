# Statements job: reads every EFS statement PDF in data/efs not read before (a changed file is read again) into
# efs_statements and efs_lines. A file that isn't a readable statement is reported in the log and skipped.
import logging

import db
from sources import efs_statement

log = logging.getLogger(__name__)


# Reads the new and changed statement files. Returns how many were read.
def run() -> int:
    with db.connect() as conn:
        known = db.statement_files(conn)
    added = 0
    for path in efs_statement.files():
        stat = path.stat()
        if known.get(str(path)) == (stat.st_size, stat.st_mtime):
            continue  # read before and unchanged
        try:
            statement, lines = efs_statement.read(path)
        except ValueError as bad:  # e.g. a scanned copy: report it, keep reading the others
            log.warning("EFS statement not read: %s", bad)
            continue
        with db.connect() as conn:
            db.add_statement(conn, str(path), stat.st_size, stat.st_mtime, statement, lines)
        log.info("EFS statement %s (%s, %s) read: %d lines, $%.2f", statement.statement_no, statement.account,
                 statement.statement_day, len(lines), statement.charges)
        added += 1
    return added
