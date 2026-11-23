# SQLite storage. Every table has exactly one writer; source copies are replaced whole on each refresh.
# The app reads trucks through the `fleet` view (one row per truck); data gaps are collected in the `holes` view.
import json
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime, timezone

from base import config
from base.models import (BurnFactor, DatatruckDriver, DatatruckTruck, EfsLine, EfsStatement, FillEvidence, FillLookup,
                         FleetTruck, FuelCard, FuelLine, FuelStop, Order, Problem, Recommendation, Region,
                         SamsaraLive, SamsaraVehicle, SourceHealth, Stop, Store, SyncedTruck, TankEstimate, TelegramGroup,
                         Truck, TruckBurn, Trip, TruckWatch, UsualLevel)

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

-- Writer: fuel (Datatruck fuel cards, without their numbers).
CREATE TABLE IF NOT EXISTS fuel_cards (
    card_id          INTEGER PRIMARY KEY,
    company          TEXT NOT NULL,
    assigned_to      TEXT,
    driver_id        INTEGER,
    unit             TEXT,
    billable         INTEGER NOT NULL,
    deduction_policy TEXT,
    active           INTEGER NOT NULL,
    synced_at        TEXT NOT NULL
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

-- Writer: the card agent (features/cards/job). One row per message that woke it: the truck of that group, what it decided,
-- the tools it used, and the card it opened. Kept: the audit of every card it changed, and its cooldown.
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
    PRIMARY KEY (chat_id, message_id)
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


_schema_lock = threading.Lock()
_schema_ready: set[str] = set()  # database files this process has already set up


# Opens the database (setting it up on first use) and runs the block as one transaction: all or nothing.
@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    try:
        with conn:  # commits on success, rolls back on any error
            yield conn
    finally:
        conn.close()


# Makes sure tables and views exist and match this code, once per database file per process. The lock keeps this
# process's threads from doing it twice; BEGIN IMMEDIATE makes each step atomic against other programs on the file.
def _ensure_schema(conn: sqlite3.Connection) -> None:
    with _schema_lock:
        if str(config.DB_PATH) in _schema_ready:
            return
        conn.execute("PRAGMA journal_mode=WAL")  # the dashboard keeps reading while a refresh writes
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            _rebuild(conn)
        conn.executescript("BEGIN IMMEDIATE;" + TABLES + VIEWS + "COMMIT;")
        _add_column(conn, "recommendations", "sent_at", "TEXT")
        _add_column(conn, "recommendations", "lat", "REAL")
        _add_column(conn, "recommendations", "lng", "REAL")
        _schema_ready.add(str(config.DB_PATH))


# Adds a column a kept table got later (kept tables are never dropped and rebuilt, so CREATE TABLE alone won't add it).
def _add_column(conn: sqlite3.Connection, table: str, column: str, kind: str) -> None:
    if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


# Drops every refreshed table (its job refills it) and stamps the new schema version. Manual settings stay.
def _rebuild(conn: sqlite3.Connection) -> None:
    conn.executescript("BEGIN IMMEDIATE; DROP VIEW IF EXISTS holes; DROP VIEW IF EXISTS fleet; DROP VIEW IF EXISTS active_vehicles;"
                       + "".join(f"DROP TABLE IF EXISTS {t};" for t in SYNCED_TABLES)
                       + f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")


# Formats a datetime as stored UTC text, "2026-10-18 12:00:00+00:00", which compares correctly in SQL.
def _ts(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(sep=" ", timespec="seconds")


# Reads stored UTC text back into a datetime.
def _dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


# Returns the current time as stored UTC text.
def now() -> str:
    return _ts(datetime.now(timezone.utc))


# Claims a message that woke the card agent, so each is handled once (a restart or a repeat event finds it taken).
# True when it was new.
def claim_agent_run(conn: sqlite3.Connection, chat_id: int, message_id: int, unit: str | None, at: datetime,
                    text: str) -> bool:
    return conn.execute("INSERT OR IGNORE INTO agent_runs (chat_id, message_id, unit, woke_at, text) VALUES (?, ?, ?, ?, ?)",
                        (chat_id, message_id, unit, _ts(at), text)).rowcount == 1


# Records how a card agent run ended: its outcome, the tools it used (JSON), the card it opened and when, or its error.
def finish_agent_run(conn: sqlite3.Connection, chat_id: int, message_id: int, outcome: str, steps: str,
                     opened_card: str | None, opened_at: datetime | None, error: str | None) -> None:
    conn.execute("UPDATE agent_runs SET outcome = ?, steps = ?, opened_card = ?, opened_at = ?, error = ? "
                 "WHERE chat_id = ? AND message_id = ?",
                 (outcome, steps, opened_card, _ts(opened_at) if opened_at else None, error, chat_id, message_id))


# True when the card agent took a request in this chat since a moment (a bare tag right after joins that one).
def agent_run_since(conn: sqlite3.Connection, chat_id: int, since: datetime) -> bool:
    return conn.execute("SELECT 1 FROM agent_runs WHERE chat_id = ? AND woke_at >= ? LIMIT 1",
                        (chat_id, _ts(since))).fetchone() is not None


# Records a card the card agent opened, the moment eManager confirmed it.
def record_agent_open(conn: sqlite3.Connection, chat_id: int, message_id: int, card_id: str, at: datetime) -> None:
    conn.execute("UPDATE agent_runs SET opened_card = ?, opened_at = ? WHERE chat_id = ? AND message_id = ?",
                 (card_id, _ts(at), chat_id, message_id))


# When the card agent last opened a card (eManager's card id); None when it never did.
def agent_last_opened(conn: sqlite3.Connection, card_id: str) -> datetime | None:
    row = conn.execute("SELECT MAX(opened_at) FROM agent_runs WHERE opened_card = ?", (card_id,)).fetchone()
    return _dt(row[0])


# Turns a model into a table row: datetimes become stored text; `skip` drops a field kept in another table.
def _row(obj, skip: str | None = None) -> dict:
    return {k: _ts(v) if isinstance(v, datetime) else v for k, v in asdict(obj).items() if k != skip}


# Replaces a whole table with new rows, all stamped with the same refresh time.
def _replace(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    conn.execute(f"DELETE FROM {table}")
    _insert(conn, table, rows)


# Inserts rows (dicts with the same keys), all stamped with the same refresh time.
def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    stamp = now()
    columns = [*rows[0], "synced_at"]
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})",
        [row | {"synced_at": stamp} for row in rows],
    )


# Replaces the Samsara copy.
def replace_samsara_vehicles(conn: sqlite3.Connection, vehicles: list[SamsaraVehicle]) -> None:
    _replace(conn, "samsara_vehicles", [_row(v) for v in vehicles])


# Replaces the Samsara live copy (every vehicle's latest GPS point and fuel level).
def replace_samsara_live(conn: sqlite3.Connection, rows: list[SamsaraLive]) -> None:
    _replace(conn, "samsara_live", [_row(r) for r in rows])


# Replaces every driver's fuel stops.
def replace_fuel_stops(conn: sqlite3.Connection, stops: list[FuelStop]) -> None:
    _replace(conn, "fuel_stops", [_row(s) for s in stops])


# Returns every driver's fuel stops, oldest first.
def fuel_stops(conn: sqlite3.Connection) -> list[FuelStop]:
    rows = conn.execute("SELECT driver_id, driver_name, unit, at, gallons, billed, loves, state, gauge_before, "
                        "gauge_after FROM fuel_stops ORDER BY at")
    return [FuelStop(**{**row, "at": _dt(row["at"]), "loves": bool(row["loves"])}) for row in rows]


# Replaces the tank helper's estimates.
def replace_tank_estimates(conn: sqlite3.Connection, estimates: list[TankEstimate]) -> None:
    _replace(conn, "tank_estimates", [_row(e) for e in estimates])


# Replaces the Datatruck trucks copy.
def replace_dt_trucks(conn: sqlite3.Connection, trucks: list[DatatruckTruck]) -> None:
    _replace(conn, "dt_trucks", [_row(t) for t in trucks])


# Replaces the Telegram groups copy.
def replace_tg_groups(conn: sqlite3.Connection, groups: list[TelegramGroup]) -> None:
    _replace(conn, "tg_groups", [_row(g) for g in groups])


# Replaces all active orders and their stops together.
def replace_orders(conn: sqlite3.Connection, orders: list[Order]) -> None:
    _replace(conn, "dt_orders", [_row(o, skip="stops") for o in orders])
    _replace(conn, "dt_stops", [_row(s) for o in orders for s in o.stops])


# Replaces the Love's stores and prices.
def replace_stores(conn: sqlite3.Connection, stores: list[Store]) -> None:
    # `name` is only for stations that aren't Love's; `way` is kept in its own table (store_exits)
    _replace(conn, "stores", [{k: v for k, v in _row(s, skip="name").items() if k != "way"} for s in stores])


# Keeps a Love's store's highway and exit as its own page says them (None: the page names none).
def save_store_exit(conn: sqlite3.Connection, store_no: str, way: str | None) -> None:
    conn.execute("INSERT OR REPLACE INTO store_exits (store_no, way, synced_at) VALUES (?, ?, ?)", (store_no, way, now()))


# The Love's stores whose own page hasn't been read for its exit yet, by store number.
def stores_without_exit(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT store_no FROM stores WHERE store_no NOT IN (SELECT store_no FROM store_exits) ORDER BY store_no")]


# Adds one price sheet to the price history (a store's price for a day it already has is replaced) and records the
# file as read.
def add_price_sheet(conn: sqlite3.Connection, path: str, size: int, modified: float, stores: list[Store]) -> None:
    stamp = now()
    conn.executemany("INSERT OR REPLACE INTO price_history (store_no, price_date, retail, net, synced_at) "
                     "VALUES (?, ?, ?, ?, ?)", [(s.store_no, s.price_date, s.retail, s.net, stamp) for s in stores])
    conn.execute("INSERT OR REPLACE INTO price_files (path, size, modified, price_date, synced_at) VALUES (?, ?, ?, ?, ?)",
                 (path, size, modified, max(s.price_date for s in stores), stamp))


# Returns the price sheet files already read, as {path: (size, modified)}.
def price_files(conn: sqlite3.Connection) -> dict[str, tuple[int, float]]:
    return {row["path"]: (row["size"], row["modified"]) for row in conn.execute("SELECT path, size, modified FROM price_files")}


# Returns the path of the sheet with the newest price date (the most recently changed file among equals), or None.
def newest_price_file(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT path FROM price_files ORDER BY price_date DESC, modified DESC LIMIT 1").fetchone()
    return row["path"] if row else None


# Adds one EFS statement with its lines (a statement read before is replaced: same number, new file) and records
# the file it came from as read.
def add_statement(conn: sqlite3.Connection, path: str, size: int, modified: float, statement: EfsStatement,
                  lines: list[EfsLine]) -> None:
    conn.execute("DELETE FROM efs_lines WHERE statement_no = ?", (statement.statement_no,))
    conn.execute("DELETE FROM efs_statements WHERE statement_no = ? OR path = ?", (statement.statement_no, path))
    row = _row(statement) | {"summary": json.dumps(statement.summary), "path": path, "size": size, "modified": modified}
    _insert(conn, "efs_statements", [row])
    _insert(conn, "efs_lines", [_row(line) for line in lines])


# Returns the statement files already read, as {path: (size, modified)}.
def statement_files(conn: sqlite3.Connection) -> dict[str, tuple[int, float]]:
    return {row["path"]: (row["size"], row["modified"]) for row in conn.execute("SELECT path, size, modified FROM efs_statements")}


# Returns every EFS statement read, newest first (by statement date, then account).
def statements(conn: sqlite3.Connection) -> list[EfsStatement]:
    rows = conn.execute("SELECT statement_no, account, statement_day, charges, summary FROM efs_statements "
                        "ORDER BY statement_day DESC, account")
    return [_statement(row) for row in rows]


# Returns one statement and its lines in their order; None when it was never read.
def statement(conn: sqlite3.Connection, statement_no: str) -> tuple[EfsStatement, list[EfsLine]] | None:
    row = conn.execute("SELECT statement_no, account, statement_day, charges, summary FROM efs_statements "
                       "WHERE statement_no = ?", (statement_no,)).fetchone()
    if row is None:
        return None
    lines = conn.execute("SELECT statement_no, seq, tn, day, unit, city, state, description, quantity, amount, fee "
                         "FROM efs_lines WHERE statement_no = ? ORDER BY seq", (statement_no,))
    return _statement(row), [EfsLine(**line) for line in lines]


# Keeps what Samsara showed around these fills.
def add_fill_evidence(conn: sqlite3.Connection, found: list[FillEvidence]) -> None:
    conn.executemany("DELETE FROM fill_evidence WHERE line_id = ?", [(e.line_id,) for e in found])
    _insert(conn, "fill_evidence", [_row(e) for e in found])


# Returns the evidence kept for these Datatruck lines, as {line id: FillEvidence}; a line not looked up isn't in it.
def fill_evidence(conn: sqlite3.Connection, line_ids: list[int]) -> dict[int, FillEvidence]:
    marks = ",".join("?" * len(line_ids))
    rows = conn.execute(f"SELECT line_id, gauge_from, gauge_to, risen_at, lat, lng, place FROM fill_evidence "
                        f"WHERE line_id IN ({marks})", line_ids) if line_ids else []
    return {row["line_id"]: FillEvidence(**{**row, "risen_at": _dt(row["risen_at"])}) for row in rows}


# Keeps one statement's fuel used per Samsara vehicle (a statement looked up again is replaced).
def add_statement_burn(conn: sqlite3.Connection, statement_no: str, burns: list[TruckBurn]) -> None:
    conn.execute("DELETE FROM statement_burn WHERE statement_no = ?", (statement_no,))
    _insert(conn, "statement_burn", [_row(b) for b in burns])


# Returns one statement's fuel used per Samsara vehicle, as {samsara id: TruckBurn}; empty when not looked up yet.
def statement_burn(conn: sqlite3.Connection, statement_no: str) -> dict[str, TruckBurn]:
    rows = conn.execute("SELECT statement_no, samsara_id, burned_gal, miles, gauge_start, gauge_end FROM statement_burn "
                        "WHERE statement_no = ?", (statement_no,))
    return {row["samsara_id"]: TruckBurn(**row) for row in rows}


# A stored statement row back as an EfsStatement (its summary from JSON).
def _statement(row: sqlite3.Row) -> EfsStatement:
    return EfsStatement(**{**row, "summary": tuple((name, amount) for name, amount in json.loads(row["summary"]))})


# Returns each price sheet day's Love's discount (pump price minus our price) averaged over every store, from
# `since_day` on, as {day: dollars per gallon}.
def network_discounts(conn: sqlite3.Connection, since_day: str) -> dict[str, float]:
    rows = conn.execute("SELECT price_date, AVG(retail - net) AS discount FROM price_history WHERE price_date >= ? "
                        "GROUP BY price_date", (since_day,))
    return {row["price_date"]: row["discount"] for row in rows}


# Returns every price sheet from `since_day` on as {day: {store_no: our price per gallon}}.
def price_sheets(conn: sqlite3.Connection, since_day: str) -> dict[str, dict[str, float]]:
    sheets = defaultdict(dict)
    for row in conn.execute("SELECT store_no, price_date, net FROM price_history WHERE price_date >= ?", (since_day,)):
        sheets[row["price_date"]][row["store_no"]] = row["net"]
    return dict(sheets)


# Adds newly looked-up fills.
def add_fill_lookups(conn: sqlite3.Connection, fills: list[FillLookup]) -> None:
    _insert(conn, "fill_lookups", [_row(f) for f in fills])


# Returns every looked-up fill by its fuel line id.
def fill_lookups(conn: sqlite3.Connection) -> dict[int, FillLookup]:
    rows = conn.execute("SELECT line_id, lat, lng, gauge_before FROM fill_lookups")
    return {row["line_id"]: FillLookup(**row) for row in rows}


# Replaces the Datatruck drivers copy.
def replace_dt_drivers(conn: sqlite3.Connection, drivers: list[DatatruckDriver]) -> None:
    _replace(conn, "dt_drivers", [_row(d) for d in drivers])


# Replaces the fuel lines copy.
def replace_fuel_lines(conn: sqlite3.Connection, lines: list[FuelLine]) -> None:
    _replace(conn, "fuel_lines", [_row(f) for f in lines])


# Replaces only the fuel lines fueled on or after a local day; older lines stay as they are.
def replace_fuel_lines_since(conn: sqlite3.Connection, since_day: str, lines: list[FuelLine]) -> None:
    conn.execute("DELETE FROM fuel_lines WHERE fueled_at >= ?", (since_day,))
    _insert(conn, "fuel_lines", [_row(f) for f in lines])


# Replaces the engine fuel factors.
def replace_burn_factors(conn: sqlite3.Connection, factors: list[BurnFactor]) -> None:
    _replace(conn, "burn_factors", [_row(f) for f in factors])


# Each pilot truck's engine fuel factor, by unit.
def burn_factors(conn: sqlite3.Connection) -> dict[str, float]:
    return {r["unit"]: r["gal_per_unit"] for r in conn.execute("SELECT unit, gal_per_unit FROM burn_factors")}


# Saves a pilot truck's latest look, replacing the one before.
def save_truck_watch(conn: sqlite3.Connection, watch: TruckWatch) -> None:
    conn.execute("INSERT OR REPLACE INTO truck_watch (unit, look) VALUES (?, ?)",
                 (watch.unit, json.dumps(asdict(watch), default=lambda v: v.isoformat())))


# A pilot truck's latest look; None before its first.
def truck_watch(conn: sqlite3.Connection, unit: str) -> TruckWatch | None:
    row = conn.execute("SELECT look FROM truck_watch WHERE unit = ?", (unit,)).fetchone()
    return _watch(row["look"]) if row else None


# A saved look back as a TruckWatch.
def _watch(look: str) -> TruckWatch:
    d = json.loads(look)
    return TruckWatch(**_known(TruckWatch, {**d, "at": _dt(d["at"]), "road_made_at": _dt(d["road_made_at"]),
                         "line": [tuple(p) for p in d["line"]] if d["line"] else None,
                         "regions": tuple(Region(**r) for r in d["regions"]),
                         "usual": UsualLevel(**d["usual"]) if d.get("usual") else None,
                         "road_stops": tuple(tuple(p) for p in d.get("road_stops") or ()),
                         "fueled_at": _dt(d.get("fueled_at"))}))


# Records a look at a truck's load: a trip starts on its first look and each look moves its end; a road made anew
# (`line`; None when the road was kept) replaces the one kept.
def save_trip(conn: sqlite3.Connection, trip: Trip) -> None:
    conn.execute("INSERT INTO trips (unit, order_id, load_id, stops, started_at, ended_at, line) VALUES (?, ?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT (unit, order_id) DO UPDATE SET load_id = excluded.load_id, stops = excluded.stops, "
                 "ended_at = excluded.ended_at, line = COALESCE(excluded.line, trips.line)",
                 (trip.unit, trip.order_id, trip.load_id, json.dumps(trip.stops), _ts(trip.started_at), _ts(trip.ended_at),
                  json.dumps(trip.line) if trip.line else None))


# A truck's trips that ended since a UTC day ("YYYY-MM-DD"), newest first.
def trips(conn: sqlite3.Connection, unit: str, since_day: str) -> list[Trip]:
    return [Trip(r["unit"], r["order_id"], r["load_id"], tuple(tuple(s) for s in json.loads(r["stops"])), _dt(r["started_at"]),
                 _dt(r["ended_at"]), [tuple(p) for p in json.loads(r["line"])] if r["line"] else None)
            for r in conn.execute("SELECT * FROM trips WHERE unit = ? AND ended_at >= ? ORDER BY started_at DESC", (unit, since_day))]


# Every pilot truck's latest look.
def truck_watches(conn: sqlite3.Connection) -> list[TruckWatch]:
    return [_watch(r["look"]) for r in conn.execute("SELECT look FROM truck_watch ORDER BY unit")]


# Records something a driver would be told, and returns its id.
def add_recommendation(conn: sqlite3.Connection, rec: Recommendation) -> int:
    row = _row(rec, skip="rec_id")
    return conn.execute(f"INSERT INTO recommendations ({', '.join(row)}) VALUES ({', '.join(':' + c for c in row)})", row).lastrowid


# Marks a recommendation as sent to the driver's own group.
def mark_sent(conn: sqlite3.Connection, rec_id: int, at: datetime) -> None:
    conn.execute("UPDATE recommendations SET sent_at = ? WHERE rec_id = ?", (_ts(at), rec_id))


# The recommendation of a truck still waiting to see what becomes of it; None when there is none.
def open_recommendation(conn: sqlite3.Connection, unit: str) -> Recommendation | None:
    row = conn.execute("SELECT * FROM recommendations WHERE unit = ? AND status = 'open' ORDER BY rec_id DESC LIMIT 1",
                       (unit,)).fetchone()
    return _recommendation(row) if row else None


# How many fuel stops told to a truck after a moment ended driven past.
def passed_stops(conn: sqlite3.Connection, unit: str, since: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM recommendations WHERE unit = ? AND kind = 'stop' AND status = 'passed' "
                        "AND made_at > ?", (unit, _ts(since))).fetchone()[0]


# Closes a recommendation with what became of it.
def settle_recommendation(conn: sqlite3.Connection, rec_id: int, status: str, at: datetime) -> None:
    conn.execute("UPDATE recommendations SET status = ?, settled_at = ? WHERE rec_id = ?", (status, _ts(at), rec_id))


# The recommendations made since a UTC day ("YYYY-MM-DD"), newest first.
def recommendations(conn: sqlite3.Connection, since_day: str) -> list[Recommendation]:
    return [_recommendation(r) for r in conn.execute(
        "SELECT * FROM recommendations WHERE made_at >= ? ORDER BY rec_id DESC", (since_day,))]


# A `recommendations` row as a Recommendation: stored times become datetimes.
def _recommendation(row: sqlite3.Row) -> Recommendation:
    return Recommendation(**_known(Recommendation, {**row, "made_at": _dt(row["made_at"]), "settled_at": _dt(row["settled_at"]),
                                                    "sent_at": _dt(row["sent_at"])}))


# The stored values a record type still has: a field dropped from the code since doesn't stop old rows from loading
# (otherwise every look of the engine would fail on its saved look, quietly).
def _known(cls, values: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in values.items() if k in names}


# Records that a scheduled job started (error None) or finished (with its error, if it crashed).
def record_job(conn: sqlite3.Connection, job: str, started_at: str, finished_at: str | None, error: str | None) -> None:
    conn.execute("INSERT INTO job_runs (job, started_at, finished_at, error) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT (job) DO UPDATE SET started_at = excluded.started_at, finished_at = excluded.finished_at, "
                 "error = excluded.error", (job, started_at, finished_at, error))


# Returns the scheduled jobs' last runs as {job: row}.
def job_runs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["job"]: row for row in conn.execute("SELECT * FROM job_runs")}


# Records one try at refreshing a source: when, and the error when it failed (None: it worked, so it worked then too).
def record_source(conn: sqlite3.Connection, name: str, at: datetime, error: str | None) -> None:
    conn.execute("INSERT INTO source_health (name, last_try_at, last_ok_at, error) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT (name) DO UPDATE SET last_try_at = excluded.last_try_at, error = excluded.error, "
                 "last_ok_at = COALESCE(excluded.last_ok_at, source_health.last_ok_at)",
                 (name, _ts(at), None if error else _ts(at), error))


# How each source's last refresh went.
def source_health(conn: sqlite3.Connection) -> list[SourceHealth]:
    return [SourceHealth(r["name"], _dt(r["last_try_at"]), _dt(r["last_ok_at"]), r["error"])
            for r in conn.execute("SELECT * FROM source_health ORDER BY name")]


# The problems the heartbeat found and hasn't seen fixed yet, by component.
def health_alerts(conn: sqlite3.Connection) -> dict[str, Problem]:
    return {r["component"]: Problem(r["component"], r["text"], _dt(r["since"]), bool(r["told"]))
            for r in conn.execute("SELECT * FROM health_alerts ORDER BY component")}


# Keeps a problem found (it replaces the one kept for that component).
def set_alert(conn: sqlite3.Connection, problem: Problem) -> None:
    conn.execute("INSERT OR REPLACE INTO health_alerts (component, text, since, told) VALUES (?, ?, ?, ?)",
                 (problem.component, problem.text, _ts(problem.since) if problem.since else None, int(problem.told)))


# Forgets an alerted problem once it is fixed.
def clear_alert(conn: sqlite3.Connection, component: str) -> None:
    conn.execute("DELETE FROM health_alerts WHERE component = ?", (component,))


# The newest moments the data shows: Samsara's newest GPS point (UTC), the newest fuel purchase (Central, as Datatruck
# writes it, "YYYY-MM-DD HH:MM") and the newest Love's price sheet's day. None where there is nothing yet.
def newest_data(conn: sqlite3.Connection) -> tuple[datetime | None, str | None, str | None]:
    gps = conn.execute("SELECT MAX(gps_at) FROM samsara_live").fetchone()[0]
    fuel = conn.execute("SELECT MAX(fueled_at) FROM fuel_lines").fetchone()[0]
    sheet = conn.execute("SELECT MAX(price_date) FROM price_files").fetchone()[0]
    return _dt(gps), fuel, sheet


# Replaces the fuel cards copy.
def replace_fuel_cards(conn: sqlite3.Connection, cards: list[FuelCard]) -> None:
    _replace(conn, "fuel_cards", [_row(c) for c in cards])


# Replaces all linked trucks at once, so a truck gone from the sources also disappears here.
def replace_trucks(conn: sqlite3.Connection, trucks: list[SyncedTruck]) -> None:
    _replace(conn, "trucks", [_row(t) for t in trucks])


# Returns the Samsara copy.
def samsara_vehicles(conn: sqlite3.Connection) -> list[SamsaraVehicle]:
    rows = conn.execute("SELECT samsara_id, name, vin, mpg, last_gps_at FROM samsara_vehicles")
    return [SamsaraVehicle(**{**row, "last_gps_at": _dt(row["last_gps_at"])}) for row in rows]


# Returns the Datatruck trucks copy.
def dt_trucks(conn: sqlite3.Connection) -> list[DatatruckTruck]:
    return [DatatruckTruck(**row) for row in conn.execute("SELECT dt_id, unit, vin, status, ownership FROM dt_trucks")]


# Returns the Datatruck drivers copy.
def dt_drivers(conn: sqlite3.Connection) -> list[DatatruckDriver]:
    rows = conn.execute("SELECT driver_id, full_name, driver_type, employee_status, company, unit FROM dt_drivers")
    return [DatatruckDriver(**row) for row in rows]


# Returns the fuel lines fueled on or after a local day ("YYYY-MM-DD"), oldest first.
def fuel_lines(conn: sqlite3.Connection, since_day: str) -> list[FuelLine]:
    rows = conn.execute(
        "SELECT line_id, fueled_at, transaction_type, product, gallons, pump_total, billed, fee, billable, location, city, "
        "state, company, unit, truck_ownership, driver_id, driver_name, driver_type, card_id "
        "FROM fuel_lines WHERE fueled_at >= ? ORDER BY fueled_at", (since_day,))
    return [FuelLine(**{**row, "billable": bool(row["billable"])}) for row in rows]


# Returns the fuel lines fueled from one local day through another ("YYYY-MM-DD", both whole), oldest first.
def fuel_lines_between(conn: sqlite3.Connection, first_day: str, last_day: str) -> list[FuelLine]:
    return [l for l in fuel_lines(conn, first_day) if l.fueled_at[:10] <= last_day]


# Returns the Love's stores with their prices, and their highway and exit where the store's page was read.
def stores(conn: sqlite3.Connection) -> list[Store]:
    return [Store(**row) for row in conn.execute(
        "SELECT store_no, city, state, lat, lng, retail, net, price_date, way FROM stores LEFT JOIN store_exits USING (store_no)")]


# Returns the Telegram groups copy.
def tg_groups(conn: sqlite3.Connection) -> list[TelegramGroup]:
    return [TelegramGroup(**row) for row in conn.execute("SELECT chat_id, title FROM tg_groups")]


# Returns the Telegram groups whose title contains a text (any case), sorted by title.
def find_groups(conn: sqlite3.Connection, text: str) -> list[TelegramGroup]:
    rows = conn.execute("SELECT chat_id, title FROM tg_groups WHERE title LIKE '%' || ? || '%' ORDER BY title", (text,))
    return [TelegramGroup(**row) for row in rows]


# Returns every truck as the app sees it: one row each, with synced, live, helper and your values merged.
def fleet(conn: sqlite3.Connection) -> list[Truck]:
    return [_truck(row) for row in conn.execute("SELECT * FROM fleet ORDER BY unit")]


# Returns only the trucks you picked for the pilot.
def pilot(conn: sqlite3.Connection) -> list[Truck]:
    return [_truck(row) for row in conn.execute("SELECT * FROM fleet WHERE pilot ORDER BY unit")]


# One pilot truck by its unit; None when the unit isn't in the pilot.
def pilot_truck(conn: sqlite3.Connection, unit: str) -> Truck | None:
    row = conn.execute("SELECT * FROM fleet WHERE pilot AND unit = ?", (unit,)).fetchone()
    return _truck(row) if row else None


# Turns a `fleet` row into a Truck: stored times become datetimes, the pilot flag a real true/false.
def _truck(row: sqlite3.Row) -> Truck:
    return Truck(**{**row, "fuel_at": _dt(row["fuel_at"]), "gps_at": _dt(row["gps_at"]), "pilot": bool(row["pilot"])})


# Returns every Datatruck truck for the fleet status, one row each, linked to Samsara or not: its active drivers (a
# team's type is its first driver's), its Samsara readings, whether it has an active fuel card, its newest purchase.
# A card counts when its driver is active on this truck, or when it has no driver and is assigned to this unit: a
# card's unit alone doesn't count, because many active cards still sit on drivers who left.
def fleet_status(conn: sqlite3.Connection) -> list[FleetTruck]:
    rows = conn.execute("""
        WITH active AS (SELECT unit, driver_id, full_name, driver_type FROM dt_drivers
                        WHERE employee_status = 'active' AND unit IS NOT NULL),
             -- the units with a card, worked out once (asking the cards again for every truck takes seconds)
             carded AS (SELECT a.unit FROM fuel_cards c JOIN active a ON a.driver_id = c.driver_id WHERE c.active
                        UNION SELECT unit FROM fuel_cards WHERE active AND driver_id IS NULL AND unit IS NOT NULL),
             fueled AS (SELECT unit, MAX(fueled_at) AS fueled_at FROM fuel_lines GROUP BY unit)
        SELECT d.unit, d.status,
               (SELECT group_concat(full_name, ' & ') FROM active WHERE unit = d.unit) AS driver,
               (SELECT driver_type FROM active WHERE unit = d.unit ORDER BY driver_id LIMIT 1) AS driver_type,
               t.name AS samsara_name, l.gps_at, l.fuel_pct, l.fuel_at,
               d.unit IN (SELECT unit FROM carded) AS has_card, f.fueled_at
        FROM dt_trucks d
        LEFT JOIN trucks t ON t.unit = d.unit
        LEFT JOIN samsara_live l ON l.samsara_id = t.samsara_id
        LEFT JOIN fueled f ON f.unit = d.unit
        ORDER BY d.unit""")
    return [FleetTruck(**{**row, "gps_at": _dt(row["gps_at"]), "fuel_at": _dt(row["fuel_at"]), "has_card": bool(row["has_card"])})
            for row in rows]


# Returns the active orders copy, each with its stops in route order.
def orders(conn: sqlite3.Connection) -> list[Order]:
    stops = defaultdict(list)
    for row in conn.execute("SELECT stop_id, order_id, seq, kind, lat, lng, city, state FROM dt_stops ORDER BY seq"):
        stops[row["order_id"]].append(Stop(**row))
    rows = conn.execute("SELECT order_id, load_id, status, unit, pickup_at FROM dt_orders ORDER BY order_id")
    return [Order(**{**row, "pickup_at": _dt(row["pickup_at"]), "stops": tuple(stops[row["order_id"]])}) for row in rows]


# Returns every data gap as rows of (hole, item, detail), sorted so each kind of hole comes together.
def holes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM holes ORDER BY hole, item").fetchall()


# Returns (table, row count, last refresh time) for every refreshed table.
def status(conn: sqlite3.Connection) -> list[tuple[str, int, str | None]]:
    return [(t, *conn.execute(f"SELECT COUNT(*), MAX(synced_at) FROM {t}").fetchone()) for t in SYNCED_TABLES]


# Adds a linked truck to the pilot (adding it again only updates the note). Unknown units are rejected so a typo
# can't be silently ignored.
def add_pilot(conn: sqlite3.Connection, unit: str, note: str | None) -> None:
    if not conn.execute("SELECT 1 FROM trucks WHERE unit = ?", (unit,)).fetchone():
        raise LookupError(f"Unknown unit '{unit}'. Run `sync` first, or check the list with `fleet`.")
    conn.execute("INSERT INTO pilot_trucks (unit, note, added_at) VALUES (?, ?, ?) "
                 "ON CONFLICT (unit) DO UPDATE SET note = COALESCE(excluded.note, pilot_trucks.note)",
                 (unit, note, now()))


# Takes a truck out of the pilot, together with the tank size and chat you set for it.
def remove_pilot(conn: sqlite3.Connection, unit: str) -> None:
    if conn.execute("DELETE FROM pilot_trucks WHERE unit = ?", (unit,)).rowcount == 0:
        raise LookupError(f"Unit '{unit}' is not in the pilot. See the list with `pilot`.")


# Saves your Telegram group for a pilot truck; None clears it so the auto-match applies again.
def set_chat(conn: sqlite3.Connection, unit: str, chat_id: int | None) -> None:
    _set_pilot_value(conn, unit, "chat_id", chat_id)


# Saves your tank size for a pilot truck; None clears it so the tank helper's estimate applies again.
def set_tank(conn: sqlite3.Connection, unit: str, tank_gal: float | None) -> None:
    _set_pilot_value(conn, unit, "tank_gal", tank_gal)


# Writes one of your values for a pilot truck. Other units are rejected so a typo can't be silently ignored.
def _set_pilot_value(conn: sqlite3.Connection, unit: str, column: str, value) -> None:
    # `column` comes only from the two functions above, never from user input, so the f-string is safe.
    if conn.execute(f"UPDATE pilot_trucks SET {column} = ? WHERE unit = ?", (value, unit)).rowcount == 0:
        raise LookupError(f"Unit '{unit}' is not in the pilot. Add it first with `pilot-add {unit}`.")
