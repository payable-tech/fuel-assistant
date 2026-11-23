# All settings in one place: file paths, secrets from .env, and the tunable numbers.
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent  # src/base/config.py -> the project folder
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
load_dotenv(ROOT / ".env")

# Datatruck web app login (AWS Cognito). Not secrets: the public settings of Datatruck's own website.
DT_COGNITO_URL = "https://cognito-idp.us-east-2.amazonaws.com/"
DT_COGNITO_CLIENT_ID = "1359ip88mj731hc3psrad2uvof"

# Samsara: one account per motor carrier, each with its token in .env as SAMSARA_API_TOKEN_<name>
SAMSARA_ACCOUNTS = ("TTL", "DT")

# Dashboard
DASHBOARD_HOST = "0.0.0.0"  # "0.0.0.0": other PCs on this network can open it too; "127.0.0.1": this PC only
# Who may open it: this PC and private office networks. Not the Radmin VPN (26.x), which this PC is also on, with
# Windows Firewall off; the dashboard has no login, so its address alone must not be enough from outside the office.
DASHBOARD_NETWORKS = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
DASHBOARD_PORT = 8050
BASELINE_WEEKS = 26        # weeks of history the dashboard shows
BREAKDOWN_WEEKS = 4        # recent full weeks the breakdown tables cover

# Files
DB_PATH = DATA_DIR / "fuel.db"
PRICES_DIR = DATA_DIR / "love's"
TG_PRICES_CHAT_ID = -5551908421                    # Telegram group "Love's Daily Prices": one Love's sheet a day (user, 2026-11-20)
TG_PRICES_DIR = PRICES_DIR / "telegram"            # its sheets, pulled by the prices job as tg-<message id>.xlsx
STATEMENTS_DIR = DATA_DIR / "efs"                  # EFS weekly statement PDFs, saved here by hand (one per account per week)
# Each EFS account (its name on page 1 of its statements) and the Datatruck companies whose cards are on it. The user,
# 2026-11-19: fuel is paid only through EFS, on these two accounts. The Accounting view looks for Datatruck lines of
# these companies that are on no statement line. The DT National name is a guess until its first text statement.
EFS_ACCOUNTS = {
    "ALIF UZ CORP": ("TAYLOR TRANSPORTS LLC", "VKL TRUCKING INC", "ALIF UZ CORP"),
    "DT NATIONAL TRANSPORTATION LLC": ("DT National Transportation LLC",),
}
# eManager, the EFS website, for fuel cards (features/cards/efs_*.py, the way bob-agent reaches it). It runs in its own Chrome
# window, since its bot check lets only a real browser through.
EMANAGER_CHROME_PORT = 9224                 # Chrome listens on this local port only
EMANAGER_PROFILE = DATA_DIR / "efs-chrome"  # that window's own Chrome profile, apart from anyone's own Chrome
EMANAGER_HEARTBEAT_SECONDS = 240            # eManager logs out after 90 idle minutes; every login ends after 24 hours
# The eManager user that acts for each account; one login switches between them. Bob's login: card work moved here
# from bob-agent, which no longer uses it (the user, 2026-11-22).
EMANAGER_USERS = {"ALIF": "Bobalif", "DT": "BOB_DT"}
# Each account's card policies. Listing every card is one lookup per policy: eManager's "All Cards" finds nothing.
EMANAGER_POLICIES = {"ALIF": ("1", "2"), "DT": ("1",)}
LOG_PATH = DATA_DIR / "fuel.log"
LOG_MAX_MB = 20        # fuel.log starts afresh at this size, the old one kept as fuel.log.1 (a normal day writes ~0.2 MB)
LOG_FILES_KEPT = 4     # old files kept (fuel.log.1 to .4, newest first): at most ~100 MB of log in all
TG_SESSION_PATH = DATA_DIR / "telegram.session"    # the assistant's account (TG_PHONE): sends the messages (test group, live trucks)
TG_GROUPS_SESSION_PATH = DATA_DIR / "bob.session"  # Bob's account: lists the driver groups for linking trucks, until
                                                   # the assistant's account is in them all (then point this above)

# The card agent (features/cards/job, the user's go 2026-11-23): wakes when the assistant's account is tagged in a driver
# group, reads the chat, and when the driver needs his fuel card opened, opens it for one fill and tells him to try
# again, the way Bob does. Its own Telegram login on the same account, apart from the engine's (one login file can't be
# opened twice); `main.py agent-login` makes it once.
# Which account it is: its login file, and the phone its login code goes to. The assistant's account (TG_PHONE) when
# unset; the user, 2026-11-23: test on Bob's account first (AGENT_SESSION=agent-bob.session), switch to Migo later.
AGENT_SESSION_PATH = DATA_DIR / (os.getenv("AGENT_SESSION", "").strip() or "agent.session")
AGENT_PHONE = os.getenv("AGENT_PHONE", "").strip() or None
AGENT_MODEL = "claude-opus-5-5"
AGENT_EFFORT = "medium"
AGENT_ACT = True           # False: it decides and reports to the office, but opens no card and answers no driver
AGENT_HISTORY = 10         # messages of the chat it reads, the one that tagged it included
AGENT_MAX_PHOTOS = 3       # the newest photos among them it looks at (a declined receipt, a pump screen)
AGENT_OPEN_FILLS = 1       # an opening lasts this many transactions, always All Locations (features/cards/efs_cards)
AGENT_REOPEN_HOURS = 6     # a card it opened isn't opened again by it sooner: the office decides then
AGENT_OFFICE_CHAT_ID = int(os.getenv("AGENT_OFFICE_CHAT_ID", "").strip() or 0) or None  # its reports; the test group when unset
# A group that plays a truck's group with a fabricated truck, driver and card (features/cards/efs_fake): nothing real is read
# or changed for it. AGENT_TEST_ONLY=1 makes the agent ignore every other group (and skip the eManager window).
AGENT_TEST_CHAT_ID = int(os.getenv("AGENT_TEST_CHAT_ID", "").strip() or 0) or None
AGENT_TEST_ONLY = os.getenv("AGENT_TEST_ONLY", "").strip() == "1"

# Data freshness
ACTIVE_HOURS = 24          # a truck counts as active (for the holes report) if GPS reported within this

# Fuel recommendation (features/engine/recommend): the hard rule, the driver's level, then money
RESERVE_PCT = 10           # never plan to arrive under this at the cautious MPG
WORSE_MPG = 0.85           # the cautious MPG: the lower of average and live, 15% worse (the user's pick, 2026-11-02)
ABOVE_USUAL_PTS = 1        # a stop reached more than this above the driver's usual level gets ignored (2-17% fuel there).
                           # Was 5 until 2026-11-16 (the user's word): stops told 5+ points above the usual level were
                           # driven past twice as often, and drivers who passed fueled 12 points lower than we told
LOOK_MI = 60               # the driver is told when the stop is this close: until then the choice stays open, and the
                           # closer it is made, the better the estimate (2026-11-02, was 150)
# A Love's stop is always a fill-up (the user's go, 2026-11-11: of 12 part fills told, none was bought as asked). Only a
# truck stop standing in for a Love's out of reach still asks for part of a tank.
PART_GAP_USD = 0.50        # a Love's ahead this much cheaper, also at the pump, is marked on the plan's regions
PART_REACH_MI = 500        # ...when at most this far past the stop
PART_MIN_GAL = 30          # at a truck stop before a Love's: buy at least this
PART_MARGIN_GAL = 25       # ...and at least this less than a fill-up, or it isn't worth asking
MAX_PASSED = 2             # after this many stops told and driven past on one tank, no more are told until the last
                           # Love's in reach or low fuel (the user's go, 2026-11-11: of 23 third-or-later messages, 1 was followed)
LAST_PCT = 3               # a Love's reached with less than this in the worst case is out of reach: the emergency starts past the last one
URGENT_PCT = 25            # with no Love's to count on, the truck stop backup starts at this gauge level
LOW_FUEL_ALARM = False     # the low-fuel message (a truck stop that isn't a Love's, or "find the nearest truck stop") is
                           # off: the truck still shows as urgent on the page, nothing is told or recorded (the user's
                           # word, 2026-11-13, "we will work on that or remove later": 1 of 20 was followed)
LOW_PENALTY_USD = 5        # dollars a stop loses per point it is reached below the driver's range
DEFAULT_MPG = 6.5          # used when Samsara MPG is missing or outside MPG_RANGE
USUAL_MIN_STOPS = 5        # fewer gauged stops: the driver's usual level isn't known
DEFAULT_USUAL = (22, 15, 30, 95)  # ...and these are used: the fleet's middle (usual, low, high, fill)
GAUGE_STEADY_MIN = 10      # the fuel now is the middle of the gauge readings of this many minutes: the gauge wobbles ~3 points
GAUGE_MIN_READINGS = 5     # ...but at least this many, looking back up to GAUGE_LOOKBACK_MIN: a stopped truck reports rarely
GAUGE_LOOKBACK_MIN = 60
GAUGE_FRESH_MIN = 30       # an older gauge reading can't be recommended on
FILL_RISE_PCT = 8          # a gauge rise this big means fuel was bought
FUEL_HOLD_MIN = 60         # ...and no new message for this long after it: the fill may still be going on (the user's go,
                           # 2026-11-04, after 14755 got its stop again at the pump, its gauge half way up)
NEAR_STOP_MI = 2           # a stop closer than this isn't told: the driver is already there. Low fuel is told anyway
PARKED_MIN = 15            # a truck that moved less than PARKED_MI in this many minutes is parked: its stop waits
PARKED_MI = 1              # ...till it moves (told at 08:18 while parked, 540201 passed it 3 h later; user's go 2026-11-05)
STOP_REACHED_MI = 1.0      # a load's stop is done once the truck's GPS has been this close to it
VISIT_WINDOW_H = 24        # ...counting only visits from this long before the pickup appointment (not earlier loads)
LOAD_MAX_DAYS = 10         # a load picked up longer ago than this is over, whatever Datatruck still shows
CORRIDOR_MI = 1.5          # Love's farther than this (straight line) from the road are not considered
ROUTE_STEP_MI = 0.5        # the road is cut into pieces this short to find the stores along it
LINE_STEP_MI = 0.1         # a saved road keeps points at least this far apart (same line, fewer points)
OFF_ROAD_MI = 5            # a truck this far from its road has gone another way: a new road is made
REROUTE_MIN = 60           # ...at most this often
TRUCK_STOP_OFF_MI = 2      # no Love's in reach: real truck stops this close to the road ahead count
RECOMMEND_DAYS = 14        # the dashboard lists recommendations of this many days
RECOMMEND_FROM = "2026-11-02"  # ...and the fills no message asked for from this day, the engine's first
NEARBY_MI = 10             # Love's this close to the road, though off it: counted, with the way there, when none on the
                           # road is in reach, before low fuel (540201, Ingalls IN, user's go 2026-11-05); on the map too
DETOUR_ROAD_FACTOR = 1.3   # the road to a Love's off the road is about this much longer than the straight line
# A truck with no load (features/engine/no_load, the user's go 2026-11-18): once its fuel is down to the driver's usual level, the
# nearest Love's ahead in the direction it is going is told, like any stop (within LOOK_MI, held while parked)
HEADING_MI = 10            # its direction: from where its GPS was this many miles back to where it is now
HEADING_MAX_MIN = 30       # ...driven within this many minutes: the miles before a stop say nothing of the way after it
# Never a Love's behind the driver (the user's go, 2026-11-22: 1767 told Love's he had passed, down to 4% on I-30). The
# stops told Nov 15-22 that lay behind the truck were 151-180 degrees off its way; of 331 good ones, 3 were over 135.
BEHIND_DEG = 135           # a place more than this off the truck's way lies behind it
ROAD_AHEAD_MI = 20         # the load's road this far on from the truck shows where it goes: behind him, the road is wrong
                           # (a load in Datatruck he isn't driving makes a road that starts with a U-turn), and the
                           # nearest Love's ahead in his direction is told instead, as for a truck with no load
AHEAD_CONE_DEG = 45        # a Love's counts as ahead when it lies within this many degrees of that direction, either side.
                           # Replay on 251 no-load Love's fills made while driving (Oct 1-Nov 17): from 30 mi before the
                           # Love's he used, our nearest ahead was that one 66% of the time (15 mi / 30 degrees: 57%)
MAP_STEP_MI = 0.25         # roads go to the map with points at least this far apart
EXITS_PAUSE_SEC = 1        # between two Love's store pages read for their highway and exit: 608 stores take ~10 min, once
LINK_MAX_VIA = 3          # stops on the way in a message's link: Google's limit on mobile browsers
RESULT_WINDOW_H = 48       # the truck's first diesel stop this soon after a recommendation is what became of it

# Live MPG (features/engine/burn): the engine as a fuel meter
LIVE_MPG_HOURS = 3         # how the truck runs "now": over this many hours
LIVE_MIN_MILES = 25        # ...with at least these miles driven in them
BURN_DAYS = 14             # each truck is calibrated on this many days
BURN_STRETCH_MI = 250      # ...of gauge drops over stretches this long
BURN_MIN_STRETCHES = 3     # fewer: no factor, the truck's live MPG stays unknown

# Driver habits: how each driver usually fuels, from their diesel stops and the Samsara gauge around them
HABIT_DAYS = 30            # stops of the last this many days
HABIT_MAX_FAILED = 0.2     # more than this share of trucks without gauge readings: the old copy is kept
RAN_LOW_PCT = 10           # a stop that began below this gauge level "ran low"
TOP_OFF_GAL = 50           # a stop buying less than this is a top-off

# Fleet status (the top of the Drivers tab)
FLEET_FUELED_DAYS = 14     # a truck with no card assigned that bought fuel within this many days is shown apart

MPG_RANGE = (4.0, 12.0)

# Tank helper: tank = gallons bought ÷ how far the Samsara fuel gauge rose (middle value over recent fill-ups),
# but never less than what the tank has been seen to hold
TANK_DAYS = 30             # fill-ups of the last this many days are used
TANK_WINDOW_MIN = 120      # gauge readings this long before/after a purchase count; purchases closer than this are one stop
TANK_MIN_RISE_PCT = 25     # smaller gauge rises are too noisy to use
TANK_MIN_FILLS = 3         # fewer usable fill-ups -> no estimate (the truck shows in `holes`)

# Schedule, in minutes
STUCK_MIN = 30                     # no progress for this long (a job done or a truck looked at; the longest job takes
                                   # ~17): the program restarts itself
NIGHT_HOURS = (3, 6)               # Central: the slow daily jobs (scheduler.NIGHT_JOBS) run once a night between these
                                   # hours, when the fewest stops are told (user's go, 2026-11-05)
EVERY_LIVE_MIN = 5                 # Samsara position and fuel level of every truck
EVERY_ORDERS_MIN = 15
EVERY_PRICES_MIN = 30
EVERY_STATEMENTS_MIN = 30          # new EFS statement PDFs in data/efs
EVERY_EVIDENCE_MIN = 15            # Samsara evidence for the statements' fills, a few trucks at a time
EVIDENCE_TRUCKS_PER_RUN = 10       # ~50 fills, two small Samsara calls each (~1 s a fill): about a minute, so the engine
                                   # keeps its turn
EVIDENCE_BEFORE_H = 4              # a fill's gauge rise is looked for from this long before Datatruck's time (its time
EVIDENCE_AFTER_H = 1               # can be hours late, api-data-findings 2026-10-22) to this long after
EVIDENCE_PARKED_H = 24             # readings this far back are fetched too: a truck parked engine-off sends none, so its
                                   # level before the fill is its last reading before the window
GAUGE_FRESH_DAYS = 3               # a gauge reading older than this at a statement's start or end is not that day's level
EVERY_RECENT_FUEL_MIN = 15         # just the last few days, for the live view
EVERY_RECOMMEND_MIN = 5            # silent fuel recommendations for the pilot trucks
EVERY_BURN_MIN = 24 * 60           # engine fuel factors
EVERY_LOOKUP_MIN = 15              # where new fills outside Love's were, the gauge before
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

# Live view
LIVE_FEED_SIZE = 30                # newest purchases listed
LIVE_DAYS = 14                     # days in the day-by-day chart
LIVE_OUTSIDE_LIMIT = 12            # drivers listed under "outside Love's this week"
DISCOUNT_DAYS, DISCOUNT_WEEKS, DISCOUNT_MONTHS = 15, 13, 7  # the discount chart's periods by day / week / month: the
                                  # one in progress (the figures above it) and 14 days, 12 weeks, 6 months finished

# Paid above the cheapest Love's nearby (Live's outside list): a fill against the lowest Love's price
# within NEAR_MI that day. Straight line around where the truck was: the road ahead isn't known, so it is a ceiling.
NEAR_MI = 25
SHEET_MAX_AGE_DAYS = 3             # ...on the newest Love's price sheet at most this old (the sheets have gaps)

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
LIVE_FROM = "2026-11-03"           # the first day a driver got a message: the Live tab counts the plans from here
LOVES_TARGET = 0.999               # the share of the fleet's diesel to buy at Love's, the goal
LOOKUPS_FROM = "2026-09-28"        # fills outside Love's are looked up from this day on


# Returns a required secret from .env, failing loudly with its name if it is missing.
def secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value
