# The card commands of `main.py`: keeping the eManager login alive, listing fuel cards and changing one by hand, and
# starting the card agent and its Telegram login. main.py only lists them (register).
import argparse
import logging
import time
from collections import Counter
from datetime import datetime
from logging.handlers import RotatingFileHandler

from base import config
from base.models import EfsCard, EfsCardRow
from features.cards import settings as cards_settings
from features.cards.emanager import fuel_cards, site, window
from features.cards.emanager.window import EfsError


# Adds the card commands to main.py's command line.
def register(sub) -> None:
    sub.add_parser("efs-login", help="open the eManager window and keep its login alive until stopped").set_defaults(
        run=cmd_efs_login)
    p = sub.add_parser("efs-cards", help="list fuel cards in eManager, read only")
    add_card_lookup(p, default_by="all")
    p.set_defaults(run=cmd_efs_cards)

    p = sub.add_parser("efs-card", help="change one fuel card in eManager; shows the change unless --send")
    add_card_lookup(p, default_by="unit")
    change = p.add_mutually_exclusive_group(required=True)
    change.add_argument("--status", choices=fuel_cards.STATUSES, help="set the card's status")
    change.add_argument("--override", type=int, metavar="TIMES",
                        help=f"override for 1-{fuel_cards.MOST_TIMES} transactions, all locations")
    change.add_argument("--remove-override", action="store_true", help="take the override off")
    change.add_argument("--set", nargs=2, metavar=("PROMPT", "VALUE"),
                        help=f"set one prompt ({', '.join(fuel_cards.PROMPTS)}), e.g. --set unit 99999")
    p.add_argument("--hand-enter", action="store_true", help="with --override: allow hand enter")
    p.add_argument("--send", action="store_true", help="make the change")
    p.set_defaults(run=cmd_efs_card)

    sub.add_parser("agent-login", help="log the card agent's own Telegram login in, once").set_defaults(
        run=cmd_agent_login)
    sub.add_parser("card-agent", help="run the card agent: answers fuel card requests in the driver groups").set_defaults(
        run=cmd_card_agent)
    p = sub.add_parser("card-cases", help="save what drivers wrote about their fuel cards as test cases (reads the groups)")
    p.add_argument("--days", type=int, default=14, help="how far back to read (default 14)")
    p.add_argument("--most", type=int, default=60, help="the most cases to save, newest first (default 60)")
    p.set_defaults(run=cmd_card_cases)


# Opens the eManager window and keeps its login alive until Ctrl+C. eManager still ends every login after 24 hours.
def cmd_efs_login(args) -> None:
    window.start()
    print("The eManager window is open. Log in there; this keeps the login alive. Ctrl+C stops it.", flush=True)
    was = None
    try:
        while True:
            alive, said = efs_login_status()
            if said != was:
                print(f"{datetime.now():%H:%M} {said}", flush=True)
                was = said
            # ask often while waiting for the login, then well inside the 90-minute idle logout
            time.sleep(cards_settings.EMANAGER_HEARTBEAT_SECONDS if alive else 5)
    except KeyboardInterrupt:
        print("Stopped. The window stays open; without this, eManager logs out after 90 idle minutes.")


# One heartbeat: whether eManager has someone logged in, and who, or why not. A page still loading or changing (the
# login itself) fails the heartbeat for a moment; the next try sees how it ended.
def efs_login_status() -> tuple[bool, str]:
    try:
        if site.heartbeat():
            return True, f"logged in as {site.logged_in()}"
        return False, "not logged in: log in in the window"
    except EfsError as error:
        return False, f"not logged in yet ({error})"


# Logs the card agent's own Telegram login in, once (the same account as the assistant, a second login): you type the
# code Telegram sends to the account's app.
def cmd_agent_login(args) -> None:
    from features.cards import telegram_agent
    print(f"Card agent logged in as {telegram_agent.login()}.")


# Runs the card agent until stopped (features/cards/agent), with its own log file data/agent.log (only `serve` writes
# fuel.log). run_agent.bat starts it again if it stops.
def cmd_card_agent(args) -> None:
    from features.cards import agent as card_agent
    handler = RotatingFileHandler(config.DATA_DIR / "agent.log", maxBytes=config.LOG_MAX_MB * 1024 * 1024,
                                  backupCount=config.LOG_FILES_KEPT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger(__name__).info("Card agent starting (acts: %s)", cards_settings.AGENT_ACT)
    card_agent.run()


# Reads the truck groups' history for what drivers wrote about their fuel cards and saves the cases under
# data/card_cases, for the replay. Only reads: nothing is written to any group.
def cmd_card_cases(args) -> None:
    from features.cards import cases
    print(f"{cases.collect(args.days, args.most)} cases saved in {cases.CASES_DIR}")


# Lists one account's cards the way Card Lookup finds them, and a card's own page when exactly one is found. Read only.
def cmd_efs_cards(args) -> None:
    found = fuel_cards.cards(args.account, args.by, args.text)
    for row in found:
        print(card_line(row))
    statuses = Counter(row.status for row in found).most_common()
    print(f"{len(found)} cards: " + ", ".join(f"{count} {status}" for status, count in statuses))
    if len(found) == 1:
        print_card(fuel_cards.card(args.account, found[0]))


# Changes one card: its status, an override, taking the override off, or one prompt. Shows the card and the change
# first; only --send makes it, and then shows the card as eManager has it afterwards.
def cmd_efs_card(args) -> None:
    found = fuel_cards.cards(args.account, args.by, args.text)
    if args.by == "unit":
        # Card Lookup may also list units that only start with the text: 318 finds 3189
        found = [row for row in found if row.unit.strip() == args.text.strip()]
    if len(found) != 1:
        raise LookupError(f"{len(found)} cards found by {args.by} {args.text!r}; a change needs exactly one. "
                          "List them with efs-cards, then search by what only that card has.")
    row = found[0]
    print(card_line(row))
    print_card(fuel_cards.card(args.account, row))
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
        return f"set the status to {args.status}", lambda: fuel_cards.set_status(args.account, row, args.status)
    if args.remove_override:
        return "remove the override", lambda: fuel_cards.remove_override(args.account, row)
    if args.set:
        prompt, value = args.set
        return f"set {prompt} to {value!r}", lambda: fuel_cards.set_prompt(args.account, row, prompt, value)
    words = f"override for {args.override} transaction(s), all locations" + (", hand enter" if args.hand_enter else "")
    return words, lambda: fuel_cards.set_override(args.account, row, args.override, args.hand_enter)


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
    p.add_argument("account", choices=sorted(cards_settings.EMANAGER_USERS), help="which EFS account")
    p.add_argument("--by", choices=["all", *fuel_cards.LOOKUPS], default=default_by,
                   help=f"what to look up by (default {default_by})")
    p.add_argument("text", nargs="?", default="", help="what to look up, e.g. a unit number")
