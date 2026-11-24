# SQLite storage. Every table has exactly one writer; source copies are replaced whole on each refresh.
# The app reads trucks through the `fleet` view (one row per truck); data gaps are collected in the `holes` view.
# The tables and views themselves are defined in schema.py; the functions here stand in sections that follow them.
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
from base.store import schema

_schema_lock = threading.Lock()
_schema_ready: set[str] = set()  # database files this process has already set up


# ===== Opening the database =====


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
        if conn.execute("PRAGMA user_version").fetchone()[0] != schema.SCHEMA_VERSION:
            _rebuild(conn)
        conn.executescript("BEGIN IMMEDIATE;" + schema.TABLES + schema.VIEWS + "COMMIT;")
        _add_column(conn, "recommendations", "sent_at", "TEXT")
        _add_column(conn, "recommendations", "lat", "REAL")
        _add_column(conn, "recommendations", "lng", "REAL")
        _add_column(conn, "agent_runs", "record", "TEXT")
        _add_column(conn, "fuel_cards", "last4", "TEXT")
        _schema_ready.add(str(config.DB_PATH))


# Adds a column a kept table got later (kept tables are never dropped and rebuilt, so CREATE TABLE alone won't add it).
def _add_column(conn: sqlite3.Connection, table: str, column: str, kind: str) -> None:
    if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


# Drops every refreshed table (its job refills it) and stamps the new schema version. Manual settings stay.
def _rebuild(conn: sqlite3.Connection) -> None:
    conn.executescript("BEGIN IMMEDIATE; DROP VIEW IF EXISTS holes; DROP VIEW IF EXISTS fleet; DROP VIEW IF EXISTS active_vehicles;"
                       + "".join(f"DROP TABLE IF EXISTS {t};" for t in schema.SYNCED_TABLES)
                       + f"PRAGMA user_version = {schema.SCHEMA_VERSION}; COMMIT;")


# ===== Shared helpers: times as stored text, records as rows, replacing a whole table =====


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


# The stored values a record type still has: a field dropped from the code since doesn't stop old rows from loading
# (otherwise every look of the engine would fail on its saved look, quietly).
def _known(cls, values: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in values.items() if k in names}


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


# ===== Source copies: Samsara =====


# Replaces the Samsara copy.
def replace_samsara_vehicles(conn: sqlite3.Connection, vehicles: list[SamsaraVehicle]) -> None:
    _replace(conn, "samsara_vehicles", [_row(v) for v in vehicles])


# Returns the Samsara copy.
def samsara_vehicles(conn: sqlite3.Connection) -> list[SamsaraVehicle]:
    rows = conn.execute("SELECT samsara_id, name, vin, mpg, last_gps_at FROM samsara_vehicles")
    return [SamsaraVehicle(**{**row, "last_gps_at": _dt(row["last_gps_at"])}) for row in rows]


# Replaces the Samsara live copy (every vehicle's latest GPS point and fuel level).
def replace_samsara_live(conn: sqlite3.Connection, rows: list[SamsaraLive]) -> None:
    _replace(conn, "samsara_live", [_row(r) for r in rows])


# ===== Source copies: Datatruck trucks, drivers and loads =====


# Replaces the Datatruck trucks copy.
def replace_dt_trucks(conn: sqlite3.Connection, trucks: list[DatatruckTruck]) -> None:
    _replace(conn, "dt_trucks", [_row(t) for t in trucks])


# Returns the Datatruck trucks copy.
def dt_trucks(conn: sqlite3.Connection) -> list[DatatruckTruck]:
    return [DatatruckTruck(**row) for row in conn.execute("SELECT dt_id, unit, vin, status, ownership FROM dt_trucks")]


# Replaces the Datatruck drivers copy.
def replace_dt_drivers(conn: sqlite3.Connection, drivers: list[DatatruckDriver]) -> None:
    _replace(conn, "dt_drivers", [_row(d) for d in drivers])


# Returns the Datatruck drivers copy.
def dt_drivers(conn: sqlite3.Connection) -> list[DatatruckDriver]:
    rows = conn.execute("SELECT driver_id, full_name, driver_type, employee_status, company, unit FROM dt_drivers")
    return [DatatruckDriver(**row) for row in rows]


# Replaces all active orders and their stops together.
def replace_orders(conn: sqlite3.Connection, orders: list[Order]) -> None:
    _replace(conn, "dt_orders", [_row(o, skip="stops") for o in orders])
    _replace(conn, "dt_stops", [_row(s) for o in orders for s in o.stops])


# Returns the active orders copy, each with its stops in route order.
def orders(conn: sqlite3.Connection) -> list[Order]:
    stops = defaultdict(list)
    for row in conn.execute("SELECT stop_id, order_id, seq, kind, lat, lng, city, state FROM dt_stops ORDER BY seq"):
        stops[row["order_id"]].append(Stop(**row))
    rows = conn.execute("SELECT order_id, load_id, status, unit, pickup_at FROM dt_orders ORDER BY order_id")
    return [Order(**{**row, "pickup_at": _dt(row["pickup_at"]), "stops": tuple(stops[row["order_id"]])}) for row in rows]


# ===== Source copies: fuel purchases and cards =====


# Replaces the fuel lines copy.
def replace_fuel_lines(conn: sqlite3.Connection, lines: list[FuelLine]) -> None:
    _replace(conn, "fuel_lines", [_row(f) for f in lines])


# Replaces only the fuel lines fueled on or after a local day; older lines stay as they are.
def replace_fuel_lines_since(conn: sqlite3.Connection, since_day: str, lines: list[FuelLine]) -> None:
    conn.execute("DELETE FROM fuel_lines WHERE fueled_at >= ?", (since_day,))
    _insert(conn, "fuel_lines", [_row(f) for f in lines])


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


# Replaces the fuel cards copy.
def replace_fuel_cards(conn: sqlite3.Connection, cards: list[FuelCard]) -> None:
    _replace(conn, "fuel_cards", [_row(c) for c in cards])


# ===== Source copies: Telegram groups =====


# Replaces the Telegram groups copy.
def replace_tg_groups(conn: sqlite3.Connection, groups: list[TelegramGroup]) -> None:
    _replace(conn, "tg_groups", [_row(g) for g in groups])


# Returns the Telegram groups copy.
def tg_groups(conn: sqlite3.Connection) -> list[TelegramGroup]:
    return [TelegramGroup(**row) for row in conn.execute("SELECT chat_id, title FROM tg_groups")]


# Returns the Telegram groups whose title contains a text (any case), sorted by title.
def find_groups(conn: sqlite3.Connection, text: str) -> list[TelegramGroup]:
    rows = conn.execute("SELECT chat_id, title FROM tg_groups WHERE title LIKE '%' || ? || '%' ORDER BY title", (text,))
    return [TelegramGroup(**row) for row in rows]


# ===== Source copies: Love's stores and prices =====


# Replaces the Love's stores and prices.
def replace_stores(conn: sqlite3.Connection, stores: list[Store]) -> None:
    # `name` is only for stations that aren't Love's; `way` is kept in its own table (store_exits)
    _replace(conn, "stores", [{k: v for k, v in _row(s, skip="name").items() if k != "way"} for s in stores])


# Returns the Love's stores with their prices, and their highway and exit where the store's page was read.
def stores(conn: sqlite3.Connection) -> list[Store]:
    return [Store(**row) for row in conn.execute(
        "SELECT store_no, city, state, lat, lng, retail, net, price_date, way FROM stores LEFT JOIN store_exits USING (store_no)")]


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


# ===== Trucks: the linked trucks, the pilot, and your own values for it =====


# Replaces all linked trucks at once, so a truck gone from the sources also disappears here.
def replace_trucks(conn: sqlite3.Connection, trucks: list[SyncedTruck]) -> None:
    _replace(conn, "trucks", [_row(t) for t in trucks])


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
# team's type is its first driver's), its Samsara readings, whether it has an active fuel card (and those cards' last
# four digits), its newest purchase.
# A card counts when its driver is active on this truck, or when it has no driver and is assigned to this unit: a
# card's unit alone doesn't count, because many active cards still sit on drivers who left.
def fleet_status(conn: sqlite3.Connection) -> list[FleetTruck]:
    rows = conn.execute("""
        WITH active AS (SELECT unit, driver_id, full_name, driver_type FROM dt_drivers
                        WHERE employee_status = 'active' AND unit IS NOT NULL),
             -- the units with a card, worked out once (asking the cards again for every truck takes seconds)
             carded AS (SELECT a.unit, c.last4 FROM fuel_cards c JOIN active a ON a.driver_id = c.driver_id WHERE c.active
                        UNION SELECT unit, last4 FROM fuel_cards WHERE active AND driver_id IS NULL AND unit IS NOT NULL),
             fueled AS (SELECT unit, MAX(fueled_at) AS fueled_at FROM fuel_lines GROUP BY unit)
        SELECT d.unit, d.status,
               (SELECT group_concat(full_name, ' & ') FROM active WHERE unit = d.unit) AS driver,
               (SELECT driver_type FROM active WHERE unit = d.unit ORDER BY driver_id LIMIT 1) AS driver_type,
               t.name AS samsara_name, l.gps_at, l.fuel_pct, l.fuel_at,
               d.unit IN (SELECT unit FROM carded) AS has_card, f.fueled_at,
               (SELECT group_concat(last4, ', ') FROM carded WHERE unit = d.unit) AS cards
        FROM dt_trucks d
        LEFT JOIN trucks t ON t.unit = d.unit
        LEFT JOIN samsara_live l ON l.samsara_id = t.samsara_id
        LEFT JOIN fueled f ON f.unit = d.unit
        ORDER BY d.unit""")
    return [FleetTruck(**{**row, "gps_at": _dt(row["gps_at"]), "fuel_at": _dt(row["fuel_at"]), "has_card": bool(row["has_card"])})
            for row in rows]


# The diesel gallons each unit bought on or after a local day ("YYYY-MM-DD"), by unit.
def diesel_by_unit(conn: sqlite3.Connection, since_day: str) -> dict[str, float]:
    return {unit: gallons for unit, gallons in conn.execute(
        "SELECT unit, SUM(gallons) FROM fuel_lines WHERE fueled_at >= ? AND transaction_type = 'fuel' AND product = 'ULSD' "
        "AND gallons > 0 AND unit IS NOT NULL GROUP BY unit", (since_day,))}


# Returns every data gap as rows of (hole, item, detail), sorted so each kind of hole comes together.
def holes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM holes ORDER BY hole, item").fetchall()


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


# ===== Helper results: fuel stops, tank sizes, engine fuel factors, fill lookups =====


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


# Replaces the engine fuel factors.
def replace_burn_factors(conn: sqlite3.Connection, factors: list[BurnFactor]) -> None:
    _replace(conn, "burn_factors", [_row(f) for f in factors])


# Each pilot truck's engine fuel factor, by unit.
def burn_factors(conn: sqlite3.Connection) -> dict[str, float]:
    return {r["unit"]: r["gal_per_unit"] for r in conn.execute("SELECT unit, gal_per_unit FROM burn_factors")}


# Adds newly looked-up fills.
def add_fill_lookups(conn: sqlite3.Connection, fills: list[FillLookup]) -> None:
    _insert(conn, "fill_lookups", [_row(f) for f in fills])


# Returns every looked-up fill by its fuel line id.
def fill_lookups(conn: sqlite3.Connection) -> dict[int, FillLookup]:
    rows = conn.execute("SELECT line_id, lat, lng, gauge_before FROM fill_lookups")
    return {row["line_id"]: FillLookup(**row) for row in rows}


# ===== The fuel engine's records: each truck's latest look, its trips, the messages =====


# Saves a pilot truck's latest look, replacing the one before.
def save_truck_watch(conn: sqlite3.Connection, watch: TruckWatch) -> None:
    conn.execute("INSERT OR REPLACE INTO truck_watch (unit, look) VALUES (?, ?)",
                 (watch.unit, json.dumps(asdict(watch), default=lambda v: v.isoformat())))


# A pilot truck's latest look; None before its first.
def truck_watch(conn: sqlite3.Connection, unit: str) -> TruckWatch | None:
    row = conn.execute("SELECT look FROM truck_watch WHERE unit = ?", (unit,)).fetchone()
    return _watch(row["look"]) if row else None


# Every pilot truck's latest look.
def truck_watches(conn: sqlite3.Connection) -> list[TruckWatch]:
    return [_watch(r["look"]) for r in conn.execute("SELECT look FROM truck_watch ORDER BY unit")]


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


# ===== Accounting: the EFS statements and Samsara's evidence for them =====


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


# A stored statement row back as an EfsStatement (its summary from JSON).
def _statement(row: sqlite3.Row) -> EfsStatement:
    return EfsStatement(**{**row, "summary": tuple((name, amount) for name, amount in json.loads(row["summary"]))})


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


# ===== Jobs and health: each job's last run, each source's last refresh, the heartbeat's problems =====


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


# Returns (table, row count, last refresh time) for every refreshed table.
def status(conn: sqlite3.Connection) -> list[tuple[str, int, str | None]]:
    return [(t, *conn.execute(f"SELECT COUNT(*), MAX(synced_at) FROM {t}").fetchone()) for t in schema.SYNCED_TABLES]


# ===== The card agent's runs =====


# Claims a message that woke the card agent, so each is handled once (a restart or a repeat event finds it taken).
# True when it was new.
def claim_agent_run(conn: sqlite3.Connection, chat_id: int, message_id: int, unit: str | None, at: datetime,
                    text: str) -> bool:
    return conn.execute("INSERT OR IGNORE INTO agent_runs (chat_id, message_id, unit, woke_at, text) VALUES (?, ?, ?, ?, ?)",
                        (chat_id, message_id, unit, _ts(at), text)).rowcount == 1


# Records how a card agent run ended: its outcome, the tools it used (JSON), the card it opened and when, its error,
# and the run's whole record (JSON; None when Claude was not asked).
def finish_agent_run(conn: sqlite3.Connection, chat_id: int, message_id: int, outcome: str, steps: str,
                     opened_card: str | None, opened_at: datetime | None, error: str | None, record: str | None) -> None:
    conn.execute("UPDATE agent_runs SET outcome = ?, steps = ?, opened_card = ?, opened_at = ?, error = ?, record = ? "
                 "WHERE chat_id = ? AND message_id = ?",
                 (outcome, steps, opened_card, _ts(opened_at) if opened_at else None, error, record, chat_id, message_id))


# How many jobs the card agent did since a moment: the requests it used a tool for (a thank-you it only read is none).
def agent_jobs_since(conn: sqlite3.Connection, since: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM agent_runs WHERE woke_at >= ? AND steps IS NOT NULL AND steps != '[]'",
                        (_ts(since),)).fetchone()[0]


# One run of the card agent as its row; None when there is none for that message.
def agent_run(conn: sqlite3.Connection, chat_id: int, message_id: int) -> dict | None:
    row = conn.execute(
        "SELECT chat_id, message_id, unit, woke_at, text, outcome, steps, opened_card, opened_at, error, record "
        "FROM agent_runs WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)).fetchone()
    return dict(row) if row else None


# Notes that the card agent is running at this moment (its pulse's beat).
def agent_beat(conn: sqlite3.Connection, at: datetime) -> None:
    conn.execute("INSERT INTO agent_pulse (id, beat_at) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET beat_at = excluded.beat_at",
                 (_ts(at),))


# Notes whether the card agent found eManager logged in; "since" moves only when that changed.
def agent_emanager(conn: sqlite3.Connection, alive: bool, at: datetime) -> None:
    conn.execute("INSERT INTO agent_pulse (id, emanager, emanager_since) VALUES (1, ?, ?) ON CONFLICT (id) DO UPDATE SET "
                 "emanager_since = CASE WHEN agent_pulse.emanager IS excluded.emanager THEN agent_pulse.emanager_since "
                 "ELSE excluded.emanager_since END, emanager = excluded.emanager", (int(alive), _ts(at)))


# Notes the last tag the card agent heard, and in a few words what it did about it.
def agent_tag(conn: sqlite3.Connection, at: datetime, note: str) -> None:
    conn.execute("INSERT INTO agent_pulse (id, tag_at, tag_note) VALUES (1, ?, ?) ON CONFLICT (id) DO UPDATE SET "
                 "tag_at = excluded.tag_at, tag_note = excluded.tag_note", (_ts(at), note))


# The card agent's pulse as its row; None before its first beat.
def agent_pulse(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT beat_at, emanager, emanager_since, tag_at, tag_note FROM agent_pulse WHERE id = 1").fetchone()
    return dict(row) if row else None


# The card agent's runs since a moment, newest first, each as its row.
def agent_runs_since(conn: sqlite3.Connection, since: datetime) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT chat_id, message_id, unit, woke_at, text, outcome, steps, opened_card, opened_at, error, record "
        "FROM agent_runs WHERE woke_at >= ? ORDER BY woke_at DESC", (_ts(since),))]


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
