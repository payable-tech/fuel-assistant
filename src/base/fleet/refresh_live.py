# Live job: copies every truck's latest Samsara GPS point and fuel level into `samsara_live`.
from base.fleet import mirror
from base.sources import samsara
from base.store import db


# Replaces the live copy. Returns True when it was refreshed.
def run() -> bool:
    return mirror.refresh("Samsara live", samsara.live, db.replace_samsara_live)
