# How the loop works

What runs on this PC, in what order, and how a fuel plan gets made. Numbers in `CAPS` are settings in
`src/config.py`; the rest of the design is in [PLAN.md](PLAN.md).

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
  │   │ helper results (tanks, driver habits) · plans · job_runs      │  │
  │   └───────────────────────────────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────────────┘
          ▲                                           │ calls
          │ port 8050                                 ▼
   browser on this PC              Samsara · Datatruck · Telegram · Google Routes · EIA
   or another PC on the network    + Love's sheets dropped in data/love's/
```

The two parts don't talk to each other: the scheduler writes into the database, the web server reads from it.
The database runs in WAL mode, so the page can read while a job writes. One exception: for the Plans tab, the web
server asks Samsara for the road driven since a plan (2–7 s). A background loop (`dashboard.keep_fresh`) keeps each
pilot truck's newest plan built and rebuilds it every 5 min (`TRIP_CACHE_S`) while its load is open; any plan opened
before is answered from its last build at once and rebuilt behind the scenes. Only a plan never opened waits.

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
| 4 | Fuel plans for pilot loads | 5 min | the DB + Samsara GPS + Google (section 3); sends and edits Telegram messages | `plans`, `plan_messages` |
| 5 | Love's prices | 30 min | sheets in `data/love's/` not read before | `price_history`, `stores` |
| 6 | Market diesel prices (EIA) | 24 h | EIA weekly prices | `market_prices` |
| 7 | Trucks, drivers, Telegram | 24 h | Samsara vehicles, Datatruck trucks and drivers, Bob's groups | the copies, then `trucks` (links) |
| 8 | Fuel purchases, full copy | 24 h | every Datatruck fuel line and card (~3 min) | `fuel_lines`, `fuel_cards` |
| 9 | Tank estimates (pilot trucks) | 24 h | fuel lines + Samsara gauge history | `tank_estimates` |
| 10 | Driver habits | 24 h | fuel lines + Samsara gauge history (~5 min) | `fuel_stops` |

How it behaves:
- **One job at a time.** A long job (8 or 10) makes the others wait their turn; nothing ever runs twice at once.
- **The order matters.** When several jobs are due in the same pass, positions (1) and loads (3) are refreshed
  before the planner (4) uses them.
- **The clock is in the database**, not in memory. After a restart, a job that ran 10 minutes ago waits 5 more
  minutes; only jobs that are due run.
- **A failing job** is written to `data/fuel.log`, shown with its error on the Data tab, and tried again at its
  next turn. The other jobs carry on.
- **A refresh that fails or comes back empty** keeps the previous copy, so an API hiccup can't empty a table.

## 3. How one plan is made (job 4)

```
  every 5 min, for each pilot truck (its row in `fleet`):

  its GPS track from Samsara, one call: from its followed plan's start, or 24 h before its earliest pickup
     │
     ▼
  its followed plan (the newest): anything happened since the last look?   (section 4)
     │ yes → a new full message queued (and re-planned first when the driver went off plan)
     ▼
  its active loads (from job 3)
     │ none → skip
     ▼
  which load is it on, and which stops are still ahead?
  in transit first, then by pickup; a stop is done once the GPS came within 1 mi of it
     │ no stop ahead on any load → skip (between loads)
     ▼
  does this load already have a plan? ── yes → skip: one plan per load
     │ no
     ▼
  tank size, fuel reading and position known? ── no → warning in the log, tried again in 5 min
     │ yes
     ▼
  Google: the road from where the truck is now through the stops ahead
     │
     ▼
  every Love's within 1.5 mi of that road (CORRIDOR_MI), with its price from the newest sheet
     │
     ▼
  planner: cheapest stops and gallons
  · tank never below 10% (RESERVE_PCT) · at least 20 gal a stop · each stop counts $40
  · aims for 40+ gal at the last stop (END_MIN_GAL) · a Love's off the road pays for its detour
     │
     ▼
  saved in `plans`, with the truck, load, road and Love's as they were → shows on the Plans tab
  (when no choice of stops keeps 10% in the tank, it is saved as "no plan")
  + its progress started (`plan_progress`) and its first message queued (`plan_messages`) for "Test fuel"
     │
     ▼
  end of the run: every queued message less than 60 min old (SEND_WITHIN_MIN) is sent from Bob's account
  · sent → sent_at recorded, and the plan's previous message gets "⤵ Newer update below" instead of its link
  · failed → stays queued, tried again next run · older → dropped, the truck moved on
```

## 4. The life of one load

```
  load B assigned in Datatruck, while the truck still drives load A
     │
     │ every 5 min: A still has stops ahead, so A is the truck's load and B waits
     ▼
  the truck's GPS comes within 1 mi of A's last stop
     │
     ▼ next planner run (within 5 min)
  plan for B, from where the truck is at that moment, through B's stops in road order,
  e.g. truck → fuel 1 → PU → fuel 2 → DEL; "⛽ New fuel plan" goes to "Test fuel" with "▶ Start the road"
     │
     │ the plan itself is never changed (the Plans tab shows how it held up); it is followed:
     ▼
  every 5 min, from the GPS since the plan and the fuel lines (in every 15 min):
     │
     ├─ PU reached ............................ "✅ PU … done"
     ├─ fuel bought at a planned stop ......... "✅ Stop done · bought N gal at …"
     ├─ fuel bought elsewhere ................. "⚠️ Off plan · bought N gal at …"  ┐ the rest of the road
     ├─ left a planned stop, no fill .......... "⚠️ Stop missed"                   ┘ re-planned from here
     │    (15 min after leaving when the gauge shows no fill, else 1 h without a fuel line)
     ├─ a stop passed, nothing to tell yet .... no message: the newest one's link just skips it
     │
     │  each event → one new full message: done things crossed out, "▶ Continue the road" through what
     │  is left, and the message before it says "⤵ Newer update below" instead of its link
     ▼
  the truck reaches B's DEL → "🏁 Delivered · plan followed / not followed", the plan beside what was
  bought and the extra cost → the truck's next load gets its plan
```

## 5. What keeps it running

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
- **Hang** (a job stuck, e.g. on a network call that never answers): the watchdog sees no job finish for
  `STUCK_MIN` (30 min; the longest job takes ~5) and ends the program, so run.bat restarts it fresh.
- **Sleep:** the program asks Windows to stay awake (the PC was set to sleep after 2 h idle: on 2026-10-21 that
  stopped it for 2.3 h before this; none since, overnight included).
- **Windows restart** (updates, a power cut): it starts only once someone logs in — this PC has no automatic login,
  and setting one up needs the admin password. Windows may restart for updates outside its active hours (8–17).
  Log in again remotely with AnyDesk if needed.
- Closing the "Fuel assistant" window stops everything until the next logon; double-click `run.bat` to start
  it again.
- What a restart keeps: everything is in the database, written in all-or-nothing steps. Jobs run on when they are
  due (`job_runs`), messages still queued are sent (if under an hour old), followed plans carry on from their saved
  progress. A job cut off mid-run shows on the Data tab with no finish time until its next run.
- To check it's alive: the Data tab lists each job's last run and any error; `data/fuel.log` has the details.

## 6. Not in the loop yet

- **Drivers' groups.** New plans go only to the test group "Test fuel"; the drivers get them when we go live.
- **The next load.** When the next load is already booked, the plan still ends at the current load's last stop.
- **Load changes.** The rest of the road is re-planned when the driver goes off plan, but not yet when dispatch
  changes the load's stops after the plan was made.
- **Daily prices.** Job 5 only reads sheets someone put in `data/love's/`.
- **No plan.** When no Love's is in reach from where the truck is, the plan sends it to a truck stop nearby first
  (Google Places). When the Love's are too far apart further along the road (Maine, for example), the plan is still
  empty and a driver would get nothing; it should say where fuel is there instead.
