# How the loop works

What runs on this PC and in what order. Numbers in `CAPS` are settings in
`src/base/config.py`; the rest of the design is in [PLAN.md](PLAN.md).

## 1. One program, two parts

```
                    run.bat  (opened at logon; starts the program again 30 s after it stops)
                       │
                       ▼
  ┌─────────────────────────── main.py serve ────────────────────────────┐
  │                                                                      │
  │   Web server (main thread)              Scheduler (background thread)│
  │   answers the browser:                  every 30 s: runs the jobs    │
  │   the page from web/,                   that are due, one at a time  │
  │   the numbers from /api/...                                          │
  │          │ reads                                  │ writes           │
  │          ▼                                        ▼                  │
  │   ┌──────────────────────── data/fuel.db ─────────────────────────┐  │
  │   │ copies of Samsara, Datatruck, Telegram, Love's, EIA           │  │
  │   │ helper results (tanks, driver habits, lookups) · job_runs     │  │
  │   └───────────────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────────────┘
          ▲                                           │ calls
          │ port 8050                                 ▼
   browser on this PC              Samsara · Datatruck · Telegram (read-only) · EIA
   or another PC on the network    + Love's sheets dropped in data/love's/
```

The two parts don't talk to each other: the scheduler writes into the database, the web server reads from it.
The database runs in WAL mode, so the page can read while a job writes.

## 2. The scheduler loop

```
  ┌──► for each job in the list below, top to bottom:
  │        last start (job_runs table) at least "every" minutes ago?
  │            no  → skip it
  │            yes → record "started" → run it → record "finished", or the error
  │
  │    wait 30 s
  └──────┘
```

| # | Job (name on the Data tab) | Every | Gets | Writes |
|---|---|---|---|---|
| 1 | Truck positions and fuel levels | 5 min | Samsara, one call for all trucks | `samsara_live` |
| 2 | Fuel purchases, last days | 15 min | Datatruck, last 3 days | `fuel_lines` (those days) |
| 3 | Active loads | 15 min | Datatruck orders and their stops | `dt_orders`, `dt_stops` |
| 4 | Love's prices | 30 min | sheets in `data/love's/` not read before | `price_history`, `stores` |
| 5 | Market diesel prices (EIA) | 24 h | EIA weekly prices | `market_prices` |
| 6 | Trucks, drivers, Telegram | nightly 03–06 CT | Samsara vehicles, Datatruck trucks and drivers, Bob's groups | the copies, then `trucks` (links) |
| 7 | Fuel purchases, full copy | nightly 03–06 CT | every Datatruck fuel line and card (3–17 min) | `fuel_lines`, `fuel_cards` |
| 8 | Tank estimates (pilot trucks) | nightly 03–06 CT | fuel lines + Samsara gauge history | `tank_estimates` |
| 9 | Driver habits | nightly 03–06 CT | fuel lines + Samsara gauge history (~8 min) | `fuel_stops` |
| 10 | Fill lookups | 15 min | fills outside Love's + Samsara GPS and gauge | `fill_lookups` |
| 11 | Fuel recommendations (silent) | 5 min | the DB + Samsara GPS and engine + Google (below); sends nothing | `truck_watch`, `recommendations` |
| 12 | Engine fuel factors | 24 h | Samsara engine and gauge history of the pilot trucks | `burn_factors` |
| 13 | Love's exits (new stores) | nightly 03–06 CT | the own page of each Love's store not read yet (loves.com) | `store_exits` |

How it behaves:
- **One job at a time.** A long job (7 or 9) makes the others wait their turn; nothing ever runs twice at once.
- **The slow daily jobs (6–9) run at night**, once between 03:00 and 06:00 Central (`NIGHT_HOURS`), one per pass:
  the engine has its look between two of them. A night missed (the program down) or a failed run waits for the
  next night, never the day (the user's go, 2026-11-05, after they paused the engine for 28 min one morning).
- **The order matters.** When several jobs are due in the same pass, the quick, live ones run first.
- **The clock is in the database**, not in memory. After a restart, a job that ran 10 minutes ago waits 5 more
  minutes; only jobs that are due run.
- **A failing job** is written to `data/fuel.log`, shown with its error on the Data tab, and tried again at its
  next turn. The other jobs carry on.
- **A refresh that fails or comes back empty** keeps the previous copy, so an API hiccup can't empty a table.

### One look at one truck (job 11)

```
  tank, position, a fresh gauge reading? ─ no → "no fresh gauge": nothing can be said
     │ yes
  which load, which stops ahead (GPS decides) ─ none → "no load"
     │
  its road: kept from before, or new from Google for a new load or when it left the road
     │
  a stop told earlier: fueled? passed? no longer safe? → closed, with what became of it
     │ still standing → nothing new is said
     ▼
  MPG: forecast (average + last 3 hours by engine) and cautious (the lower, 15% worse)
     │
  every Love's on the road → enough for delivery? → else too late? too early? then money
     │
     ├ stop within 60 mi → told, always "Fill up" (live trucks: to the driver; all: a copy to "Test fuel").
     │     Not told after two stops driven past on this tank ("skipped"): quiet until the last Love's or low fuel
     ├ stop further on → watching
     ├ under the reserve, Love's still in reach → the nearest, told when close. No emergency
     └ no Love's in reach, gauge 25% or under → urgent, the nearest real truck stop
```
Details and why: PLAN.md §6.1. Everything shows on the dashboard's Recommend tab.

## 3. What keeps it running

```
  log on to Windows
                       │
                       ▼
  Startup folder: shortcut "Fuel assistant" opens run.bat in a minimized window
                       │
     ┌─────────────────▼──────────────────────────────┐
     │ main.py serve                                  │◄──┐
     │ · asks Windows not to sleep while it runs      │   │
     │ · web server + scheduler (sections 1–2)        │   │
     │ · watchdog: stuck 30 min → ends itself         │   │
     └─────────────────┬──────────────────────────────┘   │
                       │ stops, crashes, or hangs         │
                       ▼                                  │
                   wait 30 s ─────────────────────────────┘
```

- **Crash:** the program ends and run.bat starts it again 30 s later (tested by killing it; it came back each time).
- **Hang** (a job stuck, e.g. on a network call that never answers): the watchdog sees no progress for
  `STUCK_MIN` (30 min; the longest job takes ~17) and ends the program, so run.bat restarts it fresh. Progress is a
  job finished or one truck looked at by the engine: its first pass after a restart takes ~25 min (each truck's GPS
  track is fetched anew), and on 2026-11-20 it nearly got cut off when only finished jobs counted.
- **Sleep:** the program asks Windows to stay awake (the PC was set to sleep after 2 h idle: on 2026-10-21 that
  stopped it for 2.3 h before this; none since, overnight included).
- **A click in the window:** Windows starts a text selection ("Select Fuel assistant" in the title) and pauses the
  program until it ends — the watchdog too, since it writes a log line first. On 2026-10-28 that froze the refreshes
  for 2 h 50 min. `serve` now turns click-to-select off in its window when it starts.
- **Windows restart** (updates, a power cut): it starts only once someone logs in — this PC has no automatic login,
  and setting one up needs the admin password. Windows may restart for updates outside its active hours (8–17).
  Log in again remotely with AnyDesk if needed.
- Closing the "Fuel assistant" window stops everything until the next logon; double-click `run.bat` to start
  it again.
- What a restart keeps: everything is in the database, written in all-or-nothing steps. Jobs run on when they are
  due (`job_runs`). A job cut off mid-run (no finish time) is due again at once, so a daily job isn't lost for a
  day when the program restarts while it runs.
- To check it's alive: the Data tab lists each job's last run and any error; `data/fuel.log` has the details.
  Only `serve` writes that file (one-off commands print to their window). At 20 MB it starts afresh and the old one
  becomes `fuel.log.1` (then `.2` … `.4`; older ones are deleted), so the log never passes ~100 MB. A network
  failure in the engine is one line per truck, not the full error trace: an 8-hour outage on 2026-11-20 wrote
  72 MB of those traces (the file had grown to 277 MB).

## 4. Not in the loop yet

- **Sending to drivers.** Recommendations are recorded and copied to the test group; nothing tells drivers anything until the user says go.
- **Daily prices.** Job 4 only reads sheets someone put in `data/love's/`.
