# All settings in one place: file paths, secrets from .env, and the tunable alert and planner numbers.
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
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
LOG_PATH = DATA_DIR / "fuel.log"
TG_SESSION_PATH = DATA_DIR / "telegram.session"    # the assistant's account (TG_PHONE): sends the messages
TG_GROUPS_SESSION_PATH = DATA_DIR / "bob.session"  # Bob's account: lists the driver groups for linking trucks, until
                                                   # the assistant's account is in them all (then point this above)

# Data freshness
ACTIVE_HOURS = 24          # a truck counts as active (for the holes report) if GPS reported within this

# Planner: which Love's along a load's route, and how many gallons at each, for the lowest total cost
RESERVE_PCT = 10           # the plan never lets the tank drop below this much fuel
CORRIDOR_MI = 1.5          # Love's farther than this (straight line) from the route are not considered
DETOUR_FACTOR = 2.6        # road miles to a Love's and back per straight-line mile off the route (1.3 each way)
END_MIN_GAL = 40           # aim to reach the load's last stop with this much (the next load's start), else the reserve
STATION_OFF_MI = 5         # no Love's in reach: other stations this close to the road ahead count (Google Places)
MIN_BUY_GAL = 30           # a planned stop buys at least this much (drivers may not stop for less; a hunch for now)
STOP_COST_USD = 40         # what one more stop costs (driver time, wear), so the plan doesn't stop needlessly
FUEL_STEP_GAL = 5          # fill-up amounts are planned in steps of this many gallons
ROUTE_STEP_MI = 0.5        # the route line is cut into pieces this short to find the stores along it
STOP_REACHED_MI = 1.0      # a load's stop is done once the truck's GPS has been this close to it
VISIT_WINDOW_H = 24        # ...counting only visits from this long before the pickup appointment (not earlier loads)
PLAN_LINE_STEP_MI = 0.1    # a saved plan keeps its road with points at least this far apart (same line, fewer points)

# Driver habits: how each driver usually fuels, from their diesel stops and the Samsara gauge around them
HABIT_DAYS = 30            # stops of the last this many days
RAN_LOW_PCT = 10           # a stop that began below this gauge level "ran low"
TOP_OFF_GAL = 50           # a stop buying less than this is a top-off

# Plans view
TRACK_STEP_MI = 0.2        # the road a truck drove is sent to the map with points at least this far apart
PLANS_DAYS = 14            # plans made in the last this many days are listed
DEFAULT_MPG = 6.5          # used when Samsara MPG is missing or outside MPG_RANGE
MPG_RANGE = (4.0, 12.0)

# Tank helper: tank = gallons bought ÷ how far the Samsara fuel gauge rose (middle value over recent fill-ups),
# but never less than what the tank has been seen to hold
TANK_DAYS = 30             # fill-ups of the last this many days are used
TANK_WINDOW_MIN = 120      # gauge readings this long before/after a purchase count; purchases closer than this are one stop
TANK_MIN_RISE_PCT = 25     # smaller gauge rises are too noisy to use
TANK_MIN_FILLS = 3         # fewer usable fill-ups -> no estimate (the truck shows in `holes`)

# Schedule, in minutes
STUCK_MIN = 30                     # no job finished for this long (the longest takes ~5): the program restarts itself
EVERY_LIVE_MIN = 5                 # Samsara position and fuel level of every truck
EVERY_TANKS_MIN = 24 * 60          # tank helper
EVERY_PLAN_MIN = 5                 # planner: plans each pilot truck's new load, keeps sent messages current
EVERY_HABITS_MIN = 24 * 60         # every driver's stops with the gauge (one Samsara call per truck, a few minutes)
EVERY_ORDERS_MIN = 15
EVERY_PRICES_MIN = 30
EVERY_SYNC_MIN = 24 * 60
EVERY_FUEL_LINES_MIN = 24 * 60     # full copy of every fuel line, catches late edits to old lines
EVERY_RECENT_FUEL_MIN = 15         # just the last few days, for the live view
EVERY_MARKET_MIN = 24 * 60         # EIA market prices: a new week appears each Monday
RECENT_FUEL_DAYS = 3

# Live view
LIVE_FEED_SIZE = 30                # newest purchases listed
LIVE_DAYS = 14                     # days in the day-by-day chart
LIVE_OUTSIDE_LIMIT = 12            # drivers listed under "outside Love's this week"

# Shadow mode: every plan message is sent to this chat ("Test fuel"). Empty: nothing is sent.
TEST_CHAT_ID = int(os.getenv("TEST_CHAT_ID", "").strip() or 0) or None
LIVE_UNITS: tuple[str, ...] = ("0226", "555701", "3068")  # units whose drivers get their plan messages too, in their own group
SEND_WITHIN_MIN = 60       # a plan's message not sent this long after the plan was made is dropped: the truck moved on
FOLLOW_DAYS = 5            # a plan is followed (a message per major event) for at most this long
MISSED_AFTER_MIN = 60      # a planned stop passed this long ago with no fuel line from it counts as missed
MISSED_QUICK_MIN = 15      # ...already this long after leaving when the gauge since shows no fill (and re-plans then)
GAUGE_RISE_PCT = 5         # a gauge rise under this (in points) after leaving a stop means the truck didn't fill
GAUGE_FRESH_MIN = 30       # a followed truck's gauge reading this recent is its fuel now (else the estimate)
REPLAN_GAP_MIN = 60        # a road is re-planned for safety at most this often (one with no safe plan: tried again)
SWITCH_COST_USD = 25       # a re-plan moves to a Love's the driver wasn't told about only when it saves more than this


# Returns a required secret from .env, failing loudly with its name if it is missing.
def secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value
