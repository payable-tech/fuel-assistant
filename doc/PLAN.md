# Fuel Assistant — Plan & Architecture

Status: **approved 2026-10-18 — building** · drafted 2026-10-14

> **Direction update, 2026-10-19.** Before optimizing, we measure how fuel runs today: a baseline dashboard
> (`serve` command, `web/` folder) built on the Datatruck *web* API. The research in Bob's Telegram Saved Messages
> showed the value is in planning each **load's** fuel (where and how many gallons), not in a 25% alert.
> Sections 1 and 6 were rewritten around the load on 2026-10-20.
>
> **Pilot, 2026-10-19.** The MVP serves about **10 hand-picked trucks** (`pilot_trucks`). For each one, the `fleet`
> view holds one row with everything core needs (driver, fuel, position, tank, MPG, chat); the load comes from
> `dt_orders`. When a new load arrives, the planner (step 6) plans that load's fuel from this row.
> Source copies stay fleet-wide: the rest of the fleet is the comparison group.

## 1. Goal (MVP)

For each **load** of a pilot truck, plan its fuel: **which Love's to stop at and how many gallons to buy at
each**, so the trip's fuel costs the least, and post the plan to the truck's **Telegram group** (sent from Bob's
own account). The aim is **dollars paid per gallon** for the same driving (scorecard in 5.2).

Shadow first: for a week plans go only to Bob or a test chat and are compared with what drivers really bought,
before any plan reaches a driver.

## 2. Decisions

| Topic | Decision |
|---|---|
| Love's prices | Every `.xlsx` under `data/love's/` (subfolders too) goes into a price history, each sheet read once; the sheet with the newest **Effective Date** (column **Best Discounted Price**) is what the planner uses |
| Pilot | ~10 trucks you pick (`pilot-add`). Everything new reads only them; growing = adding rows |
| Tank sizes | The **tank helper** estimates them from the last 30 days' fill-ups and the Samsara gauge (§5.4); `set-tank` overrides. No default: a pilot truck without a tank is a hole |
| Driver hours (HOS) | Skipped |
| Telegram | Bob's own account (Telethon), no bot |
| Scoring | Lowest total for the trip: gallons × Love's discounted price + $40 per stop; fuel left at the end counts at the price near the destination. Driver time counts only through the stop cost |

## 3. Data sources (verified on live data)

| Source | What we use | Notes |
|---|---|---|
| Samsara | fuel %, GPS (+ address), vehicle VIN, 30-day MPG, fuel gauge history (a reading every ~2 min) | One call returns all trucks. ~128 active trucks. Some gauges stopped reporting long ago, so each reading keeps its own time |
| Datatruck web API | fuel lines (all history), fuel cards, trucks (VIN, ownership), drivers (type, status) | The API Datatruck's own website uses, mapped from a HAR capture. Login: AWS Cognito, 1-hour token renewed from `.env` `DT_WEB_REFRESH_TOKEN` (dies if Bob signs out of Datatruck in the browser) |
| Datatruck Open API | active loads → stop coordinates | API key; max 20 calls/min, 25 rows/page |
| Love's xlsx | 609 stores: number, city, state, lat/lng, retail + discounted price, date | You drop each day's sheet in. 2026-10-20: 228 sheets, 189 days from 2025-03-14 to 2026-10-20 (gaps on some days) |
| U.S. EIA | weekly average retail diesel price, US + 8 regions, since 1994 | Public file, no login (`psw18vwall.xls`); a new week every Monday afternoon. The market yardstick: where our drivers fuel can't move it |
| Google Routes | road line from the truck through the stops still ahead | One call per plan. Traffic-unaware (cheapest tier); car routing, no truck restrictions |
| Telegram | list Bob's groups, send message | One-time login code to Bob's phone |

**Trucks are linked by VIN** (Samsara ↔ Datatruck). Names don't match ("Unit 33 John …" vs "0604").

## 4. Architecture

Three layers, one direction of dependency:

```
            ┌──────────────── jobs/  (glue, runs on a schedule) ────────────────┐
            │ sync_registry   refresh_*   estimate_tanks   plan_loads           │
            └───────┬──────────────────┬──────────────────────┬─────────────────┘
                    │                  │                      │
        ┌───────────▼──────────┐ ┌─────▼───────────────┐ ┌────▼─────┐
        │ sources/  (I/O only) │ │ core/  (pure logic) │ │ db.py    │
        │ samsara   datatruck  │ │ linking  tank  fuel │ │ SQLite   │
        │ loves     google     │ │ loads    geo        │ │          │
        │ telegram  eia        │ │ planner  message    │ │          │
        └──────────────────────┘ └─────────────────────┘ └──────────┘
                    all layers share:  models.py (dataclasses) · config.py (settings)
```

| Layer | Does | Never does |
|---|---|---|
| `sources/` | Talks to one outside system, returns `models` objects | Decide anything, touch the DB |
| `core/` | Pure calculations: same input → same output | Network, DB, clock, files |
| `db.py` | Read/write SQLite | Business logic |
| `jobs/` | Wires sources → core → db/telegram. One job = one schedule | Calculations of its own |

Why this shape: `core/` holds every decision and has no I/O, so it is fully unit-testable.
Bugs in API calls stay in `sources/`; bugs in logic stay in `core/`.

### Folder layout

```
Fuel Assistent project/
├─ .env                       secrets (never share)
├─ run.bat                    runs `serve` and restarts it if it stops; opened at logon by the Startup-folder shortcut
├─ requirements.txt
├─ pytest.ini                 lets tests import from src/
├─ .venv/                     Python + libraries for this project
├─ data/
│  ├─ love's/**/*.xlsx        Love's price sheets, any name, subfolders allowed (archive/, downloads-2026-10-20/)
│  ├─ fuel.db                 SQLite database (created automatically)
│  ├─ telegram.session        Telegram login of the assistant's account (TG_PHONE), which sends — never share
│  ├─ bob.session             Telegram login of Bob's account, which lists the driver groups — never share
│  └─ fuel.log                log file
├─ doc/PLAN.md                this file
├─ src/
│  ├─ main.py                 command line (see section 5.2)
│  ├─ config.py               settings + secrets from .env
│  ├─ models.py               dataclasses shared by all layers
│  ├─ db.py                   schema, views, queries
│  ├─ server.py               dashboard server (web/ files + /api/...), open to PCs on the same network (DASHBOARD_HOST)
│  ├─ sources/  samsara.py · datatruck_web.py · datatruck.py (orders) · loves.py · eia.py · telegram.py · google_routes.py
│  ├─ core/     linking.py · fuel.py (baseline math) · market.py (EIA yardstick) · tank.py (tank helper) · loads.py (current load)
│  │            · geo.py (route, Love's along it) · planner.py (where + how much) · message.py (plan text)
│  │            · trip.py (what the truck really did after a plan) · habits.py (driver habits + their simulation)
│  │            · compare.py (plan vs habit vs actual)
│  └─ jobs/     mirror.py · sync_registry.py · refresh_fuel.py · load_prices.py · refresh_market.py · refresh_orders.py
│               · refresh_live.py · estimate_tanks.py · plan_loads.py · driver_habits.py · dashboard.py · scheduler.py
├─ web/                       live dashboard (always dark): index.html · css/app.css · js/{app,live,trends,plans,drivers,data,charts,dom,theme,format}.js
│                             · vendor/ (Apache ECharts 5.5.1, Leaflet 1.9.4, IBM Plex Sans) served locally, no build step;
│                               only the Plans map's street tiles come from the internet
└─ tests/                     unit tests for db, linking, fuel math, tank helper, current load, Samsara and Datatruck
                              mapping, price sheet, refreshes
```

### Runtime

Step by step, with diagrams: [LOOP.md](LOOP.md).

One Python process: the web server, plus one scheduler thread that runs the jobs **one at a time** → no two jobs
ever race. The scheduler runs each job when it is due:

| Job | Every | Does |
|---|---|---|
| `sync_registry` | 24 h | Refresh Samsara, Datatruck and Telegram copies, then relink `trucks` |
| `load_prices` | 30 min | Sheets not read before → `price_history`; the newest price date → `stores` |
| `refresh_orders` | 15 min | Active Datatruck orders + stops → `dt_orders` / `dt_stops` |
| `refresh_fuel.run_recent` | 15 min | Last 3 days of fuel purchases (seconds), for the Live view |
| `refresh_fuel.run` | 24 h | Every fuel purchase and card (~3 min), catches late edits |
| `refresh_market` | 24 h | EIA weekly diesel prices → `market_prices` (one ~0.8 MB download) |
| `refresh_live` | 5 min | Every truck's latest Samsara position and fuel level → `samsara_live` (one call) |
| `estimate_tanks` | 24 h | Tank helper for the pilot trucks → `tank_estimates` (one gauge-history call per truck) |
| `driver_habits` | 24 h | Every driver's diesel stops of the last 30 days with the gauge around them → `fuel_stops` (one gauge-history call per truck that bought diesel, ~175, a few minutes) |
| `plan_loads` | 5 min | Each pilot truck's load (the first with a stop still ahead) gets one plan, saved to `plans`; the plan is followed (`plan_progress`) with a full message to the test chat (`plan_messages`) when made and at each major event, re-planning the rest when the driver goes off plan (~45 s a run, one GPS call per truck) |

`serve` runs these through `jobs/scheduler.py` (one background thread, one job at a time; each run recorded in
`job_runs` and shown on the Data tab). `serve --no-refresh` only shows the data. The database runs in WAL mode so
the dashboard keeps reading while a refresh writes.

**24/7 on this PC (PC-017).** `run.bat` runs `serve` and starts it again 30 s after it stops; a shortcut
"Fuel assistant" in the Windows Startup folder opens it, minimized, at logon. While it runs, `serve` asks Windows
not to sleep (the screen may still turn off). A watchdog ends the program when no job has finished for `STUCK_MIN`
(30 min), so a hang is restarted like a crash. After a Windows restart someone has to log in for it to start (no
automatic login on this PC; LOOP.md section 5).

Errors: a failing job is logged and retried on its next run; one truck failing doesn't stop the others.
A refresh that fails **or returns nothing** keeps the previous copy (`jobs/mirror.py`), so an API hiccup
can never wipe a table.

## 5. Database (SQLite, `data/fuel.db`)

**Rule: every table has exactly one writer.** Source copies are replaced whole, so they can never hold stale rows.
`unit` (the Datatruck unit number) is the one truck key. All times are stored as UTC text
(`2026-10-18 12:00:00+00:00`), which compares correctly in SQL.

| Layer | Table | Key | Holds | Only writer |
|---|---|---|---|---|
| Source copy | `samsara_vehicles` | `samsara_id` | name, vin, mpg, last_gps_at | sync |
| Source copy | `dt_trucks` | `dt_id` | unit, vin, status, ownership | sync |
| Source copy | `dt_drivers` | `driver_id` | name, driver type, employee status, company, truck | sync |
| Source copy | `fuel_lines` | `line_id` | every fuel-card line: time (Central), product, gallons, pump total, EFS billed, fee, billable, station, state, company, truck, driver, card id (never the number) | fuel |
| Source copy | `fuel_cards` | `card_id` | company, assigned driver/truck, billable, deduction policy, active (never the number) | fuel |
| Source copy | `tg_groups` | `chat_id` | title | sync |
| Source copy | `dt_orders` + `dt_stops` | `order_id` / `stop_id` | status, unit, pickup time / stops in order with lat/lng | orders |
| Source copy | `stores` | `store_no` | city, state, lat, lng, retail, net, price_date (the newest sheet) | prices |
| Source copy | `price_history` | `store_no` + `price_date` | retail, net: every sheet ever put in `data/love's` | prices |
| Source copy | `price_files` | `path` | size, change time, price date of each sheet already read (a sheet is read once) | prices |
| Source copy | `market_prices` | `day` + `region` | EIA weekly retail diesel price per region (day = the Monday it was taken) | market |
| Source copy | `samsara_live` | `samsara_id` | latest lat/lng, address, GPS time, fuel %, fuel reading time | live |
| Linked | `trucks` | `unit` | samsara_id, vin, name, mpg, auto_chat_id, chat_note | sync (relink) |
| Helper | `tank_estimates` | `unit` | tank_gal, fills (fill-ups it is based on). Pilot trucks only | tanks |
| Helper | `fuel_stops` | — | every driver's diesel stops of the last 30 days: driver, unit, time, gallons, billed, Love's?, state, gauge before/after | habits |
| Yours | `pilot_trucks` | `unit` | tank_gal, chat_id (empty = use the helper / auto-match), note, added_at | **you** (`pilot-add`, `pilot-remove`, `set-tank`, `set-chat`) |
| App record | `plans` | `plan_id`; unique `unit` + `order_id` | one plan per load: made_at, and the whole plan as JSON (truck as it was, load, stops ahead, road line, Love's along it, MPG, price date, stops). Kept, never replaced or dropped | plan_loads |
| App record | `plan_messages` | `message_no` | every message about a plan, oldest first: `plan_id`, the chat (`TEST_CHAT_ID` for now), the text as last written, `made_at`, `sent_at` and Telegram's `message_id` (empty until Telegram took it). Kept | plan_loads |
| App record | `plan_progress` | `plan_id` | how far a followed plan has got, as JSON (`models.Progress`): the road in force (the plan or its latest re-plan), waypoints passed on it, the Love's planned so far, every event told. Kept | plan_loads |

A plan keeps a copy of everything it used, so it can be redrawn and checked against the real purchases after the
load is gone from `dt_orders` and the price sheet has changed.

Views (no data, recreated on every start so they always match the code):
- **`fleet`**: **one row per truck** with everything known about it: driver, MPG, latest fuel % and position,
  tank, Telegram group, and whether it is a pilot truck. The only place where automatic and your values meet,
  and yours win (`tank_source` / `chat_source` say which one is used: `manual`, `auto`, or empty).
- **`holes`**: every place the data doesn't link up, one row per problem (hole, item, detail). The `Pilot: …`
  holes (no tank, no Telegram group, no recent fuel reading, no longer linked) must be zero for the planner.
- `active_vehicles`: Samsara vehicles with GPS in the last 24 h, so the holes list skips retired trucks.

```
 samsara_vehicles ─┐ VIN
                   ├──► trucks (relinked by sync) ──────────────┐
 dt_trucks ────────┘    auto_chat_id ◄── tg_groups titles       │
 samsara_live ──────────── fuel %, position ────────────────────┼──► fleet view ──► app (one row per truck)
 dt_drivers ────────────── active driver(s) ────────────────────┤    tank = yours, else helper
 tank_estimates (tank helper) ──────────────────────────────────┤    chat = yours, else auto
 pilot_trucks (only you) ───────────────────────────────────────┘
```

**Helpers** work out a value from the copies (the tank helper: gallons bought ÷ how far the gauge rose). Rules: a
helper writes only its own table; yours always wins in `fleet`; a value with neither source is a hole, never a
default.

### 5.1 Linking rules (`core/linking.py`)
- **Samsara ↔ Datatruck** by VIN (trimmed, upper-case). When Samsara has several records for one VIN (an old
  one and a new one), the record with the **latest GPS** is the real truck: the old one went silent when its
  device moved. In live data, never more than one record of a pair was active. Ties (for example, neither
  record ever reported), empty VINs, a VIN repeated in Datatruck, and a repeated unit number are left out and
  shown in `holes`. Source data is never patched here.
- **Truck ↔ Telegram group**: a truck's group is the **one** group whose title names its unit number (leading
  zeros ignored, no other fleet unit in the title) **and** one of its active Datatruck drivers (2+ words of the
  name, any order: "Kendrick Williams" = "Williams Kendrick"), and isn't marked INACTIVE. The unit number alone
  isn't enough: old groups of former drivers keep it. Anything else is reported as *needs manual*, because a
  missing link is safe and a wrong link is not. Because the match follows the driver, a driver change moves the
  truck to the new driver's group on the next sync. On 2026-10-19 this linked 92 of 123 active trucks (the
  unit-number-only rule linked 20, and 3 of those were wrong: another driver's, an INACTIVE or a home-time group).
- **Group title ahead of Datatruck:** dispatch renames a group ("TTL: Evans Dolce (LO)|Unit 6135") before
  Datatruck gets the driver onto the truck. So when Datatruck has **no** driver on a unit, the one live group naming
  the unit and an active driver Datatruck puts on **no** truck links too: nothing contradicts the title. Such trucks
  are listed in `holes` ("Datatruck: no driver on an active truck whose Telegram group names one") so dispatch can
  fix Datatruck. 2026-10-20: 7 more trucks linked this way (6135, 51898, 208103, 4178 team; 57685, 1081, 0530 on
  home time).
- **Manual**: `set-chat <unit> <chat_id>` always wins (pilot trucks). `set-chat <unit> none` hands the truck back
  to auto-match. Units outside the pilot are rejected, so a typo fails loudly instead of being silently ignored.
  `groups <text>` finds a group's chat id. A manual chat does not follow driver changes, so use it only where
  the auto-match can't decide (typo in a title, two groups for the same driver).
- `fleet` lists every truck with its chat and whether the link is `manual`, `auto`, or missing.

### 5.4 Tank helper (`core/tank.py`)
- Each diesel purchase's Central time is converted to UTC (daylight saving included). Purchases less than 2 h
  apart are one stop (two pumps, a split payment), because their gauge windows would overlap.
- Per stop, two measurements (gauge: lowest reading in the 2 h before, highest in the 2 h after; stops whose gauge
  rose less than 25 points are skipped as too noisy):
  - **size** = gallons ÷ gauge rise;
  - **holds at least** = gallons ÷ room left before the stop (what was poured + what was already in the tank).
- Estimate = the middle size (median) of the last 30 days' stops, **but never less than the 2nd-biggest "holds at
  least"** (the biggest is set aside as a possible gauge glitch). Fewer than 3 usable stops → no estimate.
- Why the floor: many trucks have two tanks with the gauge in one. Filling only that side makes the gauge read
  full with half the fuel in, so that stop looks like half the tank (live data: 5905's stops cluster at ~80 and
  ~145 gal). The median alone came out impossible on such trucks (5905: 140 gal, yet it once held 167+).
- Checked on live data 2026-10-19: purchase times line up with the gauge jump within 1–2 min. A truck whose Samsara
  gauge stopped reporting gets no estimate (a hole).
- **For the planner:** right after a one-side fill the gauge reads full while the other tank isn't; the two
  tanks level out while driving. A fuel % taken just after a stop can overstate what is on board.

### 5.5 Driver habits and the comparison (`core/habits.py`, `core/compare.py`)
- **Stops:** each driver's diesel purchases grouped by stop (as the tank helper does), with their truck's Samsara
  gauge just before (lowest reading in the 2 h before) and just after (highest in the 2 h after).
- **Habit** (worked out when asked, from the last 30 days): middle gauge level when stopping and after filling,
  share of stops that began below 10% ("ran low"), middle gallons per stop, share of stops under 50 gal
  ("top-offs"), share of gallons at Love's, billed $/gal, and how much more per gallon they pay outside Love's.
  First look (12 pilot trucks, 270 stops, 2026-10-20): stop at ~20%, fill to ~95%; 1 stop in 4 began below 10%.
- **Habit simulation** on a plan's road (same start, tank, MPG, Love's, prices): when the gauge gets to their stop
  level they fuel at the Love's nearest that point (one they can still reach) up to their fill level; the gallons
  they usually buy outside Love's cost their usual premium. Doesn't model why they stop (hours, rest).
- **Comparison** (Plans tab): plan, habit and actual each as stops, gallons, dollars bought, fuel left at the end.
  Extra cost vs the plan = extra dollars bought − extra fuel left at the end × the price near the destination
  (filling up cheap before an expensive area is not a cost). Shown in dollars per load. Actual is compared
  only once the load is finished; habit vs actual on finished loads tells how far the simulation can be trusted.

### 5.2 Commands (`.venv\Scripts\python.exe src\main.py <command>`)

| Command | Does |
|---|---|
| `sync` | Refresh Samsara, Datatruck trucks and Telegram groups, then relink |
| `prices` | Read new Love's sheets into the price history; the newest goes to `stores` (first run over 228 sheets: ~25 s) |
| `habits` | Collect every driver's fuel stops with the gauge (a few minutes); the Drivers tab shows the habits |
| `orders` | Copy the active Datatruck orders and their stops |
| `fuel` | Copy every Datatruck fuel line and fuel card (~3 min for ~78K lines) |
| `market` | Copy the EIA weekly diesel prices by region (seconds) |
| `serve [--port 8050] [--no-refresh]` | Run the live dashboard at http://127.0.0.1:8050, and from other office PCs at this PC's office address, **http://10.0.40.40:8050** (the log prints it at start; Windows Firewall is off on this PC). Only this PC and private office networks are let in (`DASHBOARD_NETWORKS`): the Radmin VPN (26.x) gets 403, and so may the name PC-017, which resolves to the Radmin address first. Refreshes data on its own |
| `login` | Log the assistant's Telegram account (`TG_PHONE`) in, once: you type the code Telegram sends it (and its 2FA password). Says whether it is in the test chat. Bob's login (`bob.session`) stays for listing the driver groups |
| `status` | Rows and last refresh time per table |
| `fleet` | Every linked truck: chat, link source, tank, MPG |
| `holes [--all]` | Everything that doesn't link up, grouped |
| `live` | Copy every truck's latest Samsara position and fuel level |
| `pilot` | Each pilot truck: driver, fuel %, where, tank (and its source), MPG, chat, current load |
| `pilot-add <unit> [note]` / `pilot-remove <unit>` | Put a truck in / take it out of the pilot |
| `tanks` | Run the tank helper for the pilot trucks now |
| `plan <unit>` | Plan a pilot truck's current load and print it (dry run: sends nothing, saves nothing) |
| `plans` | Plan and save every pilot load that has no plan yet and send the new plans to the test chat (what the 5-min job does) |
| `restart <unit>` | Start the truck's current load over: a fresh plan of the road ahead, sent to its chats and followed from then on (a truck going live mid-load) |
| `groups <text>` | Telegram groups whose title contains the text, with their chat ids |
| `set-chat <unit> <chat_id\|none>` | Your Telegram group for a pilot truck (beats auto) |
| `set-tank <unit> <gallons\|none>` | Your tank size for a pilot truck (beats the tank helper) |
| `init-db` | Create the empty database |

Dashboard rule: it shows numbers so patterns are visible (related series stacked over the same weeks, rolling
comparisons). No takeaway sentences, no answers to one-off questions, no fixed "then vs now" anchors; captions only say
what is drawn and which window. Questions are answered in chat.

**Plans tab** (validation: does each plan make sense, and what did the driver really do?). Left: the pilot trucks
("Unit 0226", fuel level now, driver). Folded, a truck shows where its active plan goes; pressing it opens its plans,
newest first: the **active** one (the newest, while its load is still open in Datatruck) on top, marked in amber.
A plan opens on a map (Leaflet, OpenStreetMap tiles darkened; `#plans/<id>` is a link to it): planned road (blue), the
Love's along it colored by price from the cheapest (green) to the dearest (red) on that road, each with its price in
a small bubble (where bubbles would overlap, the planned stops' and then the cheapest are kept; the rest show on
hover, with pump price, mile and distance off the road), numbered planned stops, the driver's habit stops (price and
cost on hover), pickup/delivery, where the plan started; and from Samsara/Datatruck what the truck did since: road
driven (amber), fill-ups (green diamond at a planned stop, red elsewhere; placed where the truck's GPS was when it
paid), the truck now (its fuel level on hover). Below: planned stops as a journey (start → stops → end) with what
became of each ("N gal" bought there, "drove past", "skipped", "ahead"), every fill-up since the plan, and the fuel
gauge over time (reserve line, a line per fill-up, gaps where the engine was off). The server rebuilds a plan's trip
from Samsara at most every 5 min (`jobs/dashboard.py`, `core/trip.py`).

The Plans tab also sets each plan beside the driver's habit simulated on the same road (grey "H" stops on the map)
and what really happened (5.5). Prices show both ways: discounted (what the company is billed, what plans are chosen
by) and pump. At the bottom, **Money on this load**: six figures for what was really bought (at the pump, the
discount off it, billed to the company, what the drivers' cards charged them — pump + fee, pump, or the billed amount
by card policy; nothing on company-paid cards — what the plan saves over the habit, and the real trip's extra cost
vs the plan once the load is done), then the plan / habit / actual table in the same rows.

**Drivers tab:** every driver as a dot (across: gauge when stopping, up: gauge after filling, size: gallons, color:
Love's share; pilot drivers labelled), every stop by gauge level when stopping (at Love's / elsewhere), and a table of
every driver's habit figures.

**Scorecard** (Trends → "What we paid vs the market"): each week's diesel priced at the EIA market price of its
region (between the Mondays before and after each purchase) against what EFS billed. Market moves and volume move
both sides, so **saved per gallon** changes only with our fuel decisions; the planner works if its 4-week average
rises after go-live. Pump price is not the yardstick: sending a driver to a cheaper station lowers it too.

### 5.3 What the live data looked like (2026-10-18)
125 of ~128 active trucks linked. Gaps found:
- 33 Samsara VINs have two records each (old + new). Solved by the latest-GPS rule; the old records can be cleaned up in Samsara.
- 72 Datatruck trucks have no Samsara record at all (26 of them in transit). No fuel data, so we can't serve them.
- 6 Samsara records are named after a unit but have another truck's VIN ("… SUB …" = substitute truck).
- 18 trucks have 2+ orders *in transit* at once, so the destination is ambiguous (see 6.2).
- 7 Datatruck units contain dots/letters (`..101`, `555..`, `02A`), probably old or duplicate entries.

## 6. Flows

One load of one pilot truck: its row in `fleet` (fuel, position, tank, MPG, chat) + its load → route → Love's
along it → plan → message.

### 6.1 When a plan is made (`jobs/plan_loads.py`)
- Every 5 min the `plan_loads` job looks at each pilot truck's loads and takes the first one (in transit first,
  then by pickup) that still has a stop ahead. A load without a plan gets one, from where the truck is at that
  moment, and it is saved (`plans`). One plan per load: it is not redone if the driver goes another way, so the
  Plans tab shows how the plan held up. A truck still finishing a load gets its next load planned once it has been
  at the last stop (on 2026-10-21, 44 of 192 trucks with a load already had the next one booked).
- The plan's first message is queued with it (`plan_messages`, a log of every message) and sent from Bob's account to
  `TEST_CHAT_ID`, the group "Test fuel" (shadow week). A send that fails is tried again on the next run; one still
  unsent an hour after it was written (`SEND_WITHIN_MIN`) is dropped. The drivers' own groups come with going live.
- **Followed** (`core/follow.py`, `core/route.py`, progress in `plan_progress`). The plan's waypoints are its fuel
  stops and the load's stops ahead, in the order the planned road reaches them (a fuel stop can come before the PU).
  Each run (5 min), from the truck's GPS since the plan and its Datatruck fuel lines (placed by GPS as on the Plans
  tab), the job finds what happened since the last look:
  - **PU/DEL reached**: the truck within 1 mi of it, after the waypoints before it (a DEL near the road to the PU
    doesn't count early). A fuel stop is passed the same way, or once a later one before the next PU/DEL is reached.
  - **Fuel bought**: at planned stop n when it is that Love's by store number (a Pilot at the same exit is not; a
    planned Love's counts even in a GPS gap), else "not on plan". Lines come in every 15 min; purchases minutes
    apart are one stop, and a late line updates the stop already told instead of telling it again.
  - **Stop missed**: the truck **left** a planned stop `MISSED_AFTER_MIN` (60) ago with no fuel line from it (a break
    or a 10-hour rest at the stop is not missing it) — or already `MISSED_QUICK_MIN` (15) after leaving when its
    gauge since shows no fill (rose under `GAUGE_RISE_PCT`, 5 points, from the reading before it got there; a 20-gal
    fill lifts it ~10). The gauge history is fetched only while such a stop is open. A fuel line that still comes in
    later wins: the stop reads done. First seen live 2026-10-22: 555701 drove past its Albuquerque top-up at 14:40;
    "missed" and the re-plan (Santa Rosa, NM next) reached the driver at 15:02 instead of ~15:40.
  - The trip ends at the last DEL in road order (a road passing near the consignee before the PU doesn't end it);
    purchases after it are the next load's. While the plan is followed and unfinished, and Datatruck still has its
    load open, the truck's next load waits for it.
  - **Off plan** (bought elsewhere, or a stop missed) → the **rest of the road is re-planned** from where the truck is
    now (new Google road + planner). Planned stops it no longer uses are dropped; its new Love's get the next
    numbers. The original plan stays the record for the Plans tab.
  - **A re-plan keeps the Love's already told** while they still work (reachable keeping the reserve): any other
    Love's counts `SWITCH_COST_USD` ($25) more in the planner, so the stops change only when that saves more. Seen
    2026-10-23 04:52: 832206, stopped near Conneaut, OH, swapped Madison, OH + Oklahoma City for Burbank, OH + Claude,
    TX to save 2.5¢ and 0.2¢ a gallon (~$5–10) — a new message for nothing. A told stop that can't be reached any
    more is still replaced.
  - **Safety re-plan**, with no event needed: the road ahead no longer fits the fuel on board — it would arrive more
    than half the reserve under it somewhere, or a planned fill would overflow the tank by more than that (plans
    often arrive right at the reserve, and the gauge wobbles a few gallons). A truck already under the reserve may
    use what it has to reach its next stop; and it waits while a planned stop just passed is still open (its fuel
    line may not be in yet). A road with no safe plan is tried again every `NO_PLAN_RETRY_MIN` while it would arrive
    too low (the truck may now be among Love's it couldn't reach). A re-plan that fails (e.g. Google unreachable)
    doesn't hold the events back: they are told, and the check tries again next run. A road is re-planned for
    safety at most once an hour (`REPLAN_GAP_MIN`): 832206, parked and idling in a yard, was re-planned twice and
    flipped stops back and forth before this. A safety re-plan that stops at the same Love's in the same order only
    updates the amounts, without a message.
  - **Starting a load over** (`restart <unit>`): a fresh plan of the road still ahead, from where the truck is, sent
    to its chats as "⛽ New fuel plan" and followed from then on; the earlier plan stays on the Plans tab and its
    messages in "Test fuel". For a truck that goes live mid-load, so its driver doesn't start with the shadow period's
    history. `restart <unit> --via 372` (a Love's store number, or `lat,lng`; `plan <unit> --via` to see it first)
    plans the road through the driver's own route where it isn't Google's; the plan keeps it (`via`), and re-plans go
    through it too until the truck is there. First used 2026-10-23 08:43 for 3068: Google's fastest road was US-12
    over Lolo Pass (two-lane mountain road, no truck stops for ~170 mi); the driver had already said he drives US-95
    → I-84 E (Love's #372 Ontario, OR) → I-80 E, 2,581 mi vs 2,490, and turned the US-12 plan down within a minute.
    The planner can't know a driver's route by itself: ask, or let dispatch name it.
    Seen on 2026-10-22 before it existed: 549468 would have reached its DEL with ~0 gal (both stops skipped), and
    14684's stop 2 still said "arrive ~57 gal → buy 111 gal" in a 156-gal tank after 99 gal bought off plan.
  - **Fuel now** = Samsara's latest gauge reading when it is under `GAUGE_FRESH_MIN` old and nothing was bought in the
    last 2 h; otherwise the estimate: the plan's start − miles driven ÷ MPG + gallons bought (a dual-tank gauge reads
    high right after a one-side fill). On 2026-10-22 the estimate was within ~15 gal of the gauge on 10 trucks.
  Each look with events queues **one full message** per chat (6.5): "Test fuel", and the truck's own group for units
  in `LIVE_UNITS` — the chats the plan's first message went to, so a truck that goes live mid-load starts in its
  group with its next plan. Messages are sent from the assistant's account (Migo, `data/telegram.session`). Once it is sent, the truck's previous message in that chat (of this plan or its last one) gets
  "⤵ Newer update below" instead of its link, so only the newest message leads anywhere. A send that fails holds the
  plan's later messages to that chat back, so they go out in order. A stop passed with nothing to tell
  yet (its fuel line not in) only moves the newest message's link on (silent edit). Followed until the last DEL, at
  most `FOLLOW_DAYS`; a truck's next plan takes over.
- `plan <unit>` (dry run) plans the truck's current load and prints its first message; nothing is sent or saved.

### 6.2 Route (`core/loads.py`, `sources/google_routes.py`)
- Current load: the one in transit, else the earliest pickup. 2+ in transit: the earliest pickup among them
  (open, see 10; none of the pilot trucks has this).
- Stops still ahead: those after the last stop the truck's **Samsara GPS track** came within **1 mi** of, counting
  only visits from 24 h before the pickup appointment on (not earlier loads at the same place). Datatruck can't
  tell: its stops have no "done" mark and its status lags (live, 2026-10-20: three pilot loads still "dispatched"
  after pickup, one after delivery). The trucks' tracks passed 0.0–0.1 mi from the stops they served. All stops
  reached → the load is finished, no plan. Stops without coordinates are left out.
- One Samsara call (GPS history, ~5 s) and one Google call: the truck's position → the stops ahead, as a road line.

### 6.3 Love's along the route (`core/geo.py`)
The line is cut into pieces of at most 0.5 mi (Google sends a long straight road as one piece). Every Love's within
**1.5 mi** (straight line) of it is a candidate, with how many miles along the route it is. Done locally, free.
The small detour off the route is not counted.

### 6.4 The plan (`core/planner.py`)
At each candidate the truck either drives past or fills up to a level (5-gal steps, from a full tank down). For
every (stop, level) only the cheapest way to get there is kept, so all combinations are covered fast (< 0.3 s).
- Fuel at the start = gauge % × tank; burn = miles ÷ MPG (Samsara 30-day; 6.5 when missing or outside 4–12).
- The tank never goes below **10%** at a stop or at the end. A truck already below that may use what it has to
  reach its first stop.
- A stop buys at least **20 gal** and costs **$40** on top (time, wear), so the plan doesn't stop needlessly.
- Price = Love's "Best Discounted Price" from the newest sheet.
- Fuel left at the end counts at the price of the Love's nearest the destination, so cheap fuel is carried into
  an expensive area (a load into California fills up in Arizona). Between plans that cost the same, buy less.
- **Arrive at the last stop with 40+ gal** (`END_MIN_GAL`) when a plan can, else with the reserve: the next load
  starts with ~250 mi of range, enough to reach a good Love's instead of the nearest pump. On 21 saved loads
  (2026-10-22): +$0.60 a load (fuel left is credited at the price there), one more stop every ~7 loads, fuel at
  the DEL 67 → 85 gal on average.
- **Detour counted** (`DETOUR_FACTOR` 2.6): a Love's off the route costs the fuel to drive there and back (1.3 road
  miles per straight-line mile, each way). Widening the corridor from 1.5 mi to 5 or 15 mi was tried on the same
  21 loads: 1.5 / 6 more Love's to choose from, no saving (they sit at the same exits; farther ones cost more detour
  than they save), and the 3 Maine loads still had no plan. So the corridor stays 1.5 mi.
- **No Love's in reach** (`jobs/plan_loads._stations`, `sources/google_places.py`): when no plan of Love's keeps
  the reserve, Google Places (API "Places API (New)", enabled 2026-10-23) is searched **along the road ahead**, as
  far as the fuel on board reaches, for stations within `STATION_OFF_MI` (5) of it: truck stops first (only those
  that are gas stations: Google calls rest areas and CAT scales truck stops too), and only if those can't make a
  plan, any gas station selling diesel (US-12 over Lolo Pass has none for ~170 mi). They join the candidates at
  Google's diesel price, or the nearest Love's pump price when Google has none; with no discount, the plan buys only
  what it takes to reach the Love's. A station nearest the road where the truck is now, more than a mile from it, is
  beside or behind the truck and left out. First case, 2026-10-23, unit 3068 (DT), Lewiston, ID → Shelby, NC: the
  first Love's on its road is Laurel, MT, ~530 mi on, with ~225 mi of fuel. A search around the parked truck
  (first version) found Stinker Stores, Lewiston, but the truck left without stopping, and the same search then
  pointed back at it; along the road, as sent to the driver at 08:21 (live): Conoco, Craigmont, ID (17 mi, $6.50)
  for 58 gal, then Laurel, Sioux City and Calvert City. The message names the station, "· no Love's in reach", and a
  fill-up where its GPS place was counts as that stop.
- No plan when even that keeps no reserve (Love's too far apart mid-road, as in Maine, or Google can't be asked).
- **Optimal for its rules**: on 60 random trips it matched brute force (every set of up to 3 Love's, every fill
  level) to the cent, with and without the end target and detours. Its answers are only as good as its inputs:
  the MPG (Samsara's 30-day average runs optimistic, see visions #4), the newest price sheet, the tank estimate.

### 6.5 Message (`core/message.py`)
Telegram HTML, one full message per major event, in four sections split by `--------`: what happened (the first
line, which is what Telegram's notification shows) with the load and fuel; the road (what is done in the order it
happened, then what is ahead); the totals; the link. Unit 0226's plan 23 as sent 2026-10-22, after the pickup:
```
⛽ Fuel plan · Unit 0226                                  (bold; an event says e.g. "✅ Stop 1 done · Unit 0226 · bought 72 gal")
Load 5016640 · Londonderry, NH → Warrensville Heights, OH · 674 mi
Fuel now 22% · 35 of 156 gal · 6.5 MPG                    (by estimate, see 6.1)
--------
📦 PU Ayer, MA ✓                                          (crossed out: done)
⛽ 1. Love's #611 Canaan, NY · in 55 mi                   (the name opens Google Maps at the store)
      arrive ~26 gal → buy 70 gal · $6.07
🏁 DEL Warrensville Heights, OH · in 555 mi
      arrive ~19 gal
--------
Still to buy: 70 gal · ~$423 · 1 stop                     (what the road ahead plans; the first message: "Total: …")
Bought so far: nothing yet
--------
▶ Continue the road                                       ("Start" in the first message)
```
- Headlines: "⛽ New fuel plan", "✅ PU … done", "✅ Stop n done · bought N gal", "⚠️ Off plan · bought N gal at …",
  "⚠️ Stop n missed · no fuel bought at …", "🔁 Rest of the road re-planned · from near …", and at the end
  "🏁 Delivered · plan followed / not followed".
- Done lines are only what was done: PU/DEL "✓", "⛽ Love's … ✓ 72 gal · $437", "⛽ Pilot … · 95 gal · $5.79 (not on
  plan)"; the last DEL "✓ arrived with ~N gal". A stop missed, stops dropped and a re-plan are told in the headline
  of the message they happen in, and the road ahead shows what came of them; they aren't repeated in later messages
  (before 2026-10-23 they were: 832206's message #49 had 21 lines of such history out of 37).
- Arrivals ahead are counted from the fuel on board now and where the truck is on the road.
- **Prices are pump prices only** (the Love's sheet's "Retail Price"; real purchases at their pump total): 9 of the
  12 pilot drivers' cards charge them the pump price plus a fee, and the discount is the company's. The planner still
  chooses by the discounted price.
- The last message's totals: the plan beside what was bought and the fuel left, and "Extra cost vs plan" (5.5,
  fuel left counted at the price near the destination). It has no link.
- "▶ Start/Continue the road" is a Google Maps link with no start point, so it navigates from the phone's own
  location, through the waypoints still ahead (`waypoints=`, in road order) to the last (`destination=`),
  `dir_action=navigate`. Google Maps routes like a car, not a truck. Sent without link previews. The price sheet
  date stays on the dashboard, not in the driver's message.

## 7. Settings (`config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `RESERVE_PCT` | 10 | the plan never lets the tank drop below this |
| `CORRIDOR_MI` | 1.5 | Love's farther than this (straight line) from the route are not considered |
| `DETOUR_FACTOR` | 2.6 | road miles to a Love's and back per straight-line mile off the route: the detour's fuel counts |
| `END_MIN_GAL` | 40 | aim to reach the load's last stop with this much, else with the reserve |
| `MIN_BUY_GAL` | 30 | a planned stop buys at least this much (20 until 2026-10-23: drivers may not stop ~30 min for ~$120) |
| `STOP_COST_USD` | 40 | what one more stop costs, so the plan doesn't stop needlessly |
| `FUEL_STEP_GAL` | 5 | fill-up amounts are planned in these steps |
| `ROUTE_STEP_MI` | 0.5 | the route line is cut into pieces this short to find the Love's along it |
| `STATION_OFF_MI` | 5 | no Love's in reach: other stations this close to the road ahead count (Google Places) |
| `STOP_REACHED_MI` | 1.0 | a load's stop is done once the truck's GPS has been this close to it |
| `VISIT_WINDOW_H` | 24 | only GPS visits from this long before the pickup appointment count |
| `PLAN_LINE_STEP_MI` | 0.1 | a saved plan keeps its road with points at least this far apart |
| `EVERY_PLAN_MIN` | 5 | how often the planner job looks for loads without a plan and keeps sent messages current |
| `TRACK_STEP_MI` | 0.2 | Plans tab: the road driven is sent with points at least this far apart |
| `PLANS_DAYS` | 14 | Plans tab: plans made in the last this many days are listed |
| `HABIT_DAYS` | 30 | driver habits: stops of the last this many days |
| `RAN_LOW_PCT` | 10 | driver habits: a stop that began below this gauge level "ran low" |
| `TOP_OFF_GAL` | 50 | driver habits: a stop buying less than this is a top-off |
| `DEFAULT_MPG` | 6.5 | used when Samsara MPG is missing or outside 4–12 |
| `TANK_DAYS` | 30 | tank helper: fill-ups of the last this many days |
| `TANK_WINDOW_MIN` | 120 | tank helper: gauge readings this long before/after a purchase; purchases closer are one stop |
| `TANK_MIN_RISE_PCT` | 25 | tank helper: smaller gauge rises are skipped |
| `TANK_MIN_FILLS` | 3 | tank helper: fewer usable stops → no estimate |
| `TEST_CHAT_ID` | "Test fuel" (-5383830098) | each new plan is sent here (shadow mode); empty: nothing is sent |
| `SEND_WITHIN_MIN` | 60 | a plan's message still unsent this long after the plan is dropped |
| `FOLLOW_DAYS` | 5 | a plan is followed (a message per major event) for at most this long |
| `LIVE_UNITS` | ("0226", "555701") | units whose drivers get their plan messages in the truck's own group too (the test chat keeps a copy). 555701 (company driver, company-paid fuel) got the first live plan on 2026-10-22 13:23 (`restart`); 0226's starts with its next load |
| `REPLAN_GAP_MIN` | 60 | a road is re-planned for safety at most this often (one with no safe plan: tried again) |
| `SWITCH_COST_USD` | 25 | a re-plan moves to a Love's the driver wasn't told about only when it saves more than this |
| `STUCK_MIN` | 30 | no job finished for this long: the program ends itself and run.bat restarts it |
| `MISSED_AFTER_MIN` | 60 | a planned stop passed this long ago with no fuel line from it counts as missed |
| `MISSED_QUICK_MIN` | 15 | ...already this long after leaving it when the gauge since shows no fill |
| `GAUGE_RISE_PCT` | 5 | a gauge rise under this (points) after leaving a stop means no fill |
| `GAUGE_FRESH_MIN` | 30 | a followed truck's gauge reading this recent is its fuel now (else the estimate) |
| `TG_SESSION_PATH` | data/telegram.session | the assistant's Telegram login: sends and edits the messages |
| `TG_GROUPS_SESSION_PATH` | data/bob.session | the login that lists the driver groups (linking); point it at the assistant's once that account is in them all |

`ACTIVE_HOURS` (24) decides which trucks the holes list treats as active.

`.env` keys: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `DT_SLUG`, `DT_API_TOKEN`, `DT_WEB_REFRESH_TOKEN`,
`SAMSARA_API_TOKEN_TTL` and `SAMSARA_API_TOKEN_DT` (one Samsara account per carrier, `SAMSARA_ACCOUNTS`; added DT
2026-10-23: 92 vehicles, 65 of them trucks moved from TTL, whose old TTL records stopped reporting — linking keeps the
record that reported last), `GOOGLE_MAPS_API_KEY` (Routes API, created 2026-10-20), `TEST_CHAT_ID` (optional).

## 8. Build steps (each one is tested before the next)

| # | Step | How you test it |
|---|---|---|
| 1 ✅ | Skeleton: venv, requirements, config, models, db schema + manual settings, `main.py` | `init-db` creates `data/fuel.db`; `pytest` green |
| 2 ✅ | Love's prices | `prices` → 609 stores |
| 3 ✅ | Registry: Samsara + Datatruck by VIN, MPG, holes view | `sync`, then `fleet` and `holes` |
| 4 ✅ | Telegram login + group matching | `sync` copies Bob's groups (994 on 2026-10-19); `groups <unit>` lists them |
| 5 ✅ | Active orders + stops copied | `orders`, then `status` |
| 5b ✅ | Datatruck web API + fuel lines/cards/drivers + **baseline dashboard** | `fuel`, `sync`, then `serve` and open http://127.0.0.1:8050 |
| 5c ✅ | **Pilot**: `pilot_trucks`, one row per truck (`fleet`), live fuel/GPS, tank helper | `pilot-add <unit>` ×10, `live`, `tanks`, then `pilot` and `holes` |
| 6 ✅ | **Planner**: Google route, Love's along it, cheapest stops + gallons, message, dry run | `pytest` green; `plan <unit>` prints the plan, sends nothing |
| 7 ✅ | Plans saved (`plans`, one per load) by a 15-min job + **Plans tab**: each plan on a map against what the truck did | `plans`, then open http://127.0.0.1:8050/#plans |
| 7a ✅ | Love's price history (228 sheets) + **driver habits** (Drivers tab) + plan vs habit vs actual (Plans tab) | `prices`, `habits`, then the Drivers and Plans tabs |
| 7b | Validate plans on the Plans tab; polish the planner where they look wrong | — |
| 7c ✅ | Each new plan sent to `TEST_CHAT_ID`, the group "Test fuel" (shadow), with a map link per stop | plan 21 (0226) arrived on 2026-10-21 |
| 7d ✅ | Driver message layout + "▶ Start the road" Google Maps link in road order, message edited as stops are passed | plan 23 (0226) re-sent 2026-10-22 with the PU crossed out |
| 7e ✅ | Plans followed: a full message per major event (PU/DEL, bought on/off plan, stop missed), re-plan when off plan, plan vs actual at the end | 10 active plans followed from 2026-10-22; 0226's sent in the new layout |
| 8 | Shadow week: each plan vs what the driver really bought, in dollars | a weekly comparison |
| 9 | Live: the pilot drivers receive plans | drivers' groups get the plan |
| 10 ✅ | Run 24/7 on this PC: `run.bat` (restarts itself), Startup-folder shortcut, no sleep while running, dashboard open to the office network | log off and on: the "Fuel assistant" window opens by itself |

## 9. Code rules

1. Clean, concise, no spaghetti. Clear separation of responsibility (section 4).
2. Simple over clever. Prevent edge cases with better design, not extra branches.
   Never cut functionality or robustness.
3. Every file starts with a `#` comment (1–2 lines) saying what it does.
4. Every function has a `#` comment (1–2 lines). If it can't be explained that briefly, split the function.
5. Any line that isn't obvious at a glance gets a short `#` comment.

## 10. Open items

- Pilot picked 2026-10-19 (12 trucks, all holes clear): 549468, 875521, 213000, 555701, 5905, 14684, 832924,
  1794, 796806, 513878, plus company trucks 0226 and 832206. Chosen from the 55 trucks with a group, fresh
  gauge/GPS, normal MPG, one driver, a clear load and no duplicate Samsara record, by 30-day diesel volume, $/gal
  paid and share bought outside Love's. 4 of 12 are company drivers: their fuel is mostly paid by the company
  (40% billed to the driver vs 99% for lease drivers), so savings show directly on the company's bill.
  2026-10-22: **6240** (Desire Nkusi, company driver, company-paid card) added as the candidate first live test:
  93% of his gallons at Love's (he'll find the plans familiar), but he stops at 12% and goes under 10% on 47% of
  stops (room for timing and safety), Texas lanes, good data (tank 157 gal from 17 fills). Plans post to "Test
  fuel" until he is in `LIVE_UNITS`.
- **Price history has gaps**: since Aug 1 only Oct 14, 16-20 and 22. Comparing past purchases with "the Love's
  price that day" needs the daily sheets for the days compared; without them a purchase is set against months-old
  prices (a fleet ranking done that way on 2026-10-22 was wrong and thrown out).
- **Love's prices:** a plan is only as good as its prices. Drop each day's sheet anywhere under `data/love's/`
  (or automate it: the Gmail daily price list, or Love's own price API). Up to date on 2026-10-20.
- Backtest: replay the last weeks' finished loads (their GPS track as the road, the price history of each day) to
  measure plan vs what drivers did across many loads, not only new ones.
- Tie-break for trucks with 2+ in-transit loads (6.2): 17 of 192 trucks on 2026-10-21, none in the pilot. Mostly
  Datatruck not marking the earlier load delivered (the GPS check skips it); two loads really on board at once
  would get a plan for one of them only.
- Next load already booked (44 of 192 trucks on 2026-10-21): plan through it too, instead of stopping at the
  current load's last stop?
- Map tiles come from the OpenStreetMap servers, which allow light use like one office dashboard. With many viewers,
  switch `TILES` in `web/js/plans.js` to a paid or self-hosted tile service.
- When there is no plan (Love's too far apart, e.g. New England), say where the nearest fuel is instead.
- Right after a one-side fill the gauge overstates the fuel on board (5.4).
- 72 Datatruck trucks not in Samsara: which system tracks them, if any?
- Optional later: count the small detour off the route (≤ 1.5 mi) as fuel and time.
