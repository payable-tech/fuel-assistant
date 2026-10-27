# SQLite storage. Every table has exactly one writer; source copies are replaced whole on each refresh.
# The app reads trucks through the `fleet` view (one row per truck); data gaps are collected in the `holes` view.
import json
import sqlite3
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone

import config
from models import (DatatruckDriver, DatatruckTruck, Event, FuelCard, FuelLine, FuelPlan, FuelStop, LoadPlan,
                    MarketPrice, Order, PlanStop, Progress, SamsaraLive, SamsaraVehicle, Stop, Store, StoreOnRoute,
                    SyncedTruck, TankEstimate, TelegramGroup, Truck, Waypoint)

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

-- Writer: market (U.S. EIA weekly retail diesel prices by region): the yardstick for what we pay.
CREATE TABLE IF NOT EXISTS market_prices (
    day       TEXT NOT NULL,   -- the Monday the price was taken
    region    TEXT NOT NULL,
    price     REAL NOT NULL,   -- dollars per gallon at the pump
    synced_at TEXT NOT NULL,
    PRIMARY KEY (day, region)
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

-- ===== Yours. Writer: you (`pilot-add`, `pilot-remove`, `set-tank`, `set-chat`). Nothing else ever touches it. =====
-- The trucks the assistant serves. An empty tank or chat means "use the helper's estimate / the auto-matched group".
CREATE TABLE IF NOT EXISTS pilot_trucks (
    unit     TEXT PRIMARY KEY,
    tank_gal REAL,
    chat_id  INTEGER,
    note     TEXT,
    added_at TEXT NOT NULL
);

-- ===== The app's own records. Writer: the planner job (plan_loads). Kept: never replaced, never dropped. =====
-- One plan per load, made once; a load started over (plan_loads.restart, a truck going live mid-load) gets a second,
-- later one, and the newest is the one followed. `plan` is the whole plan as JSON (the truck as it was, the road, the
-- Love's along it, the stops), so it can be redrawn and checked exactly as it was made.
CREATE TABLE IF NOT EXISTS plans (
    plan_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    unit     TEXT NOT NULL,
    order_id INTEGER NOT NULL,
    load_id  TEXT NOT NULL,
    made_at  TEXT NOT NULL,
    plan     TEXT NOT NULL,
    UNIQUE (unit, order_id, made_at)
);

-- Every message about a plan, oldest first: the first one, then one full message per major event, each to a chat
-- (the test chat for now). sent_at and message_id stay empty until Telegram took it. Only a plan's newest message
-- keeps its navigation link; older ones read "Newer update below" instead.
CREATE TABLE IF NOT EXISTS plan_messages (
    message_no INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id    INTEGER NOT NULL REFERENCES plans (plan_id),
    chat_id    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    made_at    TEXT NOT NULL,
    sent_at    TEXT,
    message_id INTEGER
);

-- How far each followed plan has got, as JSON (models.Progress): the road in force (the plan or its latest re-plan),
-- the waypoints passed on it, the Love's planned so far, and every event told.
CREATE TABLE IF NOT EXISTS plan_progress (
    plan_id  INTEGER PRIMARY KEY REFERENCES plans (plan_id),
    progress TEXT NOT NULL
);

-- Writer: the scheduler. When each automatic refresh last ran and whether it crashed.
CREATE TABLE IF NOT EXISTS job_runs (
    job         TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    error       TEXT
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
# Your pilot list (pilot_trucks), the saved plans with their messages and progress, and job_runs are not in this
# list, so they are never dropped.
SYNCED_TABLES = ["samsara_vehicles", "samsara_live", "dt_trucks", "dt_drivers", "tg_groups", "dt_orders", "dt_stops",
                 "stores", "price_history", "price_files", "fuel_lines", "fuel_cards", "market_prices", "trucks",
                 "tank_estimates", "fuel_stops"]


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
        _schema_ready.add(str(config.DB_PATH))


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
    _replace(conn, "stores", [_row(s, skip="name") for s in stores])  # `name` is only for stations that aren't Love's


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


# Saves a load's plan and returns its plan_id. The table refuses the same plan twice (same truck, load and moment);
# a load started over gets a later one.
def save_plan(conn: sqlite3.Connection, p: LoadPlan) -> int:
    cursor = conn.execute("INSERT INTO plans (unit, order_id, load_id, made_at, plan) VALUES (?, ?, ?, ?, ?)",
                          (p.truck.unit, p.order.order_id, p.order.load_id, _ts(p.made_at),
                           json.dumps(asdict(p), default=_iso)))
    return cursor.lastrowid


# Queues one more message about a plan for a chat; the planner job sends it (see unsent_messages).
def queue_message(conn: sqlite3.Connection, plan_id: int, chat_id: int, text: str, made_at: str) -> None:
    conn.execute("INSERT INTO plan_messages (plan_id, chat_id, text, made_at) VALUES (?, ?, ?, ?)",
                 (plan_id, chat_id, text, made_at))


# Returns (message_no, plan_id, chat_id, text) of each message not sent yet that was written at or after `since`,
# oldest first.
def unsent_messages(conn: sqlite3.Connection, since: datetime) -> list[tuple[int, int, int, str]]:
    rows = conn.execute("SELECT message_no, plan_id, chat_id, text FROM plan_messages WHERE sent_at IS NULL "
                        "AND made_at >= ? ORDER BY message_no", (_ts(since),))
    return [tuple(row) for row in rows]


# Records that a message was sent, with its Telegram id (to edit it later).
def mark_sent(conn: sqlite3.Connection, message_no: int, message_id: int, sent_at: str) -> None:
    conn.execute("UPDATE plan_messages SET sent_at = ?, message_id = ? WHERE message_no = ?",
                 (sent_at, message_id, message_no))


# Returns (message_no, chat_id, message_id, text) of the newest message sent to `chat_id` about the truck of plan
# `plan_id`, any of its plans (before message `before` when given), or None when none was sent there. A truck's next
# plan so takes the link off its last plan's last message too.
def last_sent(conn: sqlite3.Connection, plan_id: int, chat_id: int,
              before: int | None = None) -> tuple[int, int, int, str] | None:
    row = conn.execute("SELECT m.message_no, m.chat_id, m.message_id, m.text FROM plan_messages m JOIN plans p "
                       "USING (plan_id) WHERE p.unit = (SELECT unit FROM plans WHERE plan_id = ?) AND m.chat_id = ? "
                       "AND m.message_id IS NOT NULL AND (? IS NULL OR m.message_no < ?) "
                       "ORDER BY m.message_no DESC LIMIT 1", (plan_id, chat_id, before, before)).fetchone()
    return tuple(row) if row else None


# Returns the chats a plan's messages go to: those its first message was queued for, so a truck that goes live
# mid-load starts in its own group with its next plan, not with an update about one it never got.
def plan_chats(conn: sqlite3.Connection, plan_id: int) -> list[int]:
    rows = conn.execute("SELECT chat_id FROM plan_messages WHERE plan_id = ? GROUP BY chat_id ORDER BY MIN(message_no)",
                        (plan_id,))
    return [row["chat_id"] for row in rows]


# Records a sent message's text as edited.
def set_text(conn: sqlite3.Connection, message_no: int, text: str) -> None:
    conn.execute("UPDATE plan_messages SET text = ? WHERE message_no = ?", (text, message_no))


# Saves how far a followed plan has got (replacing what was saved before).
def save_progress(conn: sqlite3.Connection, plan_id: int, progress: Progress) -> None:
    conn.execute("INSERT OR REPLACE INTO plan_progress (plan_id, progress) VALUES (?, ?)",
                 (plan_id, json.dumps(asdict(progress), default=_iso)))


# Returns (plan_id, plan, progress) of each truck's newest plan that is being followed and was made at or after
# `since`.
def followed(conn: sqlite3.Connection, since: datetime) -> list[tuple[int, LoadPlan, Progress]]:
    rows = conn.execute("SELECT g.plan_id, p.plan, g.progress FROM plan_progress g JOIN plans p USING (plan_id) "
                        "WHERE p.made_at >= ? AND p.plan_id = (SELECT MAX(plan_id) FROM plans q WHERE q.unit = p.unit)",
                        (_ts(since),))
    return [(row["plan_id"], _load_plan(json.loads(row["plan"])), _progress(json.loads(row["progress"])))
            for row in rows]


# Returns (unit, order id) of every load that already has a plan.
def planned_loads(conn: sqlite3.Connection) -> set[tuple[str, int]]:
    return {(row["unit"], row["order_id"]) for row in conn.execute("SELECT unit, order_id FROM plans")}


# Returns the plans made on or after a UTC day ("YYYY-MM-DD"), newest first, each as stored plus its plan_id.
def plans(conn: sqlite3.Connection, since_day: str) -> list[dict]:
    rows = conn.execute("SELECT plan_id, plan FROM plans WHERE made_at >= ? ORDER BY made_at DESC", (since_day,))
    return [_saved_plan(row) for row in rows]


# Returns one saved plan as stored plus its plan_id, or None when there is no such plan.
def plan(conn: sqlite3.Connection, plan_id: int) -> dict | None:
    row = conn.execute("SELECT plan_id, plan FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
    return _saved_plan(row) if row else None


# A stored plan row as a dict: the plan's JSON plus its plan_id.
def _saved_plan(row: sqlite3.Row) -> dict:
    return {"plan_id": row["plan_id"], **json.loads(row["plan"])}


# Returns one saved plan as the LoadPlan it was made from. Raises LookupError when there is no such plan.
def load_plan(conn: sqlite3.Connection, plan_id: int) -> LoadPlan:
    row = conn.execute("SELECT plan FROM plans WHERE plan_id = ?", (plan_id,)).fetchone()
    if row is None:
        raise LookupError(f"There is no plan {plan_id}")
    return _load_plan(json.loads(row["plan"]))


# A followed plan's progress from its JSON.
def _progress(d: dict) -> Progress:
    return Progress(road=_load_plan(d["road"]), passed=d["passed"], planned=tuple(Waypoint(**w) for w in d["planned"]),
                    events=tuple(Event(**{**e, "at": _dt(e["at"])}) for e in d["events"]))


# A plan's JSON back as the LoadPlan it was made from (datetimes from ISO text, lists back to tuples).
def _load_plan(d: dict) -> LoadPlan:
    truck, order, fuel = d["truck"], d["order"], d["plan"]
    return LoadPlan(
        made_at=_dt(d["made_at"]),
        truck=Truck(**{**truck, "fuel_at": _dt(truck["fuel_at"]), "gps_at": _dt(truck["gps_at"])}),
        order=Order(**{**order, "pickup_at": _dt(order["pickup_at"]), "stops": tuple(Stop(**s) for s in order["stops"])}),
        stops_ahead=tuple(Stop(**s) for s in d["stops_ahead"]), line=tuple(tuple(p) for p in d["line"]),
        route_mi=d["route_mi"], candidates=tuple(StoreOnRoute(**{**c, "store": Store(**c["store"])}) for c in d["candidates"]),
        mpg=d["mpg"], price_date=d["price_date"], end_price=d.get("end_price"),  # plans before 2026-10-21 lack it
        end_pump=d.get("end_pump"),  # and those before 2026-10-22 this
        via=tuple(tuple(p) for p in d.get("via", ())),  # and those before 2026-10-23 this
        plan=FuelPlan(stops=tuple(PlanStop(**{**s, "store": Store(**s["store"])}) for s in fuel["stops"]),
                      end_gal=fuel["end_gal"], fuel_cost=fuel["fuel_cost"]) if fuel else None)


# How a datetime is written into JSON: ISO text, which browsers read directly.
def _iso(value: datetime) -> str:
    return value.isoformat()


# Records that a scheduled job started (error None) or finished (with its error, if it crashed).
def record_job(conn: sqlite3.Connection, job: str, started_at: str, finished_at: str | None, error: str | None) -> None:
    conn.execute("INSERT INTO job_runs (job, started_at, finished_at, error) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT (job) DO UPDATE SET started_at = excluded.started_at, finished_at = excluded.finished_at, "
                 "error = excluded.error", (job, started_at, finished_at, error))


# Returns the scheduled jobs' last runs as {job: row}.
def job_runs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["job"]: row for row in conn.execute("SELECT * FROM job_runs")}


# Replaces the fuel cards copy.
def replace_fuel_cards(conn: sqlite3.Connection, cards: list[FuelCard]) -> None:
    _replace(conn, "fuel_cards", [_row(c) for c in cards])


# Returns card id -> its deduction policy ("retail_plus_fee", "retail_amount", "invoice_amount"), for what each
# purchase cost the driver.
def card_policies(conn: sqlite3.Connection) -> dict[int, str | None]:
    return {row["card_id"]: row["deduction_policy"] for row in conn.execute("SELECT card_id, deduction_policy FROM fuel_cards")}


# Replaces the EIA market prices copy.
def replace_market_prices(conn: sqlite3.Connection, prices: list[MarketPrice]) -> None:
    _replace(conn, "market_prices", [_row(p) for p in prices])


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


# Returns the market prices taken on or after a day ("YYYY-MM-DD").
def market_prices(conn: sqlite3.Connection, since_day: str) -> list[MarketPrice]:
    rows = conn.execute("SELECT day, region, price FROM market_prices WHERE day >= ? ORDER BY day", (since_day,))
    return [MarketPrice(**row) for row in rows]


# Returns the Love's stores with their prices.
def stores(conn: sqlite3.Connection) -> list[Store]:
    return [Store(**row) for row in conn.execute(
        "SELECT store_no, city, state, lat, lng, retail, net, price_date FROM stores")]


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


# Turns a `fleet` row into a Truck: stored times become datetimes, the pilot flag a real true/false.
def _truck(row: sqlite3.Row) -> Truck:
    return Truck(**{**row, "fuel_at": _dt(row["fuel_at"]), "gps_at": _dt(row["gps_at"]), "pilot": bool(row["pilot"])})


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
