# The card agent's settings: the eManager window it works in, and the agent itself (its Telegram login, its Claude
# model, what it may do). Its secrets come from .env, which base/config loads.
import os
from datetime import datetime, timezone

from base import config

# eManager, the EFS website, for fuel cards (features/cards/emanager/, the way bob-agent reaches it). It runs in its own Chrome
# window, since its bot check lets only a real browser through.
EMANAGER_CHROME_PORT = 9224                 # Chrome listens on this local port only
EMANAGER_PROFILE = config.DATA_DIR / "efs-chrome"  # that window's own Chrome profile, apart from anyone's own Chrome
EMANAGER_HEARTBEAT_SECONDS = 240            # eManager logs out after 90 idle minutes; every login ends after 24 hours
EFS_COPY_MINUTES = 30                       # how often EFS's whole card list is copied into the database (card_list)
EFS_PAGE_HOURS = 3                          # ...and how often each card in use has its own page read again
# What a parked card carries: the card cleanup's rule (the user, 2026-11-24), also how the dashboard tells one.
PARKED_PROMPTS = {"unit": "99999", "driver-id": "99999", "driver": "ALIF UZ CORP"}
# The eManager user that acts for each account; one login switches between them. Bob's login: card work moved here
# from bob-agent, which no longer uses it (the user, 2026-11-22).
EMANAGER_USERS = {"ALIF": "Bobalif", "DT": "BOB_DT"}
# Each account's card policies. Listing every card is one lookup per policy: eManager's "All Cards" finds nothing.
EMANAGER_POLICIES = {"ALIF": ("1", "2"), "DT": ("1",)}

# The card agent (features/cards/agent, the user's go 2026-11-23): wakes when the assistant's account is tagged in a driver
# group, reads the chat, and when the driver asks about his fuel card, opens it for one fill at any location and tells
# him to try again, without the office (the user, 2026-11-24). Its own Telegram login on the same account, apart from the engine's (one login file can't be
# opened twice); `main.py agent-login` makes it once.
# Which account it is: its login file, and the phone its login code goes to. The assistant's account (TG_PHONE) when
# unset; the user, 2026-11-23: test on Bob's account first (AGENT_SESSION=agent-bob.session), switch to Migo later.
AGENT_SESSION_PATH = config.DATA_DIR / (os.getenv("AGENT_SESSION", "").strip() or "agent.session")
AGENT_PHONE = os.getenv("AGENT_PHONE", "").strip() or None
AGENT_MODEL = "claude-opus-5-5"
AGENT_EFFORT = "medium"
AGENT_ACT = True           # False: it decides and reports to the office, but opens no card and answers no driver
AGENT_HISTORY = 10         # messages of the chat it reads, the one that tagged it included
AGENT_MAX_PHOTOS = 3       # the newest photos among them it looks at (a declined receipt, a pump screen)
AGENT_OPEN_FILLS = 1       # an opening lasts this many transactions, always All Locations (features/cards/emanager/fuel_cards)
AGENT_REPEAT_HOURS = 24    # opening a card it already opened this recently is marked as a repeat in the office report
# It does this many real jobs (requests it used a tool for) counted from AGENT_JOBS_SINCE, then leaves every later
# request to the office. None means no limit: the user, 2026-11-24, after the first five ("remove the card agent
# limit"). For a batch again set a number, move AGENT_JOBS_SINCE to now (UTC) and restart the agent.
AGENT_MAX_JOBS = None
AGENT_JOBS_SINCE = datetime(2026, 11, 24, 11, 45, tzinfo=timezone.utc)  # 06:45 on this PC's clock (Eastern)
AGENT_OFFICE_CHAT_ID = int(os.getenv("AGENT_OFFICE_CHAT_ID", "").strip() or 0) or None  # its reports; the test group when unset
# A group that plays a truck's group with a fabricated truck, driver and card (features/cards/emanager/fake_cards): nothing real is read
# or changed for it. AGENT_TEST_ONLY=1 makes the agent ignore every other group (and skip the eManager window).
AGENT_TEST_CHAT_ID = int(os.getenv("AGENT_TEST_CHAT_ID", "").strip() or 0) or None
AGENT_TEST_ONLY = os.getenv("AGENT_TEST_ONLY", "").strip() == "1"

# The card checker (features/cards/card_check, the user's go 2026-11-26): three times a day (Windows' Task Scheduler,
# run_checker.bat) it reads each ACTIVE card's truck group and says whether the card should be on. Only reads.
CHECKER_SESSION_PATH = config.DATA_DIR / "checker-bob.session"  # its own login on Bob's account (`main.py checker-login`)
CHECK_MESSAGES = 40        # the group's latest messages it reads, whatever their age: a busy group's last hours, a
                           # quiet group's last weeks (the user, 2026-11-26)
CHECK_SCAN = 200           # ...looked for among at most this many (bots' posts are skipped)
CHECK_MODEL = "claude-sonnet-5-5"  # the user's pick, 2026-11-26: ~600 checks a day on the plan
CHECK_EFFORT = "medium"

# The replay (features/cards/replay) plays real driver cases to the agent against the real eManager. The one card it
# may change is the user's own test card, parked on unit 99999 as ALIF UZ CORP, INACTIVE (the user, 2026-11-22).
TEST_CARD_ACCOUNT = "ALIF"
TEST_CARD_ID = "1000085144314"     # eManager's id of the card ending 0672
TEST_CARD_UNIT = "99999"
