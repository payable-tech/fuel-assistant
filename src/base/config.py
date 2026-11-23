# The settings every part shares: file paths, secrets from .env, and the numbers more than one part goes by. A
# feature's own settings are in its settings.py (features/<feature>/settings.py).
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent  # src/base/config.py -> the project folder
DATA_DIR = ROOT / "data"
load_dotenv(ROOT / ".env")

# Datatruck web app login (AWS Cognito). Not secrets: the public settings of Datatruck's own website.
DT_COGNITO_URL = "https://cognito-idp.us-east-2.amazonaws.com/"
DT_COGNITO_CLIENT_ID = "1359ip88mj731hc3psrad2uvof"

# Samsara: one account per motor carrier, each with its token in .env as SAMSARA_API_TOKEN_<name>
SAMSARA_ACCOUNTS = ("TTL", "DT")

# Files
DB_PATH = DATA_DIR / "fuel.db"
PRICES_DIR = DATA_DIR / "love's"
LOG_PATH = DATA_DIR / "fuel.log"
LOG_MAX_MB = 20        # fuel.log starts afresh at this size, the old one kept as fuel.log.1 (a normal day writes ~0.2 MB)
LOG_FILES_KEPT = 4     # old files kept (fuel.log.1 to .4, newest first): at most ~100 MB of log in all
TG_SESSION_PATH = DATA_DIR / "telegram.session"    # the assistant's account (TG_PHONE): sends the messages (test group, live trucks)
TG_GROUPS_SESSION_PATH = DATA_DIR / "bob.session"  # Bob's account: lists the driver groups for linking trucks, until
                                                   # the assistant's account is in them all (then point this above)

# Data freshness
ACTIVE_HOURS = 24          # a truck counts as active (for the holes report) if GPS reported within this

MPG_RANGE = (4.0, 12.0)

# Jobs
STUCK_MIN = 30                     # no progress for this long (a job done or a truck looked at; the longest job takes
                                   # ~17): the program restarts itself
NIGHT_HOURS = (3, 6)               # Central: the slow daily jobs (NIGHTLY in src/timetable.py) run once a night between these
                                   # hours, when the fewest stops are told (user's go, 2026-11-05)
RECENT_FUEL_DAYS = 3

# Heartbeat (base/runner/heartbeat, the user's go 2026-11-19 after the Datatruck login ran out overnight unseen): every few
# minutes, in its own thread, it checks each part and alerts once in Telegram when one breaks and once when it is back.
HEARTBEAT_MIN = 5                  # how often it checks
SOURCE_DOWN_MIN = 30               # a source whose refreshes have failed this long is down (one failed try is a blip)
JOB_LATE_MIN = 45                  # a job not started this long past its time (and 3 of its intervals): the refreshes are behind
GPS_STALE_MIN = 30                 # Samsara's newest truck position older than this: Samsara isn't sending
PURCHASE_STALE_H = 4               # no new fuel purchase in Datatruck for this long, in the day: purchases aren't coming in
PURCHASE_DAY_HOURS = (7, 23)       # ...Central hours when ~6 purchases an hour come in (at night it can be quiet)
PRICE_SHEET_BY = 9                 # Central hour, Mon-Fri, by which the day's Love's price sheet should be in
UNSENT_MIN = 60                    # fuel messages to live trucks not sent in this window: Telegram sending is failing
DOWN_GAP_MIN = 15                  # the heartbeat silent this long before a start: the program (or the PC) was down
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "").strip() or 0) or None  # where alerts go; the test group when unset

# The group "Test fuel": a copy of every recommendation goes here, to see how it looks, sent to the driver or not.
TEST_CHAT_ID = int(os.getenv("TEST_CHAT_ID", "").strip() or 0) or None
# The trucks whose driver gets the messages in their own Telegram group, one by one on the user's go. Every other pilot
# truck stays silent (test group only). 0530 and 14755 since 2026-11-03 morning; on 2026-11-03 ~16:50 UTC the user's
# "mix" of 8 more: the two tested pilots, three trucks that buy most outside Love's, three company drivers. On
# 2026-11-04 ~17:40 UTC batch 2, the user's plan (cover every company driver, bring in lease and owners): 5 company
# drivers, 4 lease drivers who miss the most discount outside Love's, 1 owner-operator. On 2026-11-05 ~17:00 UTC
# batch 3, the user's go: 10 more company drivers (22 of 43 then), those buying outside Love's first, then the most diesel.
# 540201 paused 2026-11-05 ~18:08 UTC: low-fuel messages sent it to two city gas stations in 10 min with Love's Ingalls
# 13 mi ahead, 8 mi off the road (the user's screenshot); back on the user's go.
LIVE_UNITS = ("0530", "14755", "0226", "1553", "51506", "5502", "4482", "516773", "4214",
              "9617", "832206", "252602", "549468", "4217", "19727", "5034",
              "50779", "772209", "209420", "100", "51898", "8829", "1081", "208714",
              "213000", "3346", "50256", "519635", "522774", "555701", "714200", "7273",
              "3526", "11779", "3142", "211183", "19714", "1379", "6501", "6282",
              "555935", "3498", "1693", "1906", "6156", "516122", "554326", "472501", "211250", "286479",
              "773397", "51800", "538376", "4275", "6197", "51916", "211790", "51956", "14684", "772796",
              "520025", "6482", "9595", "19697", "1403", "211146", "4422", "1769", "1526", "4470",
              "5987", "431729", "210336", "101", "228551", "528118", "3715", "208153", "5822", "743148",
              "1827", "760575", "1799", "10", "6250", "211724", "527169", "294179", "404544", "574654",
              "4276", "550516", "772272", "208104", "4191", "1756", "1905", "6268", "526684",
              "211525",
              "513245", "218130", "4615", "14716", "5905", "6135", "3756", "6096", "1767", "202413",
              "6521", "4178", "509269", "1871", "1435", "268331", "1844", "543722", "104", "1794",
              "57685", "555246", "3189", "4169", "266087", "211289", "14734", "775801", "208033", "4596",
              "3068", "4296", "551803", "77299", "211214",
              "3625", "3077", "2030", "4333", "3058", "831648", "1518", "1620", "208103", "5881",
              "309923", "1903", "212530", "6333", "539874", "9606", "101..", "14649", "19704", "3532")
# Batch 10, 2026-11-16 ~14:00 UTC on the user's go ("go, and add only active, real units"): 12 ready once Bob's account
# added Migo to 8 groups (3625 3077 2030 4333 3058 831648 0140 208103), and 8 whose group was linked by hand (set-chat,
# Migo in each; 212530 6333 539874 9606 101.. 14649 19704 3532). All 20 checked active: an active driver in Datatruck,
# in transit or available, GPS within the hour, diesel bought this week. "101.." is Osman Mustaf's DT truck, not the
# TTL "101" above (in the shop). Left out for a doubtful tank size: 0140, 006., 1584.
# Batch 9, 2026-11-13 ~18:15 UTC on the user's go ("go 35"): every truck ready with Migo in its group, 12 that buy 90%
# or more at Love's and, for the first time, 23 that buy less (about 17,200 gal a month outside Love's between them): the
# first test of whether a message moves an outside buyer. 513245 is a substitute truck (its group names unit 541106).
# 211525 (Courtney Jenkins / Omar Sharmake, LO team, new on this truck) live 2026-11-12 ~19:15 UTC on the user's word
# ("need to add this unit"); its new group was linked by hand (set-chat), Migo is in it.
# Batch 8, 2026-11-12 ~18:00 UTC on the user's go ("do we have another 20 ready, time to increase our fleet size"):
# the two ready company trucks (1827, 760575) and 18 lease/LP drivers who already buy 90% or more at Love's, the
# biggest buyers first, as in batch 7; Migo in every group.
# 51871 (TTL: Jean Auguste, LP) paused 2026-11-16 ~15:00 UTC on the user's word ("disconnect this unit"), after two
# messages 8 minutes apart in Oklahoma City (07:53 and 08:01 CT); stays in the pilot, copies go to the test group only.
# 770369 (Bruno Franklin / Adrien Michael, new team and new group) paused 2026-11-12 ~17:00 UTC on the user's word
# ("stop sending to unit 770369"); back on their go.
# Batch 7, 2026-11-11 ~14:00 UTC on the user's go ("prepare another 30, we extend our fleet size"): toward covering the
# whole fleet. 773397 (the last ready company team) and 29 lease/LP/owner drivers on pump-price cards who already buy 91%
# or more at Love's, the biggest buyers first ("better drivers" again); Migo in every group, 8+ gauged fill-ups each.
# Batch 6, 2026-11-10 ~15:30 UTC on the user's go: company 555935, 3498, 1693, 1906 (Migo added by the user); lease/LP on
# invoice cards 6156, 516122, 554326; and LO drivers who benefit most ("not random but better drivers"): 91-100% Love's
# already and fueling near empty (472501 from 1% four times), so the reserve is a safety net for them: 472501, 211250, 286479.
# Batch 5, 2026-11-09 ~13:20 UTC on the user's go: company 3526, 11779, 3142, 211183 (the last two billed as lease on
# pump-price cards until recently) and lease/LP drivers on invoice cards, who keep the Love's discount: 19714, 1379,
# 6501, 6282. 3498 and 1693 (company) wait until Migo is in their groups.
# 6240 (Desire Nkusi) paused 2026-11-07 ~15:45 UTC: 3 stop messages in 37 min on I-40 west of Oklahoma City (OKC,
# El Reno, Hinton) at 17%, his usual level 12%.
# 1901 (Gilbert Fab) paused 2026-11-07 ~03:20 UTC: 3 stop messages in 95 min (Mandeville, Gulfport, Biloxi) at ~30%.
# 528624 (Pernot / Mullings reefer team) paused 2026-11-06 ~19:45 UTC: 3 stop messages in 63 min (El Paso, Anthony,
# Las Cruces) at 35-41%; its usual level (48%, from 8 stops) is above where the team really fuels. Back on the user's go.
# Batch 4, 2026-11-06 ~18:20 UTC on the user's go: every ready company-driver truck (528624 is a SUB for 519903, the
# group is theirs). 3498 waits until Migo is in its group.
# 3464 (Antone Alfonso) paused 2026-11-06 ~16:45 UTC: a stop message every ~40 min (Dickson, Nashville, White House TN)
# at 37% after his card failed at Love's Jackson and he said he would fuel later; back on the user's go.
# 751850 (Gino Jean) paused 2026-11-05 ~18:50 UTC on the user's word ("stop this unit for now"); back on their go.


# Returns a required secret from .env, failing loudly with its name if it is missing.
def secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value
