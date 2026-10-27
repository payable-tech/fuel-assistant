# Dashboard glue: reads the DB (and, for a plan's trip, Samsara) and returns each view's numbers as JSON-ready dicts.
import json
import logging
import threading
import time
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import config
import db
from core import compare, fuel, geo, habits, market, trip
from models import DriverHabit, FuelPlan, FuelReading, PlanStop, Store, StoreOnRoute, Trip
from sources import samsara

log = logging.getLogger(__name__)

TRIP_CACHE_S = 300  # a plan's trip is rebuilt from Samsara at most this often, however often the page asks
WARM_EVERY_S = 30  # how often the background loop looks for a truck's newest plan to build or rebuild
_trips: dict[int, tuple[float, dict]] = {}  # plan id -> (when built, payload)
_building: set[int] = set()  # plan ids being rebuilt in the background right now, so none is fetched twice at once
_lock = threading.Lock()


# Today on the company's clock (US Central), so the dashboard's days and weeks turn over at Central midnight
# whatever this PC's time zone.
def today() -> date:
    return datetime.now(fuel.CENTRAL).date()


# The Trends view: weekly numbers, breakdowns of the recent weeks, data freshness and data holes.
def baseline_payload(today: date) -> dict:
    since = (date.fromisoformat(fuel.week_of(today.isoformat())) - timedelta(weeks=config.BASELINE_WEEKS)).isoformat()
    with db.connect() as conn:
        lines = db.fuel_lines(conn, since)
        prices = db.market_prices(conn, since)
        linked_units = {t.unit for t in db.fleet(conn)}
        sources = _sources(conn)
        holes = Counter(row["hole"] for row in db.holes(conn))
    payload = fuel.baseline(lines, today, linked_units, config.BASELINE_WEEKS, config.BREAKDOWN_WEEKS,
                            market.pricer(prices))
    payload["sources"] = sources
    payload["holes"] = [{"hole": hole, "count": n} for hole, n in sorted(holes.items())]
    payload["today"] = today.isoformat()
    return payload


# The Live view: this week so far, today, the last days, the newest purchases and who bought outside Love's.
def live_payload(today: date) -> dict:
    since = (today - timedelta(days=config.LIVE_DAYS + 14)).isoformat()  # enough for last week's same hours too
    with db.connect() as conn:
        lines = db.fuel_lines(conn, since)
        sources = _sources(conn)
        jobs = [dict(row) for row in db.job_runs(conn).values()]
    payload = fuel.live(lines, config.LIVE_FEED_SIZE, config.LIVE_DAYS, config.LIVE_OUTSIDE_LIMIT)
    payload["sources"] = sources
    payload["jobs"] = jobs
    return payload


# The Plans view list: each pilot truck with where it is now and its plans of the last PLANS_DAYS days, newest first.
# A truck's newest plan is active while its load is still open in Datatruck; an older one's load has ended, since a
# truck's next load is planned only once it has been at the last stop.
def plans_payload() -> dict:
    since = (today() - timedelta(days=config.PLANS_DAYS)).isoformat()
    with db.connect() as conn:
        trucks = db.pilot(conn)
        saved = db.plans(conn, since)
        open_orders = {o.order_id for o in db.orders(conn)}
    result = []
    for t in trucks:
        own = [p for p in saved if p["truck"]["unit"] == t.unit]
        result.append({"unit": t.unit, "driver": t.driver, "fuel_pct": t.fuel_pct, "place": t.place,
                       "plans": [_summary(p) | {"active": i == 0 and p["order"]["order_id"] in open_orders}
                                 for i, p in enumerate(own)]})
    return {"days": config.PLANS_DAYS, "reserve_pct": config.RESERVE_PCT, "trucks": result}


# One saved plan with what the truck really did since: the road it drove, its fill-ups and its fuel gauge. Answers
# at once from the last build (rebuilding it in the background once it is TRIP_CACHE_S old); only a plan never built
# before waits for Samsara.
def plan_payload(plan_id: int) -> dict:
    cached = _trips.get(plan_id)
    if cached is None:
        return _build(plan_id)
    if _stale(plan_id):
        threading.Thread(target=_refresh, args=(plan_id,), daemon=True).start()
    return cached[1]


# Forever, in the background: builds each pilot truck's newest plan and rebuilds it while its load is open, so
# opening a truck in the Plans view never waits for Samsara. A failed round is logged and tried again.
def keep_fresh() -> None:
    while True:
        try:
            for plan_id in _to_warm(plans_payload()["trucks"]):
                _refresh(plan_id)
        except Exception:  # e.g. the database busy for a moment
            log.exception("Could not keep the plans' trips fresh")
        time.sleep(WARM_EVERY_S)


# The plans to build now: each truck's newest plan when it was never built, or when its load is open and its build
# is stale. A finished load's trip only changes by late fuel lines, which a click picks up.
def _to_warm(trucks: list[dict]) -> list[int]:
    newest = [t["plans"][0] for t in trucks if t["plans"]]
    return [p["plan_id"] for p in newest if p["plan_id"] not in _trips or (p["active"] and _stale(p["plan_id"]))]


# True when a plan was never built or its build is at least TRIP_CACHE_S old.
def _stale(plan_id: int) -> bool:
    cached = _trips.get(plan_id)
    return cached is None or time.monotonic() - cached[0] >= TRIP_CACHE_S


# Rebuilds one plan's payload unless another thread is already at it; a failure is logged and the last build stays.
def _refresh(plan_id: int) -> None:
    with _lock:
        if plan_id in _building:
            return
        _building.add(plan_id)
    try:
        _build(plan_id)
    except Exception:
        log.exception("Could not rebuild the trip of plan %d", plan_id)
    finally:
        with _lock:
            _building.discard(plan_id)


# Builds one plan's payload from the DB and Samsara (seconds: Samsara's GPS history is slow) and keeps it.
def _build(plan_id: int) -> dict:
    with db.connect() as conn:
        saved = db.plan(conn, plan_id)
        if saved is None:
            raise LookupError(f"There is no plan {plan_id}")
        made_at = datetime.fromisoformat(saved["made_at"])
        lines = db.fuel_lines(conn, since_day=(made_at - timedelta(days=1)).date().isoformat())
        habit = _driver_habit(conn, saved["truck"]["unit"])
        stores = db.stores(conn)
        policies = db.card_policies(conn)
    truck, end, now = saved["truck"], saved["stops_ahead"][-1], datetime.now(timezone.utc)
    track = samsara.gps_history(truck["samsara_id"], made_at, now)
    plan_stops = [(s["store"]["lat"], s["store"]["lng"]) for s in (saved["plan"] or {"stops": []})["stops"]]
    driven = trip.trip(made_at, track, [l for l in lines if l.unit == truck["unit"]], plan_stops,
                       (end["lat"], end["lng"]), config.STOP_REACHED_MI, timedelta(minutes=config.TANK_WINDOW_MIN),
                       config.TRACK_STEP_MI, policies)
    gauge = samsara.fuel_history(truck["samsara_id"], made_at, driven.finished_at or now)
    # plans made before the end price was kept use today's price of the Love's nearest the destination
    end_price = saved.get("end_price") or geo.nearest(stores, (end["lat"], end["lng"])).net
    simulated = _simulate(saved, habit)
    payload = {"plan": saved, "built_at": now.isoformat(), "trip": _plain(driven),
               "gauge": [[r.at.isoformat(), r.pct] for r in gauge],
               "reserve_pct": config.RESERVE_PCT, "stop_reached_mi": config.STOP_REACHED_MI,
               "habit": asdict(habit) if habit else None, "habit_days": config.HABIT_DAYS,
               "habit_plan": _plain(simulated) if simulated else None,
               "compare": _comparison(saved, simulated, driven, gauge, end_price)}
    _trips[plan_id] = (time.monotonic(), payload)
    return payload


# The Drivers view: each driver's fueling habits over the last HABIT_DAYS days (pilot trucks' drivers marked), and
# every stop's gauge before and after, for the charts.
def drivers_payload() -> dict:
    with db.connect() as conn:
        stops = db.fuel_stops(conn)
        pilot_units = {t.unit for t in db.pilot(conn)}
    found = habits.habits(stops, config.RAN_LOW_PCT, config.TOP_OFF_GAL)
    return {"days": config.HABIT_DAYS, "low_pct": config.RAN_LOW_PCT, "top_off_gal": config.TOP_OFF_GAL,
            "habits": [asdict(h) | {"pilot": h.unit in pilot_units} for h in found],
            "stops": [[s.gauge_before, s.gauge_after, s.loves] for s in stops if s.gauge_before is not None]}


# The habit of the driver now on a truck (the first, for a team), or None when they have no recent stops.
def _driver_habit(conn, unit: str) -> DriverHabit | None:
    ids = {d.driver_id for d in db.dt_drivers(conn) if d.unit == unit and d.employee_status == "active"}
    found = habits.habits([s for s in db.fuel_stops(conn) if s.driver_id in ids], config.RAN_LOW_PCT, config.TOP_OFF_GAL)
    return found[0] if found else None


# The driver's habit simulated on the plan's road, with the plan's start, tank, MPG and Love's; None without a habit.
def _simulate(saved: dict, habit: DriverHabit | None) -> FuelPlan | None:
    if habit is None:
        return None
    stores = [StoreOnRoute(store=Store(**c["store"]), miles=c["miles"], off_mi=c["off_mi"]) for c in saved["candidates"]]
    truck = saved["truck"]
    return habits.simulate(habit, truck["fuel_pct"], truck["tank_gal"], saved["mpg"], saved["route_mi"], stores)


# The money of one load: the plan, the driver's habit simulated on the same road, and what really happened, each at
# the pump price, what the company was billed after Love's discount, and (real purchases) what the drivers' cards
# charged them; then how much more the habit and the real trip cost the company than the plan. The real purchases
# show as they come in; the fuel left at the end, and so the real trip's extra cost, once the load is finished, so a
# half-done trip isn't set against whole ones.
def _comparison(saved: dict, simulated: FuelPlan | None, driven: Trip, gauge: list[FuelReading],
                end_price: float) -> dict:
    planned = compare.from_plan(_fuel_plan(saved["plan"])) if saved["plan"] else None
    habit = compare.from_plan(simulated) if simulated else None
    end_gal = gauge[-1].pct / 100 * saved["truck"]["tank_gal"] if driven.finished_at and gauge else None
    actual = compare.from_fills(list(driven.fills), end_gal)
    return {"end_price": end_price, "finished": driven.finished_at is not None,
            "plan": asdict(planned) if planned else None, "habit": asdict(habit) if habit else None,
            "actual": asdict(actual),
            "habit_extra": compare.extra_cost(habit, planned, end_price) if habit and planned else None,
            "actual_extra": compare.extra_cost(actual, planned, end_price) if planned and end_gal is not None else None}


# A saved plan's stops (JSON) back as a FuelPlan.
def _fuel_plan(plan: dict) -> FuelPlan:
    stops = tuple(PlanStop(**{**s, "store": Store(**s["store"])}) for s in plan["stops"])
    return FuelPlan(stops=stops, end_gal=plan["end_gal"], fuel_cost=plan["fuel_cost"])


# A plan in a few figures for the list: its load, where it goes, when it was made, and its stops and cost.
def _summary(p: dict) -> dict:
    end, plan = p["stops_ahead"][-1], p["plan"]
    return {"plan_id": p["plan_id"], "made_at": p["made_at"], "load_id": p["order"]["load_id"],
            "to": f"{end['city']}, {end['state']}", "route_mi": p["route_mi"],
            "stops": len(plan["stops"]) if plan else None, "cost": plan["fuel_cost"] if plan else None}


# A dataclass as plain JSON-ready values (datetimes become ISO text).
def _plain(obj) -> dict:
    return json.loads(json.dumps(asdict(obj), default=lambda value: value.isoformat()))


# Every refreshed table with its row count and last refresh time.
def _sources(conn) -> list[dict]:
    return [{"table": t, "rows": n, "refreshed": at} for t, n, at in db.status(conn)]
