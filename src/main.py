# Command line entry point: `python src/main.py <command>`. Each command runs one job or one tool.
import argparse
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from itertools import groupby
from logging.handlers import RotatingFileHandler

import config
import db
import server
from core import loads
from jobs import (driver_habits, estimate_burn, estimate_tanks, fill_lookups, load_prices, read_statements, refresh_fuel,
                  refresh_live, refresh_market, refresh_orders, statement_evidence, store_exits, sync_registry)
from models import EfsCard, EfsCardRow, Order
from sources import efs_cards, efs_chrome, efs_web, telegram
from sources.efs_chrome import EfsError

HOLES_SHOWN = 10    # items listed per hole unless --all


# Sends log lines to the console, and with `to_file` also to data/fuel.log, which starts afresh at LOG_MAX_MB (the old
# ones kept as fuel.log.1, .2, ...). Library chatter is kept to warnings.
def setup_logging(to_file: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(config.LOG_PATH, maxBytes=config.LOG_MAX_MB * 1024 * 1024,
                                            backupCount=config.LOG_FILES_KEPT, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
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


# Reads the Love's price sheets not read before; the newest one's prices are the ones in force.
def cmd_prices(args) -> None:
    load_prices.run()


# Reads the EFS statement PDFs saved in data/efs that were not read before.
def cmd_statements(args) -> None:
    print(f"{read_statements.run()} new EFS statements read from {config.STATEMENTS_DIR}")


# Looks up in Samsara, now and for every truck, what the statements' evidence still lacks (several minutes per statement).
def cmd_evidence(args) -> None:
    print(f"{statement_evidence.run(trucks=None)} fills looked up in Samsara")


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


# Reads the Love's store pages not read yet for their highway and exit (all stores the first time, ~10 min).
def cmd_exits(args) -> None:
    print(f"Kept the highway and exit of {store_exits.run()} Love's stores.")


# Calibrates the pilot trucks' engines as fuel meters.
def cmd_burn(args) -> None:
    estimate_burn.run()
    print("See them on the dashboard's Recommend tab (live MPG).")


# Runs the dashboard in the browser at http://127.0.0.1:<port>, refreshing its data on a timetable unless told not to.
def cmd_serve(args) -> None:
    server.serve(args.port, refresh=not args.no_refresh)


# Logs the assistant's Telegram account (TG_PHONE) in once: you type the code Telegram sends to it.
def cmd_login(args) -> None:
    name = telegram.login()
    print(f"Logged in as {name}.")


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


# Collects every driver's fuel stops of the last days with the Samsara gauge around them; the Drivers tab shows them.
def cmd_habits(args) -> None:
    driver_habits.run()
    print("See every driver's habits on the dashboard's Drivers tab.")


# Looks up the fills not looked up yet: where the truck was (outside Love's) and the gauge before; the Live view's
# outside list uses them.
def cmd_lookups(args) -> None:
    fill_lookups.run()
    print("See them on the dashboard's Live tab.")


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


# Opens the eManager window and keeps its login alive until Ctrl+C. eManager still ends every login after 24 hours.
def cmd_efs_login(args) -> None:
    efs_chrome.start()
    print("The eManager window is open. Log in there; this keeps the login alive. Ctrl+C stops it.", flush=True)
    was = None
    try:
        while True:
            alive, said = efs_login_status()
            if said != was:
                print(f"{datetime.now():%H:%M} {said}", flush=True)
                was = said
            # ask often while waiting for the login, then well inside the 90-minute idle logout
            time.sleep(config.EMANAGER_HEARTBEAT_SECONDS if alive else 5)
    except KeyboardInterrupt:
        print("Stopped. The window stays open; without this, eManager logs out after 90 idle minutes.")


# One heartbeat: whether eManager has someone logged in, and who, or why not. A page still loading or changing (the
# login itself) fails the heartbeat for a moment; the next try sees how it ended.
def efs_login_status() -> tuple[bool, str]:
    try:
        if efs_web.heartbeat():
            return True, f"logged in as {efs_web.logged_in()}"
        return False, "not logged in: log in in the window"
    except EfsError as error:
        return False, f"not logged in yet ({error})"


# Logs the card agent's own Telegram login in, once (the same account as the assistant, a second login): you type the
# code Telegram sends to the account's app.
def cmd_agent_login(args) -> None:
    from sources import telegram_agent
    print(f"Card agent logged in as {telegram_agent.login()}.")


# Runs the card agent until stopped (jobs/card_agent), with its own log file data/agent.log (only `serve` writes
# fuel.log). run_agent.bat starts it again if it stops.
def cmd_card_agent(args) -> None:
    from jobs import card_agent
    handler = RotatingFileHandler(config.DATA_DIR / "agent.log", maxBytes=config.LOG_MAX_MB * 1024 * 1024,
                                  backupCount=config.LOG_FILES_KEPT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger(__name__).info("Card agent starting (acts: %s)", config.AGENT_ACT)
    card_agent.run()


# Lists one account's cards the way Card Lookup finds them, and a card's own page when exactly one is found. Read only.
def cmd_efs_cards(args) -> None:
    found = efs_cards.cards(args.account, args.by, args.text)
    for row in found:
        print(card_line(row))
    statuses = Counter(row.status for row in found).most_common()
    print(f"{len(found)} cards: " + ", ".join(f"{count} {status}" for status, count in statuses))
    if len(found) == 1:
        print_card(efs_cards.card(args.account, found[0]))


# Changes one card: its status, an override, taking the override off, or one prompt. Shows the card and the change
# first; only --send makes it, and then shows the card as eManager has it afterwards.
def cmd_efs_card(args) -> None:
    found = efs_cards.cards(args.account, args.by, args.text)
    if args.by == "unit":
        # Card Lookup may also list units that only start with the text: 318 finds 3189
        found = [row for row in found if row.unit.strip() == args.text.strip()]
    if len(found) != 1:
        raise LookupError(f"{len(found)} cards found by {args.by} {args.text!r}; a change needs exactly one. "
                          "List them with efs-cards, then search by what only that card has.")
    row = found[0]
    print(card_line(row))
    print_card(efs_cards.card(args.account, row))
    words, make = card_change(args, row)
    if not args.send:
        print(f"Would {words}. Nothing changed; add --send to do it.")
        return
    after = make()
    print(f"Done: {words}. eManager now shows:")
    print_card(after)


# The change efs-card was asked for: in words, and the call that makes it.
def card_change(args, row: EfsCardRow):
    if args.status:
        return f"set the status to {args.status}", lambda: efs_cards.set_status(args.account, row, args.status)
    if args.remove_override:
        return "remove the override", lambda: efs_cards.remove_override(args.account, row)
    if args.set:
        prompt, value = args.set
        return f"set {prompt} to {value!r}", lambda: efs_cards.set_prompt(args.account, row, prompt, value)
    words = f"override for {args.override} transaction(s), all locations" + (", hand enter" if args.hand_enter else "")
    return words, lambda: efs_cards.set_override(args.account, row, args.override, args.hand_enter)


# One Card Lookup row on one line.
def card_line(row: EfsCardRow) -> str:
    return (f"{row.number}  id {row.card_id}  policy {row.policy}  unit {row.unit or '-':>7}  "
            f"driver id {row.driver_id or '-':>7}  {row.driver_name or '-':28}  {row.status}")


# A card's own page: its settings on one line, then its prompts.
def print_card(card: EfsCard) -> None:
    print(f"   status {card.status} | override {'ON' if card.override else 'off'} | hand enter {card.hand_enter} | "
          f"info source {card.info_source} | mobile {card.mobile} | expires {card.expires} | "
          f"last used {card.last_used or '-'}")
    for prompt, validation, value in card.prompts:
        print(f"   {prompt}: {value} ({validation})")


# The card lookup that efs-cards and efs-card share: which account, what to look up by, and what to look up.
def add_card_lookup(p: argparse.ArgumentParser, default_by: str) -> None:
    p.add_argument("account", choices=sorted(config.EMANAGER_USERS), help="which EFS account")
    p.add_argument("--by", choices=["all", *efs_cards.LOOKUPS], default=default_by,
                   help=f"what to look up by (default {default_by})")
    p.add_argument("text", nargs="?", default="", help="what to look up, e.g. a unit number")


# Builds the command line, then runs the chosen command. Expected user mistakes print a short message.
def main() -> None:
    parser = argparse.ArgumentParser(description="Fuel assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the database").set_defaults(run=cmd_init_db)
    sub.add_parser("sync", help="refresh Samsara, Datatruck, Telegram and relink trucks").set_defaults(run=cmd_sync)
    sub.add_parser("prices", help="read new Love's price sheets (the newest is in force)").set_defaults(run=cmd_prices)
    sub.add_parser("statements", help="read new EFS statement PDFs saved in data/efs").set_defaults(run=cmd_statements)
    sub.add_parser("evidence", help="look up the statements' fuel used and fill evidence in Samsara now, every truck").set_defaults(run=cmd_evidence)
    sub.add_parser("orders", help="copy active Datatruck orders").set_defaults(run=cmd_orders)
    sub.add_parser("fuel", help="copy every Datatruck fuel line and fuel card").set_defaults(run=cmd_fuel)
    sub.add_parser("market", help="copy the EIA weekly diesel prices by region").set_defaults(run=cmd_market)
    sub.add_parser("live", help="copy every truck's latest Samsara position and fuel level").set_defaults(run=cmd_live)
    sub.add_parser("tanks", help="estimate the pilot trucks' tank sizes from fill-ups").set_defaults(run=cmd_tanks)
    sub.add_parser("burn", help="calibrate the pilot trucks' engines as fuel meters").set_defaults(run=cmd_burn)
    sub.add_parser("exits", help="read the highway and exit of Love's stores from their own pages").set_defaults(run=cmd_exits)
    p = sub.add_parser("serve", help="run the dashboard in the browser")
    p.add_argument("--port", type=int, default=config.DASHBOARD_PORT)
    p.add_argument("--no-refresh", action="store_true", help="only show the data; don't refresh it automatically")
    p.set_defaults(run=cmd_serve)
    sub.add_parser("login", help="log the assistant's Telegram account in (once)").set_defaults(run=cmd_login)
    sub.add_parser("status", help="row counts and refresh times").set_defaults(run=cmd_status)
    sub.add_parser("fleet", help="list trucks and their links").set_defaults(run=cmd_fleet)

    p = sub.add_parser("holes", help="list everything that doesn't link up")
    p.add_argument("--all", action="store_true", help="list every item, not just the first ones")
    p.set_defaults(run=cmd_holes)

    sub.add_parser("pilot", help="show the pilot trucks with everything known about them").set_defaults(run=cmd_pilot)

    sub.add_parser("habits", help="collect every driver's fuel stops with the gauge (a few minutes)").set_defaults(run=cmd_habits)
    sub.add_parser("lookups", help="look up new fills in Samsara: place outside Love's, gauge before").set_defaults(run=cmd_lookups)

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

    sub.add_parser("efs-login", help="open the eManager window and keep its login alive until stopped").set_defaults(
        run=cmd_efs_login)
    p = sub.add_parser("efs-cards", help="list fuel cards in eManager, read only")
    add_card_lookup(p, default_by="all")
    p.set_defaults(run=cmd_efs_cards)

    p = sub.add_parser("efs-card", help="change one fuel card in eManager; shows the change unless --send")
    add_card_lookup(p, default_by="unit")
    change = p.add_mutually_exclusive_group(required=True)
    change.add_argument("--status", choices=efs_cards.STATUSES, help="set the card's status")
    change.add_argument("--override", type=int, metavar="TIMES",
                        help=f"override for 1-{efs_cards.MOST_TIMES} transactions, all locations")
    change.add_argument("--remove-override", action="store_true", help="take the override off")
    change.add_argument("--set", nargs=2, metavar=("PROMPT", "VALUE"),
                        help=f"set one prompt ({', '.join(efs_cards.PROMPTS)}), e.g. --set unit 99999")
    p.add_argument("--hand-enter", action="store_true", help="with --override: allow hand enter")
    p.add_argument("--send", action="store_true", help="make the change")
    p.set_defaults(run=cmd_efs_card)

    sub.add_parser("agent-login", help="log the card agent's own Telegram login in, once").set_defaults(
        run=cmd_agent_login)
    sub.add_parser("card-agent", help="run the card agent: answers fuel card requests in the driver groups").set_defaults(
        run=cmd_card_agent)

    args = parser.parse_args()
    # only the running assistant writes the log file: Windows can't rename a file another program holds open, and a
    # failed rename deletes the old files one by one
    setup_logging(to_file=args.run is cmd_serve)
    try:
        args.run(args)
    except (LookupError, RuntimeError) as error:  # e.g. unknown unit, missing .env key: something you can fix
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
