# Planner job: plans each pilot truck's load once and saves the plan, then follows it: a full message to the test
# chat when the plan is made and at each major event (a stop reached, fuel bought, a stop missed), re-planning the
# rest of the road when the driver goes off plan. Truck, loads, prices and fuel lines come from the DB, where the
# truck has been from Samsara, the road from Google.
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import config
import db
from core import follow, geo, loads, message, planner, route, trip
from models import FuelLine, LoadPlan, Order, PlanRules, Progress, Stop, Store, StoreOnRoute, TrackPoint, Truck
from sources import google_places, google_routes, samsara, telegram

log = logging.getLogger(__name__)

RULES = PlanRules(reserve_pct=config.RESERVE_PCT, min_buy_gal=config.MIN_BUY_GAL, stop_cost=config.STOP_COST_USD,
                  step_gal=config.FUEL_STEP_GAL, default_mpg=config.DEFAULT_MPG, mpg_range=config.MPG_RANGE,
                  end_min_gal=config.END_MIN_GAL, detour_factor=config.DETOUR_FACTOR,
                  switch_cost=config.SWITCH_COST_USD)
FILL_WINDOW = timedelta(minutes=config.TANK_WINDOW_MIN)  # purchases this close together are one stop


# For every pilot truck: first follows its plan in progress (what happened since the last look, see _follow), then
# plans its load (the one with stops still ahead) if that has no plan yet, saving the plan with its first message
# queued for its chats (_chats). The followed plan decides when its load ends, in road order: while it hasn't and
# Datatruck still has that load open, the next load waits. Then sends what is queued. One truck failing doesn't stop
# the others. Returns how many plans were saved.
def run() -> int:
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        trucks = db.pilot(conn)
        orders = db.orders(conn)
        stores = db.stores(conn)
        done = db.planned_loads(conn)
        followed = {p.truck.unit: (plan_id, p, prog)
                    for plan_id, p, prog in db.followed(conn, now - timedelta(days=config.FOLLOW_DAYS))
                    if not follow.finished(prog)}
        since = min([p.made_at for _, p, _ in followed.values()], default=now) - timedelta(days=1)
        lines = db.fuel_lines(conn, since_day=since.date().isoformat())
    open_orders = {o.order_id for o in orders}
    saved = 0
    for truck in trucks:
        try:
            own = [o for o in orders if o.unit == truck.unit]
            current = followed.get(truck.unit)
            track = _track(truck, own, current[1] if current else None, now)
            if current:
                prog = _follow(truck, *current, track, [l for l in lines if l.unit == truck.unit], stores, now)
                if not follow.finished(prog) and current[1].order.order_id in open_orders:
                    continue
            found = _next_load(own, track, now)
            if found is None or (truck.unit, found[0].order_id) in done:
                continue
            p = _plan(truck, *found, stores)
            with db.connect() as conn:  # plan, progress and first messages together
                plan_id = db.save_plan(conn, p)
                if _chats(truck):
                    db.save_progress(conn, plan_id, follow.start(p))
                for chat in _chats(truck):
                    db.queue_message(conn, plan_id, chat, message.first_text(p), db.now())
            saved += 1
            log.info("Planned unit %s load %s: %s", truck.unit, p.order.load_id,
                     f"{len(p.plan.stops)} stops" if p.plan else "no plan")
        except LookupError as missing:  # e.g. no fuel reading: shows in `holes`, nothing to retry until it's fixed
            log.warning("Unit %s not planned: %s", truck.unit, missing)
        except Exception:
            log.exception("Planning unit %s failed", truck.unit)
    _send_queued()
    return saved


# Starts a truck's current load over with a fresh plan of the road still ahead, from where it is now, and follows
# that one instead; its first message goes to the truck's chats (_chats). For a truck that goes live mid-load: its
# driver starts with a plan of the road ahead, not with the messages of the plan made before (those stay in the test
# chat, the old plan on the Plans tab). `via` is where the driver's own route goes, when it isn't Google's (a Love's
# store number, or "lat,lng"): the road goes through it, re-plans too, until the truck is past it. Raises LookupError
# when the truck has no load in progress being followed.
def restart(unit: str, via: str | None = None) -> LoadPlan:
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        truck = next((t for t in db.pilot(conn) if t.unit == unit), None)
        current = next(((i, p, g) for i, p, g in db.followed(conn, now - timedelta(days=config.FOLLOW_DAYS))
                        if p.truck.unit == unit), None)
        stores = db.stores(conn)
        lines = db.fuel_lines(conn, since_day=(now - timedelta(days=config.FOLLOW_DAYS + 1)).date().isoformat())
    if truck is None or current is None:
        raise LookupError(f"Unit {unit} has no load being followed to start over (see the Plans tab).")
    _, p, prog = current
    track = samsara.gps_history(truck.samsara_id, p.made_at, now)
    fills = trip.trip(p.made_at, track, [l for l in lines if l.unit == unit], [(w.lat, w.lng) for w in prog.planned],
                      None, config.STOP_REACHED_MI, FILL_WINDOW, config.TRACK_STEP_MI).fills
    after, _ = follow.look(prog, track, list(fills), now, config.STOP_REACHED_MI, config.ROUTE_STEP_MI,
                           timedelta(minutes=config.MISSED_AFTER_MIN))
    ahead = follow.stops_left(after)
    if not ahead:
        raise LookupError(f"Unit {unit} has reached the last stop of its load: its next load gets a plan of its own.")
    fresh = _plan(truck, p.order, ahead, stores, via=(_place(via, stores),) if via else ())
    with db.connect() as conn:  # the fresh plan becomes the truck's newest, so it is the one followed
        plan_id = db.save_plan(conn, fresh)
        db.save_progress(conn, plan_id, follow.start(fresh))
        for chat in _chats(truck):
            db.queue_message(conn, plan_id, chat, message.first_text(fresh), db.now())
    _send_queued()
    return fresh


# A place as typed for `restart --via`: a Love's store number ("372") or "lat,lng". Raises LookupError for neither.
def _place(text: str, stores: list[Store]) -> geo.Point:
    if "," in text:
        lat, lng = (float(part) for part in text.split(","))
        return lat, lng
    store = next((s for s in stores if s.store_no == text.strip().lstrip("#")), None)
    if store is None:
        raise LookupError(f"'{text}' is neither a Love's store number on the price sheet nor 'lat,lng'.")
    return store.lat, store.lng


# Dry run: plans one pilot truck's load without saving it, through `via` if given (see restart). Raises LookupError
# saying what is missing.
def plan_for(unit: str, via: str | None = None) -> LoadPlan:
    with db.connect() as conn:
        truck = next((t for t in db.pilot(conn) if t.unit == unit), None)
        orders = [o for o in db.orders(conn) if o.unit == unit]
        stores = db.stores(conn)
    if truck is None:
        raise LookupError(f"Unit '{unit}' is not in the pilot. See the list with `pilot`.")
    now = datetime.now(timezone.utc)
    found = _next_load(orders, _track(truck, orders, None, now), now)
    if found is None:
        raise LookupError(f"Unit {unit} has no load with a stop still ahead (no active load, or it looks finished).")
    return _plan(truck, *found, stores, via=(_place(via, stores),) if via else ())


# The truck's GPS track from the earliest moment anything needs it: the start of its plan in progress, or a visit
# to one of its loads' stops (from VISIT_WINDOW_H before the pickup). Empty while that is still ahead.
def _track(truck: Truck, orders: list[Order], current: LoadPlan | None, now: datetime) -> list[TrackPoint]:
    window = timedelta(hours=config.VISIT_WINDOW_H)
    since = min([loads.visits_from(o, window, now) for o in orders] + ([current.made_at] if current else []), default=now)
    return samsara.gps_history(truck.samsara_id, since, now) if since < now else []


# The truck's load with stops still ahead (see core/loads.next_load), judged from its GPS track. None when it has
# no such load.
def _next_load(orders: list[Order], track: list[TrackPoint], now: datetime) -> tuple[Order, list[Stop]] | None:
    if not orders:
        return None
    return loads.next_load(orders, track, config.STOP_REACHED_MI, timedelta(hours=config.VISIT_WINDOW_H), now)


# The chats a truck's plan messages go to: the test chat, and the truck's own group once it is live (LIVE_UNITS).
def _chats(truck: Truck) -> list[int]:
    chats = [config.TEST_CHAT_ID] if config.TEST_CHAT_ID else []
    if truck.unit in config.LIVE_UNITS and truck.chat_id:
        chats.append(truck.chat_id)
    return chats


# Looks at what the truck did since the last look at plan `p` (core/follow): a pickup or delivery reached, fuel
# bought, a planned stop missed (15 min after leaving it when the gauge shows no fill, else an hour without a fuel
# line; the gauge history is fetched only while such a stop is open). When the driver went off plan, or the road
# ahead no longer fits the fuel on board, the rest of the road is re-planned from where the truck is; if that fails
# (e.g. Google unreachable), the events are
# told anyway and the safety check tries again next run. Each look with events queues one full message per chat; a
# stop passed with nothing to tell yet (its fuel line not in) only moves the newest message's link on, so it never
# leads back. Returns the progress after the look.
def _follow(truck: Truck, plan_id: int, p: LoadPlan, prog: Progress, track: list[TrackPoint], lines: list[FuelLine],
            stores: list[Store], now: datetime) -> Progress:
    fills = trip.trip(p.made_at, track, lines, [(w.lat, w.lng) for w in prog.planned], None,
                      config.STOP_REACHED_MI, FILL_WINDOW, config.TRACK_STEP_MI).fills
    # a planned stop just passed with nothing told yet: its gauge readings tell sooner than a fuel line whether it filled
    since = follow.open_since(prog, track, config.STOP_REACHED_MI, config.ROUTE_STEP_MI)
    gauge = samsara.fuel_history(truck.samsara_id, since - FILL_WINDOW, now) if since else []
    after, new = follow.look(prog, track, list(fills), now, config.STOP_REACHED_MI, config.ROUTE_STEP_MI,
                             timedelta(minutes=config.MISSED_AFTER_MIN), gauge,
                             timedelta(minutes=config.MISSED_QUICK_MIN), config.GAUGE_RISE_PCT)
    fuel = follow.fuel_now(p, track, after.events, truck.fuel_pct, truck.fuel_at, now, FILL_WINDOW,
                           timedelta(minutes=config.GAUGE_FRESH_MIN), config.PLAN_LINE_STEP_MI)
    tank = p.truck.tank_gal
    reserve = tank * config.RESERVE_PCT / 100
    # margin: half the reserve, since plans often arrive right at the reserve and the gauge wobbles a few gallons
    went_off = follow.off_plan(new)
    if follow.stops_left(after) and (went_off or follow.needs_replan(
            after, fuel, _here(after, track, truck), reserve, tank, reserve / 2, now,
            timedelta(minutes=config.REPLAN_GAP_MIN))):
        try:
            moved = replace(truck, fuel_pct=fuel / tank * 100, tank_gal=tank)  # where Samsara has it now
            # keeps the Love's already told when they still work, with new amounts (see planner.plan), and the
            # driver's own route where it still goes
            via = follow.via_ahead(after.road, _here(after, track, truck), config.STOP_REACHED_MI)
            road = _plan(moved, p.order, follow.stops_left(after), stores, follow.stores_ahead(after), via)
            if not went_off and follow.same_stops(after, road):
                after = replace(after, road=road, passed=0)  # same Love's, amounts updated: nothing new to tell
            else:
                after, more = follow.replanned(after, road, now)
                new += more
        except Exception:
            log.warning("Re-planning plan %s (unit %s) failed", plan_id, truck.unit, exc_info=True)
    if after == prog:
        return after
    newest = []
    with db.connect() as conn:
        chats = db.plan_chats(conn, plan_id)  # where its first message went (see db.plan_chats)
        db.save_progress(conn, plan_id, after)
        if new:
            text = message.plan_text(p, after, new, fuel, _here(after, track, truck))
            for chat in chats:
                db.queue_message(conn, plan_id, chat, text, db.now())
        else:
            newest = [m for m in (db.last_sent(conn, plan_id, chat) for chat in chats) if m]
    for sent in newest:  # a stop passed, nothing to tell: the link skips it
        moved_on = message.with_link(sent[3], after)
        if moved_on != sent[3]:
            _relink(*sent, moved_on)
    log.info("Followed plan %s (unit %s): %s", plan_id, truck.unit, ", ".join(e.kind for e in new) or "stop passed")
    return after


# How far along the road in force the truck is now: its last GPS point (or Samsara's latest position), looked for
# from the last waypoint it passed on.
def _here(prog: Progress, track: list[TrackPoint], truck: Truck) -> float:
    passed = route.waypoints(prog.road)[:prog.passed]
    where = (track[-1].lat, track[-1].lng) if track else (truck.lat, truck.lng)
    return route.mile_of(prog.road, where, passed[-1].miles if passed else 0.0)


# Puts a sent message's text with its link moved on. A failure (e.g. a message another account sent) only leaves
# the old link in place, so it is logged and skipped.
def _relink(message_no: int, chat_id: int, message_id: int, text: str, moved_on: str) -> None:
    try:
        telegram.edit(chat_id, message_id, moved_on)
    except Exception:
        log.warning("Could not move the link of message %s on", message_no, exc_info=True)
        return
    with db.connect() as conn:
        db.set_text(conn, message_no, moved_on)


# Sends each queued message written less than SEND_WITHIN_MIN ago, oldest first, and records it as sent; then the
# truck's previous message in that chat gets "Newer update below" instead of its link, so only the newest one leads
# anywhere. A send that fails stays queued for the next run, and the plan's later messages to that chat wait with it,
# so they go out in order; one older than SEND_WITHIN_MIN is left unsent, since the truck has moved on.
def _send_queued() -> None:
    since = datetime.now(timezone.utc) - timedelta(minutes=config.SEND_WITHIN_MIN)
    with db.connect() as conn:
        queued = db.unsent_messages(conn, since)
    held = set()  # (plan_id, chat_id) whose earlier message failed this run
    for message_no, plan_id, chat_id, text in queued:
        if (plan_id, chat_id) in held:
            continue
        try:
            message_id = telegram.send(chat_id, text)
        except Exception:  # e.g. Telegram unreachable: the next run tries again
            log.exception("Sending a message of plan %s to chat %s failed", plan_id, chat_id)
            held.add((plan_id, chat_id))
            continue
        with db.connect() as conn:
            db.mark_sent(conn, message_no, message_id, db.now())
            older = db.last_sent(conn, plan_id, chat_id, before=message_no)
        log.info("Sent a message of plan %s to chat %s", plan_id, chat_id)
        if older:
            _supersede(*older)


# Replaces an older message's link with "Newer update below". A failure (e.g. too old to edit) only leaves the old
# link in place, so it is logged and skipped.
def _supersede(message_no: int, chat_id: int, message_id: int, text: str) -> None:
    try:
        telegram.edit(chat_id, message_id, message.superseded(text))
    except Exception:
        log.warning("Could not take the link off message %s", message_no, exc_info=True)
        return
    with db.connect() as conn:
        db.set_text(conn, message_no, message.superseded(text))


# Plans one load from where the truck is now: Google's road through the stops ahead, the Love's along it, and the
# cheapest plan; on a re-plan, `keep` are the Love's the driver was told about (see planner.plan). The road goes
# through `via` first, the driver's own route where it isn't Google's (see restart). When no plan of
# Love's keeps the reserve (none in reach of the fuel on board), the truck stops near the truck are added (_stations):
# the plan then sends the driver to one first, for only what it takes to reach the Love's. Raises LookupError when the
# truck has no tank size, fuel reading or position.
def _plan(truck: Truck, order: Order, ahead: list[Stop], stores: list[Store],
          keep: frozenset[str] = frozenset(), via: tuple[geo.Point, ...] = ()) -> LoadPlan:
    if truck.tank_gal is None or truck.fuel_pct is None or truck.lat is None:
        raise LookupError(f"Unit {truck.unit} has no tank size, fuel reading or position yet. See `holes`.")
    line = google_routes.route([(truck.lat, truck.lng), *via] + [(s.lat, s.lng) for s in ahead])
    route_mi = geo.along(line)[-1]
    mpg = planner.usable_mpg(truck.mpg, RULES)
    candidates = geo.stores_along(line, stores, config.CORRIDOR_MI, config.ROUTE_STEP_MI)
    near_end = geo.nearest(stores, (ahead[-1].lat, ahead[-1].lng))
    fuel_plan = planner.plan(truck.fuel_pct, truck.tank_gal, mpg, route_mi, candidates, near_end.net, RULES, keep)
    if fuel_plan is None:  # truck stops on the road ahead first; other stations selling diesel only if those can't
        truck_stops, others = _stations(truck, line, stores, mpg)
        for extra in (truck_stops, truck_stops + others):
            tried = sorted(candidates + extra, key=lambda c: c.miles)
            fuel_plan = planner.plan(truck.fuel_pct, truck.tank_gal, mpg, route_mi, tried, near_end.net, RULES, keep)
            if fuel_plan:
                candidates = tried
                break
    return LoadPlan(made_at=datetime.now(timezone.utc).replace(microsecond=0), truck=truck, order=order,
                    stops_ahead=tuple(ahead), line=tuple(geo.thin(line, config.PLAN_LINE_STEP_MI)), route_mi=route_mi,
                    candidates=tuple(candidates), mpg=mpg, price_date=max(s.price_date for s in stores),
                    end_price=near_end.net, end_pump=near_end.retail, plan=fuel_plan, via=tuple(via))


# The stations on the road ahead that aren't Love's (Google Places), as candidates within STATION_OFF_MI of it: its
# truck stops, and the other stations selling diesel. Only as far as the first stop can be: the fuel on board down to
# the reserve (or empty, for a truck already under it, as the planner allows). Google gives at most 20 of each, so a
# longer stretch lets a city's many stations crowd out the small town where the truck must fuel (3068, 2026-10-23:
# searched to an empty tank, the Boise area pushed one of Council, ID's two stations off the list one search and the
# other the next). One whose price Google doesn't have counts at the pump price of the Love's
# nearest the truck: about what diesel costs around there, with no discount, so the plan buys there only what it
# must. None when Google can't be asked (logged): the load is then planned with the Love's alone, as before.
def _stations(truck: Truck, line: list[geo.Point], stores: list[Store],
              mpg: float) -> tuple[list[StoreOnRoute], list[StoreOnRoute]]:
    fuel_gal, reserve = truck.fuel_pct / 100 * truck.tank_gal, truck.tank_gal * config.RESERVE_PCT / 100
    reach = (fuel_gal - (reserve if fuel_gal >= reserve else 0.0)) * mpg
    ahead = geo.thin([p for p, mile in zip(line, geo.along(line)) if mile <= reach], config.ROUTE_STEP_MI)
    if len(ahead) < 2:
        return [], []
    try:
        truck_stops, others = google_places.stations_along(ahead)
    except Exception:
        log.warning("Could not look for stations on the road of unit %s", truck.unit, exc_info=True)
        return [], []
    pump = geo.nearest(stores, (truck.lat, truck.lng)).retail

    # each at its own price, or the pump price near the truck; one nearest to the road where the truck is now, more
    # than STOP_REACHED_MI from it, is beside or behind the truck (Lapwai, ID, for 3068 heading east at Spalding)
    def on_road(found: list[Store]) -> list[StoreOnRoute]:
        priced = [s if s.price_date else replace(s, retail=pump, net=pump) for s in found]
        return [c for c in geo.stores_along(line, priced, config.STATION_OFF_MI, config.ROUTE_STEP_MI)
                if c.miles > config.ROUTE_STEP_MI or c.off_mi <= config.STOP_REACHED_MI]
    return on_road(truck_stops), on_road(others)
