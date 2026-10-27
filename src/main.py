# Command line entry point: `python src/main.py <command>`. Each command runs one job or one tool.
import argparse
import logging
import sys
from datetime import datetime, timezone
from itertools import groupby

import config
import db
import server
from core import loads, message
from jobs import (driver_habits, estimate_tanks, load_prices, plan_loads, refresh_fuel, refresh_live, refresh_market,
                  refresh_orders, sync_registry)
from models import Order
from sources import telegram

HOLES_SHOWN = 10    # items listed per hole unless --all


# Sends log lines to the console and to data/fuel.log; library chatter is kept to warnings.
def setup_logging() -> None:
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.LOG_PATH, encoding="utf-8")],
    )
    for noisy in ("httpx", "telethon"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# Argument type: the word "none" means "clear this setting", anything else is converted with `cast`.
def or_none(cast):
    return lambda text: None if text.lower() == "none" else cast(text)


# Formats an optional value for printing: "-" when empty, whole ids as-is, decimals to one place.
def show(value) -> str:
    if value is None:
        return "-"
    return f"{round(value, 1):g}" if isinstance(value, float) else str(value)


# Says roughly how long ago a moment was ("5 min ago", "3 h ago", "2 d ago"); "never" when there is none.
def ago(moment: datetime | None) -> str:
    if moment is None:
        return "never"
    minutes = int((datetime.now(timezone.utc) - moment).total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min ago"
    return f"{minutes // 60} h ago" if minutes < 48 * 60 else f"{minutes // (24 * 60)} d ago"


# One line for a load: its id, status, and its first and last stop.
def load_line(order: Order | None) -> str:
    if order is None:
        return "no active load"
    route = f"{order.stops[0].city}, {order.stops[0].state} -> {order.stops[-1].city}, {order.stops[-1].state}" \
        if order.stops else "no stops"
    return f"{order.load_id} ({order.status}): {route}"


# Creates data/fuel.db with all tables. Safe to run again: existing data is kept.
def cmd_init_db(args) -> None:
    with db.connect():
        pass
    print(f"Database ready: {config.DB_PATH}")


# Refreshes Samsara, Datatruck and Telegram copies and relinks trucks.
def cmd_sync(args) -> None:
    linked = sync_registry.run()
    print(f"{linked} trucks linked. Next: `holes` to see what didn't link, `fleet` for the list.")


# Loads the newest Love's price sheet.
def cmd_prices(args) -> None:
    load_prices.run()


# Copies the active Datatruck orders and their stops.
def cmd_orders(args) -> None:
    refresh_orders.run()


# Copies every Datatruck fuel line and fuel card.
def cmd_fuel(args) -> None:
    refresh_fuel.run()


# Copies the U.S. EIA weekly retail diesel prices by region, the yardstick for what we pay.
def cmd_market(args) -> None:
    refresh_market.run()


# Copies every truck's latest Samsara position and fuel level.
def cmd_live(args) -> None:
    refresh_live.run()


# Estimates the pilot trucks' tank sizes from their recent fill-ups and the Samsara fuel gauge.
def cmd_tanks(args) -> None:
    estimate_tanks.run()
    print("See the tank sizes with `pilot`; a truck without one is listed in `holes`.")


# Runs the dashboard in the browser at http://127.0.0.1:<port>, refreshing its data on a timetable unless told not to.
def cmd_serve(args) -> None:
    server.serve(args.port, refresh=not args.no_refresh)


# Logs Bob's Telegram account in once (you type the code Telegram sends him).
def cmd_login(args) -> None:
    name = telegram.login()
    in_test = config.TEST_CHAT_ID in telegram.member_of([config.TEST_CHAT_ID] if config.TEST_CHAT_ID else [])[1]
    print(f"Logged in as {name}. Member of the test chat: {'yes' if in_test else 'NO - add this account to it'}.")


# Prints each refreshed table with its row count and last refresh time.
def cmd_status(args) -> None:
    with db.connect() as conn:
        rows = db.status(conn)
    print(f"{'TABLE':<18}{'ROWS':>6}  REFRESHED (UTC)")
    for table, count, refreshed in rows:
        print(f"{table:<18}{count:>6}  {refreshed or 'never'}")


# Prints every truck with its Telegram group, where that link comes from, tank size and MPG.
def cmd_fleet(args) -> None:
    with db.connect() as conn:
        trucks = db.fleet(conn)
    print(f"{'UNIT':<10}{'CHAT ID':<18}{'LINK':<8}{'TANK':>6}{'MPG':>6}  NAME")
    for t in trucks:
        print(f"{t.unit:<10}{show(t.chat_id):<18}{t.chat_source or '-':<8}{show(t.tank_gal):>6}{show(t.mpg):>6}  {t.name}")
    print(f"{len(trucks)} trucks, {sum(t.chat_id is None for t in trucks)} without a Telegram group")


# Prints every data gap, grouped by kind, with a count and the first items of each.
def cmd_holes(args) -> None:
    with db.connect() as conn:
        rows = db.holes(conn)
    for hole, items in groupby(rows, key=lambda r: r["hole"]):  # rows come sorted by hole
        items = list(items)
        print(f"\n{hole}: {len(items)}")
        for r in items if args.all else items[:HOLES_SHOWN]:
            print(f"    {r['item']}  —  {show(r['detail'])}")
        if not args.all and len(items) > HOLES_SHOWN:
            print(f"    ... {len(items) - HOLES_SHOWN} more (use --all)")
    print(f"\n{len(rows)} holes in total")


# Prints each pilot truck as one block: driver, fuel and where, tank, MPG, Telegram group and current load.
def cmd_pilot(args) -> None:
    with db.connect() as conn:
        trucks = db.pilot(conn)
        orders = db.orders(conn)
    for t in trucks:
        tank_source = f"auto, from {t.tank_fills} fill-ups" if t.tank_source == "auto" else t.tank_source or "missing"
        print(f"\n{t.unit}  {t.driver or 'no active driver'}")
        print(f"    fuel  {show(t.fuel_pct)}% ({ago(t.fuel_at)})   at {t.place or '-'} ({ago(t.gps_at)})")
        print(f"    tank  {show(t.tank_gal)} gal ({tank_source})   MPG {show(t.mpg)}   "
              f"chat {show(t.chat_id)} ({t.chat_source or 'missing'})")
        print(f"    load  {load_line(loads.current_order([o for o in orders if o.unit == t.unit]))}")
    print(f"\n{len(trucks)} pilot trucks. Add one with `pilot-add <unit>`; gaps are listed in `holes`.")


# Dry run: plans one pilot truck's current load and prints the plan. Sends nothing, saves nothing.
def cmd_plan(args) -> None:
    print(message.first_text(plan_loads.plan_for(args.unit, args.via)))


# Starts a truck's current load over with a fresh plan of the road ahead and sends it (see plan_loads.restart).
def cmd_restart(args) -> None:
    fresh = plan_loads.restart(args.unit, args.via)
    print(f"Unit {args.unit} has a fresh plan for the rest of load {fresh.order.load_id}, sent to its chats:")
    print(message.first_text(fresh))


# Collects every driver's fuel stops of the last days with the Samsara gauge around them; the Drivers tab shows them.
def cmd_habits(args) -> None:
    driver_habits.run()
    print("See every driver's habits on the dashboard's Drivers tab.")


# Plans every pilot truck's load that has no plan yet, saves the plans and sends them to the test chat; the Plans
# tab shows them.
def cmd_plans(args) -> None:
    print(f"{plan_loads.run()} new plans saved. See them on the dashboard's Plans tab.")


# Adds a truck to the pilot, with an optional note.
def cmd_pilot_add(args) -> None:
    with db.connect() as conn:
        db.add_pilot(conn, args.unit, " ".join(args.note) or None)
    print(f"Unit {args.unit} is in the pilot. Next: `tanks` to estimate its tank, then `pilot` to check it.")


# Takes a truck out of the pilot.
def cmd_pilot_remove(args) -> None:
    with db.connect() as conn:
        db.remove_pilot(conn, args.unit)
    print(f"Unit {args.unit} is out of the pilot.")


# Lists the Telegram groups whose title contains a text, with the chat id that `set-chat` needs.
def cmd_groups(args) -> None:
    with db.connect() as conn:
        groups = db.find_groups(conn, args.text)
    for g in groups:
        print(f"{g.chat_id:<18}{g.title}")
    print(f"{len(groups)} groups contain '{args.text}'")


# Sets a pilot truck's Telegram group (beats the auto-match); "none" goes back to the auto-match.
def cmd_set_chat(args) -> None:
    with db.connect() as conn:
        db.set_chat(conn, args.unit, args.chat_id)
    print(f"Unit {args.unit}: manual chat = {show(args.chat_id)}")


# Sets a pilot truck's tank size in gallons (beats the tank helper); "none" goes back to the helper's estimate.
def cmd_set_tank(args) -> None:
    with db.connect() as conn:
        db.set_tank(conn, args.unit, args.tank_gal)
    print(f"Unit {args.unit}: tank = {show(args.tank_gal)} gal")


# Builds the command line, then runs the chosen command. Expected user mistakes print a short message.
def main() -> None:
    parser = argparse.ArgumentParser(description="Fuel assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the database").set_defaults(run=cmd_init_db)
    sub.add_parser("sync", help="refresh Samsara, Datatruck, Telegram and relink trucks").set_defaults(run=cmd_sync)
    sub.add_parser("prices", help="load the newest Love's price sheet").set_defaults(run=cmd_prices)
    sub.add_parser("orders", help="copy active Datatruck orders").set_defaults(run=cmd_orders)
    sub.add_parser("fuel", help="copy every Datatruck fuel line and fuel card").set_defaults(run=cmd_fuel)
    sub.add_parser("market", help="copy the EIA weekly diesel prices by region").set_defaults(run=cmd_market)
    sub.add_parser("live", help="copy every truck's latest Samsara position and fuel level").set_defaults(run=cmd_live)
    sub.add_parser("tanks", help="estimate the pilot trucks' tank sizes from fill-ups").set_defaults(run=cmd_tanks)
    p = sub.add_parser("serve", help="run the dashboard in the browser")
    p.add_argument("--port", type=int, default=config.DASHBOARD_PORT)
    p.add_argument("--no-refresh", action="store_true", help="only show the data; don't refresh it automatically")
    p.set_defaults(run=cmd_serve)
    sub.add_parser("login", help="log Bob's Telegram account in (once)").set_defaults(run=cmd_login)
    sub.add_parser("status", help="row counts and refresh times").set_defaults(run=cmd_status)
    sub.add_parser("fleet", help="list trucks and their links").set_defaults(run=cmd_fleet)

    p = sub.add_parser("holes", help="list everything that doesn't link up")
    p.add_argument("--all", action="store_true", help="list every item, not just the first ones")
    p.set_defaults(run=cmd_holes)

    sub.add_parser("pilot", help="show the pilot trucks with everything known about them").set_defaults(run=cmd_pilot)

    via = "the driver's own route: a Love's store number (e.g. 372) or lat,lng the road must go through"
    p = sub.add_parser("plan", help="plan a pilot truck's current load and print it (sends nothing)")
    p.add_argument("unit")
    p.add_argument("--via", help=via)
    p.set_defaults(run=cmd_plan)
    p = sub.add_parser("restart", help="start a truck's current load over with a fresh plan, and send it")
    p.add_argument("unit")
    p.add_argument("--via", help=via)
    p.set_defaults(run=cmd_restart)
    sub.add_parser("plans", help="plan and save every pilot load without a plan, send them to the test chat").set_defaults(run=cmd_plans)
    sub.add_parser("habits", help="collect every driver's fuel stops with the gauge (a few minutes)").set_defaults(run=cmd_habits)

    p = sub.add_parser("pilot-add", help="add a truck to the pilot")
    p.add_argument("unit")
    p.add_argument("note", nargs="*", help="optional note, e.g. why this truck")
    p.set_defaults(run=cmd_pilot_add)

    p = sub.add_parser("pilot-remove", help="take a truck out of the pilot")
    p.add_argument("unit")
    p.set_defaults(run=cmd_pilot_remove)

    p = sub.add_parser("groups", help="find Telegram groups by title, with their chat ids")
    p.add_argument("text", help="text in the title, e.g. a unit number or driver name")
    p.set_defaults(run=cmd_groups)

    p = sub.add_parser("set-chat", help="set a pilot truck's Telegram group")
    p.add_argument("unit")
    p.add_argument("chat_id", type=or_none(int), help="Telegram chat id, or 'none' for the auto-match")
    p.set_defaults(run=cmd_set_chat)

    p = sub.add_parser("set-tank", help="set a pilot truck's tank size")
    p.add_argument("unit")
    p.add_argument("tank_gal", type=or_none(float), help="gallons, or 'none' for the tank helper's estimate")
    p.set_defaults(run=cmd_set_tank)

    args = parser.parse_args()
    setup_logging()
    try:
        args.run(args)
    except (LookupError, RuntimeError) as error:  # e.g. unknown unit, missing .env key: something you can fix
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
