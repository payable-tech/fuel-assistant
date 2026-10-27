# Live job: copies every truck's latest Samsara GPS point and fuel level into `samsara_live`.
import db
from jobs import mirror
from sources import samsara


# Replaces the live copy. Returns True when it was refreshed.
def run() -> bool:
    return mirror.refresh("Samsara live", samsara.live, db.replace_samsara_live)
