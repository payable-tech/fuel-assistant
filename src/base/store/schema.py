# The database's shape: every table and view, as SQL. base/store/db.py makes sure the database file matches it and
# holds the functions that read and write the tables.
from base import config

# Raise when a refreshed table changes shape: those tables are then dropped and refilled by their jobs.
SCHEMA_VERSION = 2

TABLES = """
-- ===== Source copies: each replaced whole by its own source. Never edit by hand. =====

-- Writer: sync (Samsara).
CREATE TABLE IF NOT EXISTS samsara_vehicles (
    samsara_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    vin         TEXT NOT NULL,
    mpg         REAL,
    last_gps_at TEXT,
    synced_at   TEXT NOT NULL
);

-- Writer: sync (Datatruck). Unit and VIN are deliberately not unique here, so duplicates can show in `holes`.
CREATE TABLE IF NOT EXISTS dt_trucks (
    dt_id     INTEGER PRIMARY KEY,
    unit      TEXT NOT NULL,
    vin       TEXT NOT NULL,
    status    TEXT NOT NULL,
    ownership TEXT,
    synced_at TEXT NOT NULL
);

-- Writer: sync (Datatruck drivers, active or not).
CREATE TABLE IF NOT EXISTS dt_drivers (
    driver_id       INTEGER PRIMARY KEY,
    full_name       TEXT NOT NULL,
    driver_type     TEXT,
    employee_status TEXT,
    company         TEXT NOT NULL,
    unit            TEXT,
    synced_at       TEXT NOT NULL
);

-- Writer: fuel (every Datatruck fuel-card line). Card numbers are never stored, only Datatruck's card id.
CREATE TABLE IF NOT EXISTS fuel_lines (
    line_id          INTEGER PRIMARY KEY,
    fueled_at        TEXT NOT NULL,   -- local Central time "YYYY-MM-DD HH:MM"
    transaction_type TEXT NOT NULL,
    product          TEXT NOT NULL,
    gallons          REAL NOT NULL,
    pump_total       REAL NOT NULL,   -- at the posted pump price
    billed           REAL NOT NULL,   -- what EFS billed the company
    fee              REAL NOT NULL,
    billable         INTEGER NOT NULL,
    location         TEXT NOT NULL,
    city             TEXT NOT NULL,
    state            TEXT NOT NULL,
    company          TEXT NOT NULL,
    unit             TEXT,
    truck_ownership  TEXT,
    driver_id        INTEGER,
    driver_name      TEXT,
    driver_type      TEXT,
    card_id          INTEGER,
    synced_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fuel_lines_by_time ON fuel_lines (fueled_at);

-- Writer: fuel (Datatruck fuel cards; of a card's number only the last four digits).
CREATE TABLE IF NOT EXISTS fuel_cards (
    card_id          INTEGER PRIMARY KEY,
    company          TEXT NOT NULL,
    assigned_to      TEXT,
    driver_id        INTEGER,
    unit             TEXT,
    billable         INTEGER NOT NULL,
    deduction_policy TEXT,
    active           INTEGER NOT NULL,
    synced_at        TEXT NOT NULL,
    last4            TEXT
);

-- Writer: sync (Telegram, the groups Bob is in).
CREATE TABLE IF NOT EXISTS tg_groups (
    chat_id   INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    synced_at TEXT NOT NULL
);

-- Writer: orders (Datatruck active orders, with their stops).
CREATE TABLE IF NOT EXISTS dt_orders (
    order_id  INTEGER PRIMARY KEY,
    load_id   TEXT NOT NULL,
    status    TEXT NOT NULL,
    unit      TEXT,
    pickup_at TEXT,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dt_stops (
    stop_id   INTEGER PRIMARY KEY,
    order_id  INTEGER NOT NULL,
    seq       INTEGER NOT NULL,
    kind      TEXT NOT NULL,
    lat       REAL,
    lng       REAL,
    city      TEXT NOT NULL,
    state     TEXT NOT NULL,
    synced_at TEXT NOT NULL
);

-- Writer: prices (newest Love's xlsx).
CREATE TABLE IF NOT EXISTS stores (
    store_no   TEXT PRIMARY KEY,
    city       TEXT NOT NULL,
    state      TEXT NOT NULL,
    lat        REAL NOT NULL,
    lng        REAL NOT NULL,
    retail     REAL NOT NULL,
    net        REAL NOT NULL,
    price_date TEXT NOT NULL,
    synced_at  TEXT NOT NULL
);

-- Writer: prices. Every Love's sheet ever put in data/love's: one row per store per price date.
CREATE TABLE IF NOT EXISTS price_history (
    store_no   TEXT NOT NULL,
    price_date TEXT NOT NULL,
    retail     REAL NOT NULL,
    net        REAL NOT NULL,
    synced_at  TEXT NOT NULL,
    PRIMARY KEY (store_no, price_date)
);
-- Writer: prices. The sheet files already read (a changed file is read again), so each sheet is read once.
CREATE TABLE IF NOT EXISTS price_files (
    path       TEXT PRIMARY KEY,
    size       INTEGER NOT NULL,
    modified   REAL NOT NULL,
    price_date TEXT NOT NULL,
    synced_at  TEXT NOT NULL
);

-- Writer: live (Samsara: every vehicle's latest GPS point and fuel gauge reading).
CREATE TABLE IF NOT EXISTS samsara_live (
    samsara_id TEXT PRIMARY KEY,
    lat        REAL,
    lng        REAL,
    place      TEXT,   -- Samsara's address for the point
    gps_at     TEXT,
    fuel_pct   REAL,
    fuel_at    TEXT,   -- the reading's own time: some gauges stopped reporting long ago
    synced_at  TEXT NOT NULL
);

-- ===== Linked trucks: rebuilt by sync from the copies above. =====
CREATE TABLE IF NOT EXISTS trucks (
    unit         TEXT PRIMARY KEY,
    samsara_id   TEXT NOT NULL UNIQUE,
    vin          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    mpg          REAL,
    auto_chat_id INTEGER,
    chat_note    TEXT,
    synced_at    TEXT NOT NULL
);

-- ===== Helper results: values worked out from the copies. Each helper writes only its own table. =====

-- Writer: habits. Every driver's diesel stops of the last HABIT_DAYS days (purchases at one place grouped) with
-- the Samsara gauge of their truck just before and after; habits are worked out from these rows.
CREATE TABLE IF NOT EXISTS fuel_stops (
    driver_id    INTEGER NOT NULL,
    driver_name  TEXT NOT NULL,
    unit         TEXT,
    at           TEXT NOT NULL,
    gallons      REAL NOT NULL,
    billed       REAL NOT NULL,
    loves        INTEGER NOT NULL,
    state        TEXT NOT NULL,
    gauge_before REAL,
    gauge_after  REAL,
    synced_at    TEXT NOT NULL
);

-- Writer: tanks (gallons bought ÷ Samsara gauge rise over recent fill-ups, never less than what the tank has held).
-- Pilot trucks only.
CREATE TABLE IF NOT EXISTS tank_estimates (
    unit      TEXT PRIMARY KEY,
    tank_gal  REAL NOT NULL,
    fills     INTEGER NOT NULL,   -- fill-ups the estimate is based on
    synced_at TEXT NOT NULL
);

-- Writer: engine fuel factors. How many gallons one unit of each pilot truck's engine meter burns.
CREATE TABLE IF NOT EXISTS burn_factors (
    unit         TEXT PRIMARY KEY,
    gal_per_unit REAL NOT NULL,
    stretches    INTEGER NOT NULL,
    synced_at    TEXT NOT NULL
);

-- ===== Yours. Writer: you (`pilot-add`, `pilot-remove`, `set-tank`, `set-chat`). Nothing else ever touches it. =====
-- The trucks the assistant serves. An empty tank or chat means "use the helper's estimate / the auto-matched group".
CREATE TABLE IF NOT EXISTS pilot_trucks (
    unit     TEXT PRIMARY KEY,
    tank_gal REAL,
    chat_id  INTEGER,
    note     TEXT,
    added_at TEXT NOT NULL
);

-- ===== The app's own records. Kept: never replaced, never dropped. =====
-- Writer: fill lookups. One row per diesel fill outside Love's, written once and kept (not refilled): where the truck was (outside Love's) and the Samsara gauge just before (FillLookup).
CREATE TABLE IF NOT EXISTS fill_lookups (
    line_id      INTEGER PRIMARY KEY,
    lat          REAL,
    lng          REAL,
    gauge_before REAL,
    synced_at    TEXT NOT NULL
);

-- Writer: Love's exits job. One row per Love's store whose own page was read, written once and kept: its highway and
-- exit as the page says them, "I-70 (Exit 208)" (empty when the page names none).
CREATE TABLE IF NOT EXISTS store_exits (
    store_no  TEXT PRIMARY KEY,
    way       TEXT,
    synced_at TEXT NOT NULL
);

-- Writer: fuel recommendations. One row per pilot truck: its latest look, with its road kept so it isn't asked of
-- Google again; `look` is models.TruckWatch as JSON.
CREATE TABLE IF NOT EXISTS truck_watch (
    unit TEXT PRIMARY KEY,
    look TEXT NOT NULL
);

-- Writer: fuel recommendations. One row per pilot truck per load: its stops, the engine's first and last look at it, and
-- the latest road planned. Kept (truck_watch holds only the current look): the Recommend tab's past trips.
CREATE TABLE IF NOT EXISTS trips (
    unit       TEXT NOT NULL,
    order_id   INTEGER NOT NULL,
    load_id    TEXT,
    stops      TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT NOT NULL,
    line       TEXT,
    PRIMARY KEY (unit, order_id)
);

-- Writer: fuel recommendations. Everything a driver would have been told, and what became of it. Kept.
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    unit         TEXT NOT NULL,
    driver       TEXT,
    order_id     INTEGER NOT NULL,
    load_id      TEXT NOT NULL,
    made_at      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    store_no     TEXT,
    station      TEXT,
    miles_ahead  REAL,
    gauge_pct    REAL NOT NULL,
    arrive_pct   REAL,
    worst_pct    REAL,
    gallons      REAL,
    then_station TEXT,
    reason       TEXT,
    net          REAL,
    retail       REAL,
    price_date   TEXT,
    forecast_mpg REAL NOT NULL,
    cautious_mpg REAL NOT NULL,
    usual_pct    REAL NOT NULL,
    text         TEXT NOT NULL,
    status       TEXT NOT NULL,
    settled_at   TEXT,
    sent_at      TEXT,
    lat          REAL,
    lng          REAL
);

-- Writer: statements job. One row per EFS statement read from data/efs (a changed file is read again): page 1's
-- figures; `summary` is its Transaction Summary as JSON [[EFS's name, dollars], ...].
CREATE TABLE IF NOT EXISTS efs_statements (
    statement_no  TEXT PRIMARY KEY,
    account       TEXT NOT NULL,
    statement_day TEXT NOT NULL,
    charges       REAL NOT NULL,
    summary       TEXT NOT NULL,
    path          TEXT NOT NULL,
    size          INTEGER NOT NULL,
    modified      REAL NOT NULL,
    synced_at     TEXT NOT NULL
);
-- Writer: statements job. Every line of those statements, in their order.
CREATE TABLE IF NOT EXISTS efs_lines (
    statement_no TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    tn           TEXT NOT NULL,
    day          TEXT NOT NULL,
    unit         TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    description  TEXT NOT NULL,
    quantity     REAL NOT NULL,
    amount       REAL NOT NULL,
    fee          REAL NOT NULL,
    synced_at    TEXT NOT NULL,
    PRIMARY KEY (statement_no, seq)
);

-- Writer: fill evidence job. One row per diesel fill on a statement (its Datatruck line): the gauge's biggest rise near
-- it and where the truck was then, from Samsara. Looked up once and kept.
CREATE TABLE IF NOT EXISTS fill_evidence (
    line_id    INTEGER PRIMARY KEY,
    gauge_from REAL,
    gauge_to   REAL,
    risen_at   TEXT,
    lat        REAL,
    lng        REAL,
    place      TEXT,
    synced_at  TEXT NOT NULL
);
-- Writer: fill evidence job. Per statement, every Samsara vehicle's engine fuel used, miles and gauge at the start and
-- end of its days. Looked up once per statement and kept.
CREATE TABLE IF NOT EXISTS statement_burn (
    statement_no TEXT NOT NULL,
    samsara_id   TEXT NOT NULL,
    burned_gal   REAL NOT NULL,
    miles        REAL NOT NULL,
    gauge_start  REAL,
    gauge_end    REAL,
    synced_at    TEXT NOT NULL,
    PRIMARY KEY (statement_no, samsara_id)
);

-- Writer: the scheduler. When each automatic refresh last ran and whether it crashed.
CREATE TABLE IF NOT EXISTS job_runs (
    job         TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    error       TEXT
);

-- Writers: every source refresh (base/fleet/copies), and the heartbeat for Google Maps, which it asks itself (base/runner/heartbeat).
-- One row per source: when it was last tried, last worked, and why the last try failed (NULL when it worked). A failed
-- refresh keeps the old copy, so this is where a failure shows.
CREATE TABLE IF NOT EXISTS source_health (
    name        TEXT PRIMARY KEY,
    last_try_at TEXT NOT NULL,
    last_ok_at  TEXT,
    error       TEXT
);

-- Writer: the heartbeat (base/runner/heartbeat). The problems found and not yet fixed, one per component, and whether the
-- alert about each went out: each is told once when it starts and once when it ends.
CREATE TABLE IF NOT EXISTS health_alerts (
    component TEXT PRIMARY KEY,
    text      TEXT NOT NULL,
    since     TEXT,
    told      INTEGER NOT NULL DEFAULT 0
);

-- Writer: the card agent (features/cards/agent). One row per message that woke it: the truck of that group, what it decided,
-- the tools it used, the card it opened, and the run's whole record (JSON: what Claude read, what it thought, each tool
-- with its answer). Kept: the audit of every card it changed.
CREATE TABLE IF NOT EXISTS agent_runs (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    unit        TEXT,
    woke_at     TEXT NOT NULL,
    text        TEXT,
    outcome     TEXT,
    steps       TEXT,
    opened_card TEXT,
    opened_at   TEXT,
    error       TEXT,
    record      TEXT,
    PRIMARY KEY (chat_id, message_id)
);

-- Writer: the card agent. One row, its pulse, for the dashboard: when it last said it is running, whether eManager is
-- logged in and since when, and the last tag it heard with what it did about it.
CREATE TABLE IF NOT EXISTS agent_pulse (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    beat_at        TEXT,
    emanager       INTEGER,
    emanager_since TEXT,
    tag_at         TEXT,
    tag_note       TEXT
);
"""

# Views hold no data, so they are recreated on every connect and always match the code and config.
MPG_LOW, MPG_HIGH = config.MPG_RANGE
VIEWS = f"""
DROP VIEW IF EXISTS holes;
DROP VIEW IF EXISTS fleet;
DROP VIEW IF EXISTS active_vehicles;

-- Samsara vehicles that reported GPS recently; parked-for-good and retired trucks drop out.
CREATE VIEW active_vehicles AS
SELECT samsara_id FROM samsara_vehicles
WHERE last_gps_at >= datetime('now', '-{config.ACTIVE_HOURS} hours');

-- One row per truck with everything known about it: synced facts, latest fuel and position, and the values that
-- have both an automatic and a manual source (tank, chat). The one place they meet: yours always win.
CREATE VIEW fleet AS
SELECT t.unit, t.samsara_id, t.vin, t.name,
       (SELECT group_concat(d.full_name, ' & ') FROM dt_drivers d
        WHERE d.unit = t.unit AND d.employee_status = 'active') AS driver,
       t.mpg,
       l.fuel_pct, l.fuel_at, l.lat, l.lng, l.place, l.gps_at,
       COALESCE(p.tank_gal, e.tank_gal) AS tank_gal,
       CASE WHEN p.tank_gal IS NOT NULL THEN 'manual'
            WHEN e.tank_gal IS NOT NULL THEN 'auto' END AS tank_source,
       e.fills AS tank_fills,
       COALESCE(p.chat_id, t.auto_chat_id) AS chat_id,
       CASE WHEN p.chat_id IS NOT NULL THEN 'manual'
            WHEN t.auto_chat_id IS NOT NULL THEN 'auto' END AS chat_source,
       t.chat_note,
       p.unit IS NOT NULL AS pilot
FROM trucks t
LEFT JOIN pilot_trucks p ON p.unit = t.unit
LEFT JOIN tank_estimates e ON e.unit = t.unit
LEFT JOIN samsara_live l ON l.samsara_id = t.samsara_id;

-- Every place where the data doesn't link up, one row per problem: (hole, item, detail).
CREATE VIEW holes AS
SELECT 'Samsara: active vehicle without Datatruck truck' AS hole, name AS item,
       CASE vin WHEN '' THEN 'no VIN in Samsara' ELSE 'VIN ' || vin END AS detail
FROM samsara_vehicles
WHERE samsara_id IN (SELECT samsara_id FROM active_vehicles)
  AND samsara_id NOT IN (SELECT samsara_id FROM trucks)
UNION ALL
SELECT 'Datatruck: truck without Samsara vehicle', unit,
       CASE vin WHEN '' THEN 'no VIN in Datatruck' ELSE 'VIN ' || vin END
FROM dt_trucks d WHERE NOT EXISTS (SELECT 1 FROM trucks t WHERE t.unit = d.unit AND t.vin = d.vin)
UNION ALL
SELECT 'Samsara: several records share a VIN (the latest-GPS one is used; clean up the others)', vin,
       COUNT(*) || ' records: ' || group_concat(name, ' | ')
FROM samsara_vehicles WHERE vin <> '' GROUP BY vin HAVING COUNT(*) > 1
UNION ALL
SELECT 'Datatruck: VIN on several trucks', vin, COUNT(*) || ' trucks'
FROM dt_trucks WHERE vin <> '' GROUP BY vin HAVING COUNT(*) > 1
UNION ALL
SELECT 'Datatruck: unit number on several trucks', unit, COUNT(*) || ' trucks'
FROM dt_trucks GROUP BY unit HAVING COUNT(*) > 1
UNION ALL
SELECT 'Telegram: active truck without group', unit, chat_note
FROM fleet WHERE chat_id IS NULL AND samsara_id IN (SELECT samsara_id FROM active_vehicles)
UNION ALL
SELECT 'Datatruck: no driver on an active truck whose Telegram group names one (assign them in Datatruck)', unit, chat_note
FROM fleet WHERE chat_id IS NOT NULL AND chat_source = 'auto' AND chat_note IS NOT NULL
  AND samsara_id IN (SELECT samsara_id FROM active_vehicles)
UNION ALL
SELECT 'Telegram: group without truck', title, chat_id
FROM tg_groups WHERE chat_id NOT IN (SELECT chat_id FROM fleet WHERE chat_id IS NOT NULL)
UNION ALL
SELECT 'Orders: active order without linked truck', load_id, COALESCE('unit ' || unit, 'no truck on the trip')
FROM dt_orders WHERE unit IS NULL OR unit NOT IN (SELECT unit FROM trucks)
UNION ALL
SELECT 'Orders: truck with several in-transit orders', unit, COUNT(*) || ' orders: ' || group_concat(load_id, ', ')
FROM dt_orders WHERE status = 'in_transit' AND unit IS NOT NULL GROUP BY unit HAVING COUNT(*) > 1
UNION ALL
SELECT 'Orders: order without stops', load_id, status
FROM dt_orders WHERE order_id NOT IN (SELECT order_id FROM dt_stops)
UNION ALL
SELECT 'Orders: stop without coordinates', o.load_id, 'stop ' || s.seq || ' ' || s.city || ', ' || s.state
FROM dt_stops s JOIN dt_orders o ON o.order_id = s.order_id WHERE s.lat IS NULL OR s.lng IS NULL
UNION ALL
SELECT 'Samsara: active truck with missing or odd MPG', unit, COALESCE(ROUND(mpg, 1), 'no MPG')
FROM fleet WHERE (mpg IS NULL OR mpg NOT BETWEEN {MPG_LOW} AND {MPG_HIGH})
  AND samsara_id IN (SELECT samsara_id FROM active_vehicles)
UNION ALL
SELECT 'Pilot: truck no longer linked (Samsara <-> Datatruck)', unit, note
FROM pilot_trucks WHERE unit NOT IN (SELECT unit FROM trucks)
UNION ALL
SELECT 'Pilot: no tank size (set-tank, or the tank helper needs more fill-ups)', unit, name
FROM fleet WHERE pilot AND tank_gal IS NULL
UNION ALL
SELECT 'Pilot: no Telegram group (set-chat)', unit, chat_note
FROM fleet WHERE pilot AND chat_id IS NULL
UNION ALL
SELECT 'Pilot: no Samsara fuel reading in the last {config.ACTIVE_HOURS} h', unit, COALESCE('last ' || fuel_at, 'never')
FROM fleet WHERE pilot AND (fuel_at IS NULL OR fuel_at < datetime('now', '-{config.ACTIVE_HOURS} hours'));
"""

# Tables filled by refreshes: listed by the `status` command, and dropped for refilling when SCHEMA_VERSION changes.
# Your pilot list (pilot_trucks), fill_lookups and job_runs are not in this list, so they are never dropped.
SYNCED_TABLES = ["samsara_vehicles", "samsara_live", "dt_trucks", "dt_drivers", "tg_groups", "dt_orders", "dt_stops",
                 "stores", "price_history", "price_files", "fuel_lines", "fuel_cards", "trucks",
                 "tank_estimates", "fuel_stops", "burn_factors", "efs_statements", "efs_lines"]
