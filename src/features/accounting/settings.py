# Accounting's settings: where the EFS statements are, which accounts they are for, and how Samsara's evidence for a
# statement's fills is looked up.
from base import config

STATEMENTS_DIR = config.DATA_DIR / "efs"                  # EFS weekly statement PDFs, saved here by hand (one per account per week)
# Each EFS account (its name on page 1 of its statements) and the Datatruck companies whose cards are on it. The user,
# 2026-11-19: fuel is paid only through EFS, on these two accounts. The Accounting view looks for Datatruck lines of
# these companies that are on no statement line. The DT National name is a guess until its first text statement.
EFS_ACCOUNTS = {
    "ALIF UZ CORP": ("TAYLOR TRANSPORTS LLC", "VKL TRUCKING INC", "ALIF UZ CORP"),
    "DT NATIONAL TRANSPORTATION LLC": ("DT National Transportation LLC",),
}

# Samsara's evidence for a statement's fills (features/accounting/statement_evidence)
EVIDENCE_TRUCKS_PER_RUN = 10       # ~50 fills, two small Samsara calls each (~1 s a fill): about a minute, so the engine
                                   # keeps its turn
EVIDENCE_BEFORE_H = 4              # a fill's gauge rise is looked for from this long before Datatruck's time (its time
EVIDENCE_AFTER_H = 1               # can be hours late, api-data-findings 2026-10-22) to this long after
EVIDENCE_PARKED_H = 24             # readings this far back are fetched too: a truck parked engine-off sends none, so its
                                   # level before the fill is its last reading before the window
GAUGE_FRESH_DAYS = 3               # a gauge reading older than this at a statement's start or end is not that day's level
