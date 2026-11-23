# The card agent's settings: the eManager window it works in, and the agent itself (its Telegram login, its Claude
# model, what it may do). Its secrets come from .env, which base/config loads.
import os

from base import config

# eManager, the EFS website, for fuel cards (features/cards/emanager/, the way bob-agent reaches it). It runs in its own Chrome
# window, since its bot check lets only a real browser through.
EMANAGER_CHROME_PORT = 9224                 # Chrome listens on this local port only
EMANAGER_PROFILE = config.DATA_DIR / "efs-chrome"  # that window's own Chrome profile, apart from anyone's own Chrome
EMANAGER_HEARTBEAT_SECONDS = 240            # eManager logs out after 90 idle minutes; every login ends after 24 hours
# The eManager user that acts for each account; one login switches between them. Bob's login: card work moved here
# from bob-agent, which no longer uses it (the user, 2026-11-22).
EMANAGER_USERS = {"ALIF": "Bobalif", "DT": "BOB_DT"}
# Each account's card policies. Listing every card is one lookup per policy: eManager's "All Cards" finds nothing.
EMANAGER_POLICIES = {"ALIF": ("1", "2"), "DT": ("1",)}

# The card agent (features/cards/job, the user's go 2026-11-23): wakes when the assistant's account is tagged in a driver
# group, reads the chat, and when the driver needs his fuel card opened, opens it for one fill and tells him to try
# again, the way Bob does. Its own Telegram login on the same account, apart from the engine's (one login file can't be
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
AGENT_REOPEN_HOURS = 6     # a card it opened isn't opened again by it sooner: the office decides then
AGENT_OFFICE_CHAT_ID = int(os.getenv("AGENT_OFFICE_CHAT_ID", "").strip() or 0) or None  # its reports; the test group when unset
# A group that plays a truck's group with a fabricated truck, driver and card (features/cards/emanager/fake_cards): nothing real is read
# or changed for it. AGENT_TEST_ONLY=1 makes the agent ignore every other group (and skip the eManager window).
AGENT_TEST_CHAT_ID = int(os.getenv("AGENT_TEST_CHAT_ID", "").strip() or 0) or None
AGENT_TEST_ONLY = os.getenv("AGENT_TEST_ONLY", "").strip() == "1"
