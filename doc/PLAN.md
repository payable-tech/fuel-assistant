# Fuel Assistant — Plan & Architecture

Status: **new recommendation engine running since 2026-11-02. 41 trucks' drivers get the messages (`LIVE_UNITS`): 0530
and 14755 since the morning of 2026-11-03, 8 more that afternoon, 10 more on 2026-11-04, 10 company drivers on
2026-11-05, 9 more on 2026-11-06, 8 more on 2026-11-09 (11779's gauge works again); 540201, 751850, 3464, 528624, 1901
and 6240 are paused.** A copy of each message goes to the group "Test fuel" (§6.1).
A truck goes live only once the assistant's account (Migo) is in its driver group: it sends from there.

> **2026-11-02: the old engine was removed.** Scored from raw GPS, gauge and fuel card data, its 87 usable plans
> showed no measurable saving: drivers bought at 37% of the stops they were told (23% of stops when not told, not a
> proven difference), 70% of fill-ups on told loads were at no planned stop, and 57% of 250 messages were re-plans or
> warnings. Removed: the planner, the plan follower, re-plans, driver messages, stop alerts, the plan vs no-plan test,
> and the Plans and Test tabs. A copy of that code and its data is in `D:\Fuel Assistent backup 2026-11-02`.

## 1. Goal

Pay less for the same fuel on trips, with stops the driver will accept and without ever putting the truck at risk. The
driver sees one short message per stop, everything else stays silent. Every message is recorded, to set against where
the truck really fueled; only the trucks in `LIVE_UNITS` send it to the driver.

Test subjects (`pilot_trucks`): 0226, 14755, 11779, 1553, 0530 since 2026-11-02; 51506, 540201, 5502, 4482, 516773, 4214
since 2026-11-03 (the user's "mix": three trucks that buy most outside Love's, three company drivers); 9617, 1901,
832206, 252602, 6240 (company), 549468, 4217, 19727, 770369 (lease), 5034 (owner) since 2026-11-04.

## 2. Decisions

| Topic | Decision |
|---|---|
| Love's prices | Every `.xlsx` under `data/love's/` (subfolders too) goes into a price history, each sheet read once; the sheet with the newest **Effective Date** (column **Best Discounted Price**) goes to `stores` |
| Pilot | The test subjects you pick (`pilot-add`). Growing = adding rows |
| Tank sizes | The **tank helper** estimates them from the last 30 days' fill-ups and the Samsara gauge (§5.4); `set-tank` overrides. No default: a pilot truck without a tank is a hole |
| Driver hours (HOS) | Skipped |
| Telegram | Bob's account lists the driver groups for linking trucks; the assistant's account (`TG_PHONE`) sends the fuel messages: to the test group, and to the driver groups of the trucks in `LIVE_UNITS` (Telethon, no bot) |

## 3. Data sources (verified on live data)

| Source | What we use | Notes |
|---|---|---|
| Samsara | fuel %, GPS (+ address), vehicle VIN, 30-day MPG, fuel gauge history (a reading every ~2 min) | One call returns all trucks. ~128 active trucks. Some gauges stopped reporting long ago, so each reading keeps its own time |
| Datatruck web API | fuel lines (all history), fuel cards, trucks (VIN, ownership), drivers (type, status) | The API Datatruck's own website uses, mapped from a HAR capture. Login: AWS Cognito, 1-hour token renewed from `.env` `DT_WEB_REFRESH_TOKEN` (dies if Bob signs out of Datatruck in the browser) |
| Datatruck Open API | active loads → stop coordinates | API key; max 20 calls/min, 25 rows/page |
| Love's xlsx | 609 stores: number, city, state, lat/lng, retail + discounted price, date | You drop each day's sheet in. 2026-10-20: 228 sheets, 189 days from 2025-03-14 to 2026-10-20 (gaps on some days) |
| U.S. EIA | weekly average retail diesel price, US + 8 regions, since 1994 | Public file, no login (`psw18vwall.xls`); a new week every Monday afternoon. The market yardstick: where our drivers fuel can't move it |
| Google Routes | road line through a list of points | One call per load. Traffic-unaware (cheapest tier); car routing, no truck restrictions |
| Google Places | real truck stops along a stretch of road | Only when no Love's can be counted on (the urgent backup) |
| Telegram | list Bob's groups; send the fuel messages from the assistant's account | One-time login code to each account's phone |

**Trucks are linked by VIN** (Samsara ↔ Datatruck). Names don't match ("Unit 33 John …" vs "0604").

## 4. Architecture

Three layers, one direction of dependency:

```
            ┌──────────────── jobs/  (glue, runs on a schedule) ────────────────┐
            │ sync_registry   refresh_*   estimate_tanks   driver_habits        │
            └───────┬──────────────────┬──────────────────────┬─────────────────┘
                    │                  │                      │
        ┌───────────▼──────────┐ ┌─────▼───────────────┐ ┌────▼─────┐
        │ sources/  (I/O only) │ │ core/  (pure logic) │ │ db.py    │
        │ samsara   datatruck  │ │ linking  tank  fuel │ │ SQLite   │
        │ loves     google     │ │ loads    geo   burn │ │          │
        │ telegram  eia        │ │ habits   nearby     │ │          │
        │                      │ │ recommend  message  │ │          │
        │                      │ │ outcomes   market   │ │          │
        └──────────────────────┘ └─────────────────────┘ └──────────┘
                    all layers share:  models.py (dataclasses) · config.py (settings)
```

`dashboard.py` is glue too, run when the page asks rather than on a schedule: it reads the DB (and Samsara for what a
truck really did) and leaves the figures to `core/`. `rules.py` builds the recommendation's settings from `config.py`
once, so the engine and the dashboard judge a truck by the same rules (`core/` never reads `config.py`).

| Layer | Does | Never does |
|---|---|---|
| `sources/` | Talks to one outside system, returns `models` objects | Decide anything, touch the DB |
| `core/` | Pure calculations: same input → same output | Network, DB, clock, files |
| `db.py` | Read/write SQLite | Business logic |
| `jobs/`, `dashboard.py` | Wires sources → core → db. One job = one schedule; the dashboard answers the page | Calculations of its own |

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
│  ├─ telegram.session        Telegram login of the assistant's account (TG_PHONE), which sends the messages — never share
│  ├─ bob.session             Telegram login of Bob's account, which lists the driver groups — never share
│  └─ fuel.log                log file, written by `serve` only (fuel.log.1 … .4: the older ones, 20 MB each)
├─ doc/PLAN.md                this file
├─ src/
│  ├─ main.py                 command line (see section 5.2)
│  ├─ config.py               settings + secrets from .env
│  ├─ models.py               dataclasses shared by all layers
│  ├─ db.py                   schema, views, queries
│  ├─ server.py               dashboard server (web/ files + /api/...), open to PCs on the same network (DASHBOARD_HOST)
│  ├─ dashboard.py            each view's numbers for the page (reads the DB and Samsara; the figures come from core/)
│  ├─ rules.py                the recommendation's settings from config.py, shared by the engine and the dashboard
│  ├─ sources/  samsara.py · datatruck_web.py · datatruck.py (orders) · loves.py · eia.py · telegram.py · google_routes.py
│  │            · google_places.py (truck stops, the urgent backup) · efs_statement.py (EFS statement PDFs in data/efs)
│  │            · eManager, the EFS website, for fuel cards (§5.7): efs_chrome.py (its Chrome window) · efs_page.py
│  │              (reading a page) · efs_web.py (login, account switch, allowed buttons) · efs_cards.py (the card tools)
│  ├─ core/     linking.py · fuel.py (fuel figures) · market.py (EIA yardstick) · tank.py (tank helper) · loads.py (current load)
│  │            · geo.py (route, Love's along it) · habits.py (driver habits) · nearby.py (cheapest Love's near a fill)
│  │            · burn.py (engine as a fuel meter, live MPG) · recommend.py (where to fuel, how much)
│  │            · message.py (what the driver is told, its links) · outcomes.py (what came of each message)
│  │            · accounting.py (an EFS statement as a tree: page 1's rows, then lines joined to Datatruck)
│  │            · fill_checks.py (checks on a statement's fills: the statement in numbers, Love's promised vs charged)
│  │            · evidence.py (Samsara's evidence: per fill gauge rise and truck at the station; per truck bought vs burned)
│  └─ jobs/     mirror.py · sync_registry.py · refresh_fuel.py · load_prices.py · refresh_market.py · refresh_orders.py
│               · refresh_live.py · estimate_tanks.py · estimate_burn.py · driver_habits.py · fill_lookups.py · recommend.py
│               · read_statements.py · statement_evidence.py · scheduler.py
├─ web/                       live dashboard (always dark): index.html · css/app.css · vendor/ (Apache ECharts 5.5.1, IBM Plex
│                             Sans) served locally, no build step · js/: app.js (tabs, refresh) · api.js (talks to the server)
│                             · one file per view: live.js · trends.js · drivers.js · data.js · recommend.js (+ rec-map.js
│                             the map, rec-plays.js what each message became) · accounting.js (Accounting section: the
│                             EFS statement tree) · notes.js (the bell) · shared: charts.js
│                             · dom.js · format.js · labels.js (names and colors used in more than one view) · theme.js
└─ tests/                     unit tests for db, linking, fuel math, tank helper, current load, Samsara and Datatruck
                              mapping, price sheet, refreshes
```

### Runtime

Step by step, with diagrams: [LOOP.md](LOOP.md).

One Python process: the web server, plus one scheduler thread that runs the jobs **one at a time** → no two jobs
ever race. The scheduler runs each job when it is due. "night": once a night between 03:00 and 06:00 Central
(`NIGHT_HOURS`), one per pass so the engine looks between them; these four hold the engine up for minutes, so
they never run in the day (a night missed waits for the next one):

| Job | Every | Does |
|---|---|---|
| `sync_registry` | night | Refresh Samsara, Datatruck and Telegram copies, then relink `trucks` |
| `load_prices` | 30 min | New sheets posted in the Telegram group "Love's Daily Prices" → data/love's/telegram (Bob's login); sheets not read before → `price_history`; the newest price date → `stores` |
| `read_statements` | 30 min | EFS statement PDFs in `data/efs` not read before → `efs_statements` / `efs_lines` (~8 s per statement) |
| `statement_evidence` | 15 min | Per statement, every Samsara truck's engine fuel used, miles and gauge → `statement_burn` (4 calls); per diesel fill, the gauge's biggest rise and the truck's place → `fill_evidence` (two small calls per fill, 10 trucks per run). Both kept |
| `refresh_orders` | 15 min | Active Datatruck orders + stops → `dt_orders` / `dt_stops` |
| `refresh_fuel.run_recent` | 15 min | Last 3 days of fuel purchases (seconds), for the Live view |
| `refresh_fuel.run` | night | Every fuel purchase and card (3–17 min), catches late edits |
| `refresh_market` | 24 h | EIA weekly diesel prices → `market_prices` (one ~0.8 MB download) |
| `refresh_live` | 5 min | Every truck's latest Samsara position and fuel level → `samsara_live` (one call) |
| `estimate_tanks` | night | Tank helper for the pilot trucks → `tank_estimates` (one gauge-history call per truck) |
| `driver_habits` | night | Every driver's diesel stops of the last 30 days with the gauge around them → `fuel_stops` (one gauge-history call per truck that bought diesel, ~175, ~8 min) |
| `recommend` | 5 min | Each pilot truck: where it should fuel next, recorded, sent to the driver on live trucks (§6.1) → `truck_watch`, `recommendations` |
| `estimate_burn` | 24 h | Each pilot truck's engine calibrated as a fuel meter → `burn_factors` |
| `fill_lookups` | 15 min | Each new diesel fill outside Love's: where the truck was and the gauge before → `fill_lookups` |

`serve` runs these through `jobs/scheduler.py` (one background thread, one job at a time; each run recorded in
`job_runs` and shown on the Data tab). `serve --no-refresh` only shows the data. The database runs in WAL mode so
the dashboard keeps reading while a refresh writes.

**24/7 on this PC (PC-017).** `run.bat` runs `serve` and starts it again 30 s after it stops; a shortcut
"Fuel assistant" in the Windows Startup folder opens it, minimized, at logon. While it runs, `serve` asks Windows
not to sleep (the screen may still turn off) and turns off click-to-select in its window (a click there used to
pause the whole program). A watchdog ends the program when nothing has moved on (no job finished, no truck
looked at) for `STUCK_MIN` (30 min), so a hang is restarted like a crash. After a Windows restart someone has to log in for it to start (no
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
| Helper | `burn_factors` | `unit` | gallons per unit of the truck's engine meter, stretches it is based on | engine fuel factors |
| App record | `truck_watch` | `unit` | one row per pilot truck: its latest look as JSON, with its road | recommendations |
| App record | `recommendations` | `rec_id` | everything a driver would have been told, and what became of it. Kept | recommendations |
| App record | `trips` | `unit` + `order_id` | each load a pilot truck worked: its stops, first and last look, the latest road planned. Kept | recommendations |
| App record | `fill_lookups` | `line_id` | where the truck was at a fill outside Love's, and the gauge before, from `LOOKUPS_FROM` on. Written once, kept, never dropped | fill lookups |

Views (no data, recreated on every start so they always match the code):
- **`fleet`**: **one row per truck** with everything known about it: driver, MPG, latest fuel % and position,
  tank, Telegram group, and whether it is a pilot truck. The only place where automatic and your values meet,
  and yours win (`tank_source` / `chat_source` say which one is used: `manual`, `auto`, or empty).
- **`holes`**: every place the data doesn't link up, one row per problem (hole, item, detail), with `Pilot: …`
  holes for the test subjects (no tank, no Telegram group, no recent fuel reading, no longer linked).
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
- **Careful:** right after a one-side fill the gauge reads full while the other tank isn't; the two
  tanks level out while driving. A fuel % taken just after a stop can overstate what is on board.

### 5.5 Driver habits (`core/habits.py`)
- **Stops:** each driver's diesel purchases grouped by stop (as the tank helper does), with their truck's Samsara
  gauge just before (lowest reading in the 2 h before) and just after (highest in the 2 h after).
- **Habit** (worked out when asked, from the last 30 days): middle gauge level when stopping and after filling,
  share of stops that began below 10% ("ran low"), middle gallons per stop, share of stops under 50 gal
  ("top-offs"), share of gallons at Love's, billed $/gal, and how much more per gallon they pay outside Love's.
  First look (12 trucks, 270 stops, 2026-10-20): stop at ~20%, fill to ~95%; 1 stop in 4 began below 10%.

### 5.6 Fleet status (`core/fleet_status.py`, top of the Drivers tab)
- **One row per Datatruck truck** (`db.fleet_status`, read when the page asks; no table of its own). It starts from
  `dt_trucks`, not from the `fleet` view, so the trucks with no Samsara link are in: they are the ones to look at.
- **On duty:** in transit or available, with an active driver. The page draws these apart from the rest.
- **Type:** the (first) driver's Datatruck type: lease → LO, company_driver → C, company_owner → OO, anything else →
  Other; no active driver → No driver. The tags typed into driver names (LP, CPM, TEAM) are not read.
- **Samsara**, the first check that fails: no Samsara vehicle with the truck's VIN (No device; VIN mismatch when a
  Samsara vehicle is named for the unit), no GPS for `ACTIVE_HOURS`, gauge never reported, gauge silent for
  `ACTIVE_HOURS`, else Working. Each has its "what to do" line on the page (`web/js/labels.js`).
- **Fuel card:** assigned when an active card sits on a driver who is active on this truck, or on the truck itself
  (a card's unit alone doesn't count: many active cards still sit on drivers who left). Without one, a truck that
  bought fuel in the last `FLEET_FUELED_DAYS` is shown apart from one that didn't.
- **Page** (`web/js/fleet.js`, `/api/fleet`, refreshed every 5 minutes): three bars (a question each, with its groups
  and their counts, all trucks and on duty), one square per truck in clusters by status, colored by the picked bar;
  a group clicked lists its trucks.

### 5.7 Fuel cards in eManager (`sources/efs_*.py`, copied from bob-agent 2026-11-22)
- **No API: a real browser.** eManager's bot check lets only a browser through, so it runs in its own Chrome window
  (profile `data/efs-chrome`, port `EMANAGER_CHROME_PORT`), and every request is sent from inside its tab. `efs-login`
  opens it; a person logs in by hand. eManager logs out after 90 idle minutes (the heartbeat every 4 minutes
  prevents that) and ends every login after 24 hours regardless.
- **Two accounts, one login:** `EMANAGER_USERS` names the user that acts for ALIF and for DT; the session switches
  before every card call. "All cards" is one lookup per policy (`EMANAGER_POLICIES`). Pick a card by its id: last
  four digits are not unique.
- **The tools** (`efs_cards.py`): `cards` (look up), `card` (read one), `set_status` (ACTIVE / INACTIVE / HOLD),
  `set_override` (1-9 transactions, always All Locations (the user, 2026-11-22), hand enter; never Product/Limit Override, which opens
  a limits page first, not recorded), `remove_override`,
  `set_prompt` (unit, driver ID or driver name). No one-station override: overrides are always All Locations.
- **Prompts** (recorded 2026-11-22, `data/efs/har/`): Card Lookup's unit, driver ID and driver name are the card's
  prompts. Unit and Driver ID are Exact Match: the driver types them at the pump. Each prompt row has its own Edit
  form; its value box is `cardInfo.matchValue` (Exact Match) or `cardInfo.reportValue` (Report Only). A name is
  kept as typed; Card Lookup prints it in capitals, so names are compared without case.
- **Override:** eManager shows no page with the number of transactions afterwards (checked live 2026-11-22), so a
  change confirms only that the card is in override mode.
- **Safety:** only Look Up, Save, Override, Remove Override, a prompt's Edit and Update are ever pressed (delete card,
  delete prompt, transfer, reset PIN and cancel are refused in code). Every change sends the card's other settings back as its page showed them, then opens
  the card again and stops if anything is not as asked. A card in override mode is locked until the override is off.

### 5.8 The card agent (`jobs/card_agent.py`, `core/card_agent.py`, `sources/claude.py`, `sources/telegram_agent.py`; the user's go 2026-11-23)
Built the way bob-agent's Telegram agent works (`D:/bob-agent/src/agent`, `src/workers/fuel_cards`).
- **Claude** runs through the Claude Agent SDK on this PC's Claude Code login (the plan, not API billing), `AGENT_MODEL`,
  with none of Claude Code's own tools or settings: only four tools (`declined_card`, `look_up_card`, `reply_to_driver`,
  `hand_to_office`), at most 12 turns or $2 a run.
- **Wakes** when the assistant's account is tagged in a truck's group (or answered with card words); never in its office
  or test chat or a group with no truck; each message once; a bare tag within 10 min of a request there joins it.
  Reads the last `AGENT_HISTORY` messages and up to `AGENT_MAX_PHOTOS` photos, plus the truck's facts (drivers, fuel,
  place, nearest Love's, last fills; never a driver ID). eManager logged out: the office is told, Claude isn't asked.
- **A declined card is the owner's rule in code** (bob-agent's, owner 2026-10-11), Claude only passes its line on: whose
  card is the group's truck's driver (a team: the one writing, by name); his card is the one on the unit in his name, in
  ALIF or DT; ACTIVE and not open: opened for `AGENT_OPEN_FILLS` fill, all locations, now; HOLD or INACTIVE: to the
  office (activating is a person's yes); anything else, or opened by the agent within `AGENT_REOPEN_HOURS`: to the office.
  Every opening is posted to the office (`AGENT_OFFICE_CHAT_ID`, else the test group; last four digits only) and
  written to `agent_runs` the moment eManager confirms it.
- **The driver** gets one short line, as a dispatcher writes ("Card is ready, try again now."): never a long number,
  never "ready"/"open" unless a card was opened. `AGENT_ACT = False` makes it watch-only.
- **Runs** as its own program (`card-agent`, `run_agent.bat`); it opens the eManager window and keeps its login alive
  (log in there by hand, every 24 hours). Not done yet: approvals for activating a card (bob-agent asks an approver),
  closing an override nobody used.

### 5.2 Commands (`.venv\Scripts\python.exe src\main.py <command>`)

| Command | Does |
|---|---|
| `sync` | Refresh Samsara, Datatruck trucks and Telegram groups, then relink |
| `prices` | Read new Love's sheets into the price history; the newest goes to `stores` (first run over 228 sheets: ~25 s) |
| `habits` | Collect every driver's fuel stops with the gauge (a few minutes); the Drivers tab shows the habits |
| `statements` | Read new EFS statement PDFs saved in `data/efs` (text PDFs from EFS; a scanned copy is refused) |
| `evidence` | Look up in Samsara now what the statements' evidence lacks, every truck at once (~5 min per statement) |
| `orders` | Copy the active Datatruck orders and their stops |
| `fuel` | Copy every Datatruck fuel line and fuel card (~3 min for ~78K lines) |
| `market` | Copy the EIA weekly diesel prices by region (seconds) |
| `serve [--port 8050] [--no-refresh]` | Run the live dashboard at http://127.0.0.1:8050, and from other office PCs at this PC's office address, **http://10.0.40.40:8050** (the log prints it at start; Windows Firewall is off on this PC). Only this PC and private office networks are let in (`DASHBOARD_NETWORKS`): the Radmin VPN (26.x) gets 403, and so may the name PC-017, which resolves to the Radmin address first. Refreshes data on its own |
| `login` | Log the assistant's Telegram account (`TG_PHONE`) in, once: you type the code Telegram sends it (and its 2FA password). Bob's login (`bob.session`) stays for listing the driver groups |
| `status` | Rows and last refresh time per table |
| `fleet` | Every linked truck: chat, link source, tank, MPG |
| `holes [--all]` | Everything that doesn't link up, grouped |
| `live` | Copy every truck's latest Samsara position and fuel level |
| `pilot` | Each pilot truck: driver, fuel %, where, tank (and its source), MPG, chat, current load |
| `pilot-add <unit> [note]` / `pilot-remove <unit>` | Put a truck in / take it out of the pilot |
| `tanks` | Run the tank helper for the pilot trucks now |
| `lookups` | Look up new fills outside Love's in Samsara now |
| `burn` | Calibrate the pilot trucks' engines as fuel meters now |
| `groups <text>` | Telegram groups whose title contains the text, with their chat ids |
| `set-chat <unit> <chat_id\|none>` | Your Telegram group for a pilot truck (beats auto) |
| `set-tank <unit> <gallons\|none>` | Your tank size for a pilot truck (beats the tank helper) |
| `init-db` | Create the empty database |
| `efs-login` | Open the eManager window and keep its login alive until Ctrl+C (§5.7) |
| `efs-cards <ALIF\|DT> [--by unit\|driver\|driver-id\|card\|xref\|policy] [text]` | List cards, read only; one card found also shows its page |
| `efs-card <ALIF\|DT> [--by unit] <text> --status S \| --override N [--hand-enter] \| --remove-override \| --set unit\|driver-id\|driver VALUE [--send]` | Change exactly one card; without `--send` it only shows the card and the change |
| `agent-login` | Log the card agent's own Telegram login in, once (the assistant's account, a second login: `data/agent.session`) |
| `card-agent` | Run the card agent (§5.8) until stopped; `run_agent.bat` restarts it. Log: `data/agent.log` |

Dashboard rule: it shows numbers so patterns are visible (related series stacked over the same weeks, rolling
comparisons). No takeaway sentences, no answers to one-off questions, no fixed "then vs now" anchors; captions only say
what is drawn and which window. Questions are answered in chat.

Updates reach open pages by themselves: every minute a page asks `/api/version` (when a file in `web/` last changed,
the vendored libraries aside) and reloads when it differs, so a dashboard left open all day never runs old code
against new numbers.

**Recommend tab:** see §6.1.

**Drivers tab:** every driver as a dot (across: gauge when stopping, up: gauge after filling, size: gallons, color:
Love's share; pilot drivers labelled), every stop by gauge level when stopping (at Love's / elsewhere), and a table of
every driver's habit figures.

**Love's price and discount** (Trends): per full week, Love's pump price and Love's discount per gallon, each as
its average (all dollars ÷ all gallons, so it adds up to money) with the middle 80% of the gallons shaded around it
(gallon-weighted 10th–90th percentile, `fuel.spread`), and under them what we paid per gallon for all diesel, at
Love's and outside Love's. Average, not median: the two are within a few cents for price, and for the discount the
median hides the ~3% of Love's gallons billed with no discount. Not min–max: the extremes are single fills (always a
California station; the lowest discount is 0¢ every week). The band's width is mostly geography (state taxes), and the
Love's discount varies by station and by day (cost-plus pricing), so it is not one fixed number. The EIA market
comparison that was here is gone; EIA prices are still copied daily but nothing shows them.

The discount row has three lines (2026-10-28): **At Love's** (the stores we bought at, with the band), **All diesel**
(what we capture: Love's discount on the Love's share, a few cents elsewhere) and **Love's network average** (every
store's pump minus our price, averaged per price sheet day, then over the week's sheet days: `db.network_discounts`,
`fuel.network_by_week`). The network line starts Oct 14, 2026: the sheets have a gap Mar 15 – Oct 14. The price sheet
matches the fuel lines to the cent (pump = sheet retail, billed = sheet net), so the two compare directly. Oct 14–27:
we got 52.3¢ at Love's, the network gave 53.6¢; drivers buy at average stores. The
discount follows the fuel price's direction, not us: our price is cost-plus and moves with wholesale daily, Love's pump
price lags, so the gap shrinks while prices climb (weeks up >5¢: 60¢ average; down >5¢: 73¢). **Buying outside Love's**
(the panel that was "Discount per gallon and what moves it"): Love's share, and *paid extra outside Love's* = outside
dollars − outside gallons × that week's Love's price per gallon (`outside_extra`; ~$4,000 the week of Oct 19). Rough:
the outside fills are compared with Love's fills elsewhere that week, not at the same place.

### 5.3 What the live data looked like (2026-10-18)
125 of ~128 active trucks linked. Gaps found:
- 33 Samsara VINs have two records each (old + new). Solved by the latest-GPS rule; the old records can be cleaned up in Samsara.
- 72 Datatruck trucks have no Samsara record at all (26 of them in transit). No fuel data, so we can't serve them.
- 6 Samsara records are named after a unit but have another truck's VIN ("… SUB …" = substitute truck).
- 18 trucks have 2+ orders *in transit* at once, so the destination is ambiguous (see 6).
- 7 Datatruck units contain dots/letters (`..101`, `555..`, `02A`), probably old or duplicate entries.

## 6. Which load, and which stops are ahead (`core/loads.py`)

Kept from the old engine because the problem stays: `jobs/recommend` uses it.
- Current load: the one in transit, else the earliest pickup. 2+ in transit: the earliest pickup among them.
- Stops still ahead: those after the last stop the truck's **Samsara GPS track** came within **1 mi** of, counting
  only visits from 24 h before the pickup appointment on (not earlier loads at the same place). Datatruck can't
  tell: its stops have no "done" mark and its status lags (live, 2026-10-20: three loads still "dispatched" after
  pickup, one after delivery). The trucks' tracks passed 0.0–0.1 mi from the stops they served. One exception: a
  load "in transit" was picked up, so its first pickup is done even if the GPS never came near it (5502, 2026-11-03:
  the load's pickup was Rumford, ME, the truck never within 50 mi of it, and its road went back to Maine). Stops
  without coordinates are left out.

**Paid above the cheapest Love's nearby** (Live's "Outside Love's this week"; `core/nearby.py`,
`fuel.outside_by_driver`): per fill outside Love's, billed minus gallons × the lowest Love's price within `NEAR_MI`
(25 mi, straight line) on that day's sheet (newest sheet ≤ `SHEET_MAX_AGE_DAYS` old). A fill counts once its lookup has
a place (≤ ~30 min) and a Love's is that close. The circle is a ceiling: it isn't along the route.

## 6.1 The fuel recommendation (`core/recommend.py`, `core/message.py`, `core/burn.py`, `jobs/recommend.py`)

Every 5 min, for each pilot truck. Road: Google Routes from the truck through the load's stops ahead (one call per load,
again as soon as the load's stops ahead change in Datatruck (added, moved or dropped; reached ones just fall off), or if
the truck leaves it by `OFF_ROAD_MI`); Love's within `CORRIDOR_MI` of it, at the newest sheet's prices. A told stop that
isn't on a new road is closed as "replaced" and the next look decides again.

**Fuel now** is the live gauge, never an estimate: the middle of its readings of the last `GAUGE_STEADY_MIN`, at least
`GAUGE_MIN_READINGS` of them looking back up to `GAUGE_LOOKBACK_MIN` (none from before a fill-up), because the gauge wobbles
about 3 points and more at a stop (Tre at his pickup: 24 to 29), and a stopped truck reports rarely. Without a reading from the
last `GAUGE_FRESH_MIN`, no recommendation.

**Two MPGs.** Live MPG comes from the engine: fuel burned follows load × RPM × time, calibrated per truck on
`BURN_DAYS` of gauge drops (job *Engine fuel factors*; `burn_factors`). It matched the gauge within 3 points on 77% of
250-mile stretches, where a 1-hour figure from the gauge alone is mostly noise (it burns ~6 points an hour, the gauge
wobbles ±3). But the road behind only partly tells the road ahead (correlation 0.43), and an empty truck's MPG says little
about its loaded road: while a pickup is ahead, and for `LIVE_MPG_HOURS` after it, live MPG is shown but not used. So:
- **forecast MPG** = half the truck's average, half its last `LIVE_MPG_HOURS` hours: where he'll reach his level. Best
  predictor tested: 2.3 points typical miss at 250 mi (truck average 2.8, last hour 3.0).
- **cautious MPG** = the lower of the two × `WORSE_MPG`: the hard stop. Fewest cases of burning 5+ points more than expected.

**The decision** (`recommend.decide`):
1. *Enough:* the load's last stop is safely in reach at the cautious MPG. No stop.
2. *Too late:* drop Love's he can't reach above `RESERVE_PCT` at the cautious MPG. The last one left is the **hard stop**.
3. *Too early:* drop Love's he'd reach more than `ABOVE_USUAL_PTS` above his usual level (or above his own range). Drivers
   fuel at 36% of the Love's they pass near their usual level, 17% at +5..+10, 9% at +10..+20, 2% above (Oct 14-27, 24 trucks).
4. *Money:* of the rest, the one saving the company the most on a fill-up, against the one nearest his usual level.
5. Nothing fits both: the hard stop wins (Jacob at Dunn NC, 2026-10-19, the user's call), told as a plain fuel stop: its
   old line "The next Love's would put you low" was skipped with nothing happening half the time (the user, 2026-11-10).
   **The warning** ("⚠️ Last Love's you can reach … Fill up, don't skip it") goes on the stop chosen only when no Love's
   after it, nor the load's end, is in reach (`LAST_PCT`): skipping it really means low fuel (6282 passed Oklahoma City
   on a plain message, 2026-11-09). On the roads of the messages sent so far, about 1 in 9.
6. *Tell* when the stop is within `LOOK_MI`. Once told, it stands until he fuels, passes it, or it can't be reached.

**The reserve is elastic** (the user's call, 2026-11-02): it is what the plan aims for, not an alarm. Under it in the worst
case, with Love's still in reach (`LAST_PCT`, what the gauge's own error can hide), the driver is sent to the nearest ("Fuel
is getting low"); the last one in reach has its own message ("Don't skip it"). **The emergency starts only past the last
Love's in reach**, and only after a Love's off the road: one within `NEARBY_MI` (10) of the road, its miles counting the
way there (straight-line miles off times `DETOUR_ROAD_FACTOR`, 1.3), that is in reach is a fill-up stop told as "about 8 mi
off your road" (reason `detour`; 540201 was sent to two city gas stations with Love's Ingalls IN 8 mi off its road in
reach, 2026-11-05, the user's go). Then, with the gauge at `URGENT_PCT` or under, the nearest real truck stop, where the driver buys only
enough to reach the next Love's with the reserve (at least `PART_MIN_GAL`, `recommend.backup_amount`) and fills up there;
a fill-up only when no Love's is ahead (the user's go, 2026-11-04; a line about opening the card was tried and taken out
on the user's word). The message keeps the truck
stop's place (`recommendations.lat/lng`), so later looks find it on the road and it stands like a Love's (until fueled,
driven past or out of reach). Before that, every look took it as passed and sent it again (0226, 2026-11-03: twice to the
driver, 5 min apart, before 0226 was paused and the fix went in). A real truck stop is a place Google tags both truck stop and
gas station, or a Pilot, Flying J, TA or Petro travel center by name (Google tags TA as car repair, Petro as a rest stop;
its truck stop tag alone also covers truck parking): never a gas station in town (`google_places.is_truck_stop`).

**How much** (`fill_up`): at a Love's, always a fill-up, to his usual fill level (the user's go, 2026-11-11). Until then a
Love's within `PART_REACH_MI` past the stop that was `PART_GAP_USD` cheaper for the company **and** at the pump earned a
part fill ("Buy about N gal, don't fill up"): worth ~7¢/gal on paper, but of 12 told to drivers none was bought as asked
(3 stopped there and filled up anyway). Only a truck stop standing in for a Love's out of reach still asks for part of a tank.

**Two stops driven past, then quiet** (`recommend.skipped`, `MAX_PASSED`; the user's go, 2026-11-11): once the driver drove
past two stops told on one tank (since its last fill-up, by the gauge or a purchase; `jobs/recommend._passed`), no further
plain stop is told: the truck shows as "skipped". The last Love's in reach, a detour, low fuel and the emergency are still
told. Why: the first and the second message each ended at our stop ~42% of the time, the third and later 1 time in 23
(50779 got 7 in one day); on the messages of Nov 3-10 the rule would have held 11 of 117, none of which was followed.

**No load** (`core/no_load.py`, `jobs/recommend._no_load`; the user's go, 2026-11-18, "pass to the fueling level, find
the Love's on the direction the unit is going"): a truck with no load ahead (none in Datatruck, or its stops all reached)
has no road. Once its fuel is down to the driver's usual level, it is told the nearest Love's ahead in the direction it
is going: the direction from where its GPS was `HEADING_MI` back to where it is now; ahead = within `AHEAD_CONE_DEG` of
that direction; miles = straight line × `DETOUR_ROAD_FACTOR`, so the message says "📍 About 34 mi ahead". It must be in
reach (`LAST_PCT`), is told within `LOOK_MI`, always a fill-up, reason `no_load`, kept under order 0 with no load id, and
the link navigates to the Love's. Like any plain stop: held while parked (its way isn't known: state "no load, parked"),
after a fill, under 2 mi, and after two passed on a tank; under the reserve it is told anyway. Told, it stands until he
fuels, it is behind him (more than `NEAR_STOP_MI` away and more than a right angle off his way: passed), or out of reach
(replaced). A load that shows up keeps it while it is on the load's road (else "replaced"). Why (study of Oct 1-Nov 17):
trucks spend 42% of their time with no load and buy 10% of their diesel then (~9K gal a week), fueling like on a load
(median gauge 22%, 85% at Love's); the next load shows up a median 27 h later, home explains 7%, and 71% of trucks moving
with no load keep their direction. Datatruck is often behind: 23% of loads are entered after their pickup time.
Settings from a replay on 251 no-load Love's fills made while driving: with the direction over 10 mi and ±45°, from 15 /
30 / 45 mi before the Love's he used, our nearest ahead was that one 80% / 66% / 54% of the time (15 mi and ±30°: 70% /
57% / 48%).

**Never a Love's behind him** (`geo.behind`, `jobs/recommend._against`/`_by_way`/`_told_now`, `loads.pick`; the user's go,
2026-11-22, after 1767 was told Love's he had already passed and got down to 4% on I-30). His way is the direction of
his last `HEADING_MI` of GPS, driven within `HEADING_MAX_MIN` and since his last stop (`no_load.set_off`: a pickup or a
delivery can turn him around; no load uses the same); a place more than `NEAR_STOP_MI` away and more than `BEHIND_DEG`
off it is behind him. The road may rightly turn back at the load's next stop (268331 arriving at his Reynoldsburg pickup,
then west to California), so only the road up to that stop, and the Love's before it, are judged by his way. On a load:
when the road `ROAD_AHEAD_MI` on from his mile lies behind him (a load in Datatruck he isn't driving makes a road that
starts with a U-turn: 1767's said Kansas City, he drove to Texas), or the road's stop does, he is told the nearest Love's
ahead in his direction as with no load, reason `heading`, state "off its road", kept under the load; the road is kept,
so Google isn't asked again before `REROUTE_MIN`. A stop told on the road that lies behind him is passed. A stop told by
his way (`no_load`, `heading`) is judged by his way whatever load comes, and a stop told on another load is judged on
this load's road (it stands while it is on it), so a load put right never brings a second message for the same fill.
Datatruck putting it right: changed stops or a closed load make a new road at once; an added load takes over from the
one still "in transit" when the old one's next stop lies behind him (`loads.pick`; 1767's Kansas City was ~125° off, so
there the road check did it). The road is kept only near its part ahead of his mile: driven back along it, he left it
(his mile can't go back: 9606 was told "11 mi" for a Love's 88 mi off). Why `BEHIND_DEG` 135: GPS of the 433 messages of
Nov 15-22: 14 told a Love's already behind him (151-180° off), 331 were driven toward; of those, 3 were over 135°.

**Regions** (`recommend.regions`) are the same forecast further down the road, starting from the stop told: how many stops
the load needs, roughly where, and where a much cheaper Love's lies past one. Near, they follow the hard stop's rule; far
down the road its margin hides every Love's, so there the forecast alone says where. Shown on the tab; they change silently. In the replay they added no
money by themselves over one stop at a time.

**The message** must always be true: "cheaper" is only ever said of the pump price the driver sees (company prices decide,
but many drivers are charged the pump price, so a stop can look dearer to him). Truck stops only as a backup
(`sources/google_places.py`).

**Expect**, from the fairest replay (real gauges, same-day prices, 153 fill-ups, 24 trucks, Oct 14-27): about 6¢/gal if
every driver follows (0.3-12¢), plus the part fills' ~7¢. The rule picked the driver's real place 18% of the time; stops
moved a middle of 124 mi. Whether drivers accept that is what the live test is for. Not known to the rules: driving
hours, appointments, weight limits, how hard a station is to reach. A truck's own fill limit (e.g. a weight limit) isn't
a setting yet: only his usual fill level is used.

**Past trips** (the user's ask, 2026-11-05): every load the engine looks at is kept in `trips` (one row per truck per
load: stops, first and last look, the latest road planned; `jobs/recommend._keep_trip`). Under the truck's title a picker
lists them; a past trip (`/api/recommend/past`) shows its road planned, the road driven and fill-ups and the gauge over the
trip (Samsara), and its messages with what came of them, and hides the Love's-ahead table (it belongs to the plan now).
Loads before Nov 5 were rebuilt from their messages: no stops, no road planned. The current trip's map starts at the last
message when that is earlier than the road (a detour that remade the road no longer hides what happened).

**Recommend tab** (`web/js/recommend.js`; `/api/recommend`, `/api/recommend/truck`, `/api/recommend/trip`): the test trucks on
the left (fuel now, where the driver would be told to go). The tab opens with none picked (the user's ask, 2026-11-18):
every truck on the map where Samsara has it, its fuel % in a bubble above (red at 10% or under, amber at 25% or under,
grey while the gauge is silent; where bubbles would overlap the lowest fuel keeps its own), a click on one opens its
plan; pressing the tab again goes back to all trucks. For the one picked (`#recommend/0530` links to it), five figures
(fuel now, when the zone starts, when he crosses the reserve, when he runs out, the stop), then the map. **One fuel zone
per tank is drawn on the road** (`recommend.zones`): green from where the gauge reaches his level (usual + 5, expected MPG) to
where it crosses the reserve (cautious MPG), red from there to where the truck runs out (cautious MPG). A Love's in the green
is one the rules call safe and at his level; one in the red isn't safe. Zones after a planned fill-up use the expected MPG:
a rough look ahead. Every Love's on the road shows its price, company or pump by a toggle (pump, to send a screenshot to a
driver some day), those that don't fit on screen on hover. A second toggle shows the Love's within `NEARBY_MI` of the road but
off it, with how far (the rules take one only when none on the road is in reach; one chosen shows as the stop). Below: what we told him and what he did, message by message (fueled there, how much,
at what price, or elsewhere, or drove past); every Love's ahead with its arrival, worst case, prices and verdict; his gauge.

**The message:** the station with its pump price (its name in Telegram shows it on the map), where, what to do, what he
arrives with as "8% (12 gal)" (the gauge's percent, and gallons from the tank size), and any reason; then the road's link. The pump price is the user's call
(2026-11-02), honest even when a stop passed was cheaper for him.

**The highway and exit** (the user's ask, 2026-11-11): after the miles, "📍 In 34 mi, I-90 (Exit 34)". From Love's own
store pages, the one source (`sources/loves_web`: `loves.com/locations/<store no>`, heading "Belmont, OH | Exit 208/OH-149
on I-70"): each store's page is read once and kept in `store_exits` (job "Love's exits", nightly for new stores; `main.py
exits` by hand), and `db.stores` hands it to the message as `Store.way`. The price sheets have no exits. A Love's whose
page names no exit, and a truck stop that isn't a Love's, go out without one. A version from Google's driving directions
was built the same day and removed on the user's word ("no endless patches"): it missed 6 of 45 stops that Love's pages have.

**The link** ("▶ Start the road"): a Google Maps link with no start, so it navigates from the phone's location, through the
fuel stop (and the fill-up after a part fill, and pickups still ahead, in road order, at most `LINK_MAX_VIA` on the way) to
the load's last stop. Google's docs say up to 3 stops on mobile browsers, that navigation starts when the origin is left out,
and that some products may ignore stops: check on a phone before going live. Maps routes like a car, not a truck.

**When a fuel stop is not told** (`core/recommend.quiet`, the user's go, 2026-11-04): for `FUEL_HOLD_MIN` (60) after the
gauge rose like a fill (`truck_watch.fueled_at`), because the fill may still be going on: 14755 was told Tolleson again at
the pump, its gauge half way up, which looked to this driver like his usual level; and when the stop is under
`NEAR_STOP_MI` (2) away, because the driver is already there (0226 Piedmont, 0.8 mi); and while the truck is parked
(moved under `PARKED_MI`, 1, in `PARKED_MIN`, 15; state "parked"), so the stop is told once it moves, not hours before
(540201 was told at 08:18 while parked and passed the stop 3 h later, 2026-11-05). Low fuel is always told: urgent,
under the reserve (the last Love's in reach then too). The last Love's in reach with the reserve still kept waits like
any stop. Messages that did go out again by mistake are marked `status = "repeat"`
by hand (0226's second Inman, 14755's second Tolleson): they own no purchase and the Live tab leaves them out.

**Sending:** for a truck in `LIVE_UNITS`, `jobs/recommend.send_to_driver` sends the message from the assistant's account
(Migo) to the truck's own group and stamps `sent_at`; a failed send is logged and the message stays "not sent". Every
message is also copied to "Test fuel" (`TEST_CHAT_ID`), headed "📨 Sent to the driver" or "🧪 Test"; that copy refuses if
the chat is ever a truck's own group. On the dashboard (`web/js/notes.js`, the user's ask 2026-11-04) a bell in the top
bar counts the messages sent that you haven't marked checked (kept in the browser), also in the tab's title; its list
shows each with how long ago it went out, "Open plan" (the truck on the Recommend tab) and "Mark checked"; a message
that goes out while the page is open pops up at the top right.

**Rollout:** silent stage on the 5 trucks from 2026-11-02; 0530 and 14755 live on the user's go the morning of 2026-11-03;
8 more that afternoon on the user's go (6 of them added to the pilot the same hour, their first plans checked before
going live). Batch 2 on 2026-11-04, the user's plan: cover every company driver in time and bring in lease and owner
drivers, half and half; the lease ones picked by the discount they missed outside Love's in 30 days (`next_batch.py` in
the session scratchpad), each checked for a group Migo is in (50779 wasn't: skipped). A truck whose stop was already
chosen silently has that silent message set "replaced" on going live, so the driver gets it (19727, Greenville).
More trucks only on the user's go. The Recommend tab marks live trucks and each message as sent or not, with where the truck fueled.

**Fuel plans on the Live tab** (`core/outcomes.messages_sent`, from `LIVE_FROM` 00:00 Central to the newest purchase),
drawn so the scope of each figure shows without asking (the user, 2026-11-03):
- *Messages sent to drivers* (`web/js/messages.js`, redone 2026-11-18 on the user's ask: "how many messages, from
  when, and why?"): full width, one square per message colored by what became of it. Filled = ended and counted
  (fueled at our stop, at another Love's, outside Love's, drove past); hollow or dim = not counted (fueled by the gauge
  but the purchase not in Datatruck yet, on the way, called off by us). Followed = fueled at our stop ÷ ended. **By
  day**: a column per day since `LIVE_FROM`, squares stacked from the bottom in the key's order, "+N" on top = trucks
  that got their first message that day, under it the day's count and follow rate. **By why we sent it**: a row per
  reason (`labels.WHY`: fuel zone, last Love's, last before the reserve, under the reserve, detour, no load, low fuel)
  with its count and follow rate. Pointing at a square shows that message (when, unit and driver, station, why, result).
  The two panels below it (Love's share, price and discount per gallon) sit side by side at their own height.
- *Bought at Love's*: Love's share of diesel gallons against `LOVES_TARGET` (99.9%), two bars: the live trucks (their
  fills after each one's first message) and the whole fleet (every truck, every company).
- *Discount per gallon*: at stops we sent (the whole discount on those fills, the user's choice 2026-11-03: it includes
  discount the driver would have had at any Love's) beside the whole fleet's.
- *Discount kept and missed* (`fuel.discount_periods`, `dashboard.discount_payload`; the user's ask 2026-11-04, "read in
  one glance"): Day / Week / Month switch (14 days, 12 weeks, 6 months). On top, the period in progress in three
  figures; below, smooth stacked lines over the finished periods (the user's pick over bars): the fleet on its own (its
  discount less our stops' part), the part at stops we sent, and on top the discount missed outside Love's
  (`fuel.missed_discount`: each fill outside Love's at that day's average Love's discount per gallon, less the discount
  it got). The top line is what the period could have kept at Love's; as plans spread the blue band grows and the pink
  shrinks. Stacked, not side by side: beside the fleet's $45-60K a week, our part and the missed part would lie flat on
  one axis. The period in progress stays out of the lines (cut short, it would drop like the fall we watch for). Missed
  ran ~$5-7K a week, $24-26K a month in Sep-Oct (about 45¢ on each gallon bought outside Love's).

## 7. Settings (`config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `RESERVE_PCT` / `WORSE_MPG` | 10 / 0.85 | never plan to arrive under this, at the cautious MPG (the lower of average and live, 15% worse). 20% was tried first: on October's roads 15% puts more stops near the usual level (83% to 86%), with no more runs reaching empty |
| `ABOVE_USUAL_PTS` / `LOOK_MI` | 5 / 60 | a stop reached more than this above his usual level is too early / he is told this close. 150 was tried first: a stop told that early rested on one moment's numbers and stood for hours (Tre, 2026-11-02). On October's roads 60 saves +0.8¢/gal (0.2 to 1.5) over 150, with the same safety; the driver gets about an hour's warning |
| `PART_GAP_USD` / `PART_REACH_MI` | 0.50 / 500 | a much cheaper Love's past a region is marked (no part fill at a Love's since 2026-11-11) |
| `PART_MIN_GAL` / `PART_MARGIN_GAL` | 30 / 25 | how much to buy at a truck stop before a Love's |
| `MAX_PASSED` | 2 | stops told and driven past on one tank before plain stops go quiet |
| `HEADING_MI` / `AHEAD_CONE_DEG` | 10 / 45 | no load: its direction from where its GPS was this far back / a Love's within this many degrees of it, either side, is ahead |
| `HEADING_MAX_MIN` / `BEHIND_DEG` / `ROAD_AHEAD_MI` | 30 / 135 / 20 | its direction only from miles driven this lately / a place more than this off it is behind him / the road this far on shows where it goes |
| `GAUGE_STEADY_MIN` | 10 | the fuel now is the middle of the gauge readings of this many minutes. On October's readings: half the jumps of the newest reading, false rises 6.6% to 1.0%, reads only 0.3 points high while driving (20 min: 0.6) |
| `LAST_PCT` | 3 | a Love's reached with less than this in the worst case is out of reach |
| `URGENT_PCT` | 25 | with no Love's in reach, the truck stop backup starts at this gauge level |
| `LIVE_MPG_HOURS` / `BURN_DAYS` / `BURN_STRETCH_MI` | 3 / 14 / 250 | live MPG's window; how a truck's engine is calibrated |
| `HABIT_DAYS` | 30 | driver habits: stops of the last this many days |
| `RAN_LOW_PCT` | 10 | driver habits: a stop that began below this gauge level "ran low" |
| `TOP_OFF_GAL` | 50 | driver habits: a stop buying less than this is a top-off |
| `FLEET_FUELED_DAYS` | 14 | fleet status: a truck with no card assigned that bought fuel within this many days is shown apart |
| `TANK_DAYS` | 30 | tank helper: fill-ups of the last this many days |
| `TANK_WINDOW_MIN` | 120 | tank helper: gauge readings this long before/after a purchase; purchases closer are one stop |
| `TANK_MIN_RISE_PCT` | 25 | tank helper: smaller gauge rises are skipped |
| `TANK_MIN_FILLS` | 3 | tank helper: fewer usable stops → no estimate |
| `NEAR_MI` | 25 | Live: a fill outside Love's is compared with the cheapest Love's this close |
| `SHEET_MAX_AGE_DAYS` | 3 | ...on the newest price sheet at most this old |
| `LOOKUPS_FROM` | 2026-09-28 | fills outside Love's are looked up from this day on |
| `STUCK_MIN` | 30 | no job finished and no truck looked at for this long: the program ends itself and run.bat restarts it |
| `LOG_MAX_MB`, `LOG_FILES_KEPT` | 20, 4 | `data/fuel.log` starts afresh at 20 MB; the 4 newest old ones are kept |
| `TG_SESSION_PATH` | data/telegram.session | the assistant's Telegram login: sends the messages |
| `TG_GROUPS_SESSION_PATH` | data/bob.session | the login that lists the driver groups (linking); point it at the assistant's once that account is in them all |

`ACTIVE_HOURS` (24) decides which trucks the holes list treats as active.

`.env` keys: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `DT_SLUG`, `DT_API_TOKEN`, `DT_WEB_REFRESH_TOKEN`,
`SAMSARA_API_TOKEN_TTL` and `SAMSARA_API_TOKEN_DT` (one Samsara account per carrier, `SAMSARA_ACCOUNTS`; added DT
2026-10-23: 92 vehicles, 65 of them trucks moved from TTL, whose old TTL records stopped reporting — linking keeps the
record that reported last), `GOOGLE_MAPS_API_KEY` (Routes API, created 2026-10-20), `TEST_CHAT_ID` (the test group).

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
| 6 ✅ | Love's price history (228 sheets) + **driver habits** (Drivers tab) | `prices`, `habits`, then the Drivers tab |
| 7 ✅ | Run 24/7 on this PC: `run.bat` (restarts itself), Startup-folder shortcut, no sleep while running, dashboard open to the office network | log off and on: the "Fuel assistant" window opens by itself |
| 8 ✅ | **New recommendation engine, silent** (§6.1) | `pytest` green; the Recommend tab fills in |
| 9 | Silent week on the 5 trucks, reviewed with the user | — |
| 10 | Live on the 5 trucks, on the user's go: sending added | drivers' groups get messages |

## 9. Code rules

1. Clean, concise, no spaghetti. Clear separation of responsibility (section 4).
2. Simple over clever. Prevent edge cases with better design, not extra branches.
   Never cut functionality or robustness.
3. Every file starts with a `#` comment (1–2 lines) saying what it does.
4. Every function has a `#` comment (1–2 lines). If it can't be explained that briefly, split the function.
5. Any line that isn't obvious at a glance gets a short `#` comment.

## 10. Open items

- **Price history has gaps**: since Aug 1 only Oct 14, 16-20 and 22. Comparing past purchases with "the Love's
  price that day" needs the daily sheets for the days compared; without them a purchase is set against months-old
  prices (a fleet ranking done that way on 2026-10-22 was wrong and thrown out).
- **Love's prices:** drop each day's sheet anywhere under `data/love's/`
  (or automate it: the Gmail daily price list, or Love's own price API). Up to date on 2026-10-20.
- Trucks with 2+ in-transit loads (6): 17 of 192 trucks on 2026-10-21. Mostly Datatruck not marking the earlier
  load delivered (the GPS check skips it).
- Right after a one-side fill the gauge overstates the fuel on board (5.4).
- 72 Datatruck trucks not in Samsara: which system tracks them, if any?

**Freeze, 2026-10-28 11:04–13:50 ET**: a click in the server's console window (Windows QuickEdit: the title turned
"Select Fuel assistant") paused its console output; the fuel-lines job saved its rows and hung on its "refreshed" log
line, and the watchdog hung on its own log line, so nothing restarted it: no job ran for 2¾ h.
Fixed: `serve` turns QuickEdit off for its window (`server._no_click_pause`, see LOOP.md §5), and the watchdog exits
through a 10 s timer even if its log line can't be written.
