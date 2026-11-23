# The dashboard's settings: where the page is, who may open it, and how much each tab shows.
from base import config

WEB_DIR = config.ROOT / "web"

# The server
DASHBOARD_HOST = "0.0.0.0"  # "0.0.0.0": other PCs on this network can open it too; "127.0.0.1": this PC only
# Who may open it: this PC and private office networks. Not the Radmin VPN (26.x), which this PC is also on, with
# Windows Firewall off; the dashboard has no login, so its address alone must not be enough from outside the office.
DASHBOARD_NETWORKS = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
DASHBOARD_PORT = 8050
BASELINE_WEEKS = 26        # weeks of history the dashboard shows
BREAKDOWN_WEEKS = 4        # recent full weeks the breakdown tables cover

# The Recommend tab
RECOMMEND_DAYS = 14        # the dashboard lists recommendations of this many days
RECOMMEND_FROM = "2026-11-02"  # ...and the fills no message asked for from this day, the engine's first
RESULT_WINDOW_H = 48       # the truck's first diesel stop this soon after a recommendation is what became of it

# The Drivers tab: how each driver usually fuels
RAN_LOW_PCT = 10           # a stop that began below this gauge level "ran low"
TOP_OFF_GAL = 50           # a stop buying less than this is a top-off

# Fleet status (the top of the Drivers tab)
FLEET_FUELED_DAYS = 14     # a truck with no card assigned that bought fuel within this many days is shown apart

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

# The Live tab's messages sent to drivers, and the fills looked up
LIVE_FROM = "2026-11-03"           # the first day a driver got a message: the Live tab counts the plans from here
LOVES_TARGET = 0.999               # the share of the fleet's diesel to buy at Love's, the goal
LOOKUPS_FROM = "2026-09-28"        # fills outside Love's are looked up from this day on
