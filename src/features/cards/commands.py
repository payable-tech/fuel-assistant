# The card commands of `main.py`: keeping the eManager login alive, listing fuel cards and changing one by hand, the
# card cleanup, starting the card agent, the card checker, and their Telegram logins. main.py only lists them
# (register).
import argparse
import logging
import time
from collections import Counter
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from base import config
from base.models import EfsCard, EfsCardRow
from features.cards import card_list, settings as cards_settings
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
    change.add_argument("--xref", metavar="TEXT", help='set the card\'s X-Ref note, e.g. "HOMETIME 11/26"; "" clears it')
    change.add_argument("--set", nargs=2, metavar=("PROMPT", "VALUE"),
                        help=f"set one prompt ({', '.join(fuel_cards.PROMPTS)}), e.g. --set unit 99999")
    p.add_argument("--hand-enter", action="store_true", help="with --override: allow hand enter")
    p.add_argument("--send", action="store_true", help="make the change")
    p.set_defaults(run=cmd_efs_card)

    sub.add_parser("agent-login", help="log the card agent's own Telegram login in, once").set_defaults(
        run=cmd_agent_login)
    sub.add_parser("card-agent", help="run the card agent: answers fuel card requests in the driver groups").set_defaults(
        run=cmd_card_agent)
    sub.add_parser("checker-login", help="log the card checker's own Telegram login in, once (Bob's account)").set_defaults(
        run=cmd_checker_login)
    p = sub.add_parser("card-check", help="check every ACTIVE card: read its truck's group and say whether the card "
                                          "should be on; changes nothing")
    p.add_argument("--most", type=int, help="check at most this many cards (a trial)")
    p.add_argument("--unit", help="check only the cards on this unit")
    p.set_defaults(run=cmd_card_check)
    p = sub.add_parser("card-cases", help="save what drivers wrote about their fuel cards as test cases (reads the groups)")
    p.add_argument("--days", type=int, default=14, help="how far back to read (default 14)")
    p.add_argument("--most", type=int, default=60, help="the most cases to save, newest first (default 60)")
    p.set_defaults(run=cmd_card_cases)
    p = sub.add_parser("card-replay", help="play the saved cases to the card agent on the real eManager; sends nothing")
    p.add_argument("--most", type=int, default=10, help="how many cases, newest first (default 10)")
    p.set_defaults(run=cmd_card_replay)
    p = sub.add_parser("efs-cleanup", help="the card cleanup: plan which EFS cards each Datatruck unit keeps and which "
                                           "are parked (99999 / ALIF UZ CORP), read only; --park PLAN parks them")
    do = p.add_mutually_exclusive_group()
    do.add_argument("--park", type=Path, metavar="PLAN", help="park the 'park' cards of this plan file in eManager")
    do.add_argument("--undo", metavar="CARD_ID", help="put one parked card's prompts back as the log has them")
    p.add_argument("--most", type=int, default=5, help="with --park: the most cards to park this run (default 5)")
    p.set_defaults(run=cmd_efs_cleanup)


# The card cleanup: by default writes the plan and says what is in it (changes no card); --park parks a plan's cards,
# a few at a time; --undo puts one card back. Both of those need the eManager window logged in (the card agent's).
def cmd_efs_cleanup(args) -> None:
    from features.cards import cleanup, cleanup_rules
    if args.park or args.undo:
        window.start()
        if args.undo:
            print(cleanup.undo(args.undo))
            return
        try:
            done = cleanup.park(args.park, args.most)
        finally:
            print(f"Log: {cleanup.LOG}")
        print(", ".join(f"{n} {what}" for what, n in done.most_common()) or "nothing to park")
        return
    path, counts, no_card, copied_at = cleanup.plan()
    print(f"EFS's list as copied at {copied_at} (UTC): " + ", ".join(f"{n} {a}" for a, n in counts.most_common()))
    print(f"Units left with no card ({len(no_card)}): {', '.join(no_card) or 'none'}")
    print(f"Plan: {path}  ('{cleanup_rules.LEAVE}' rows first: for a person)")


# Opens the eManager window and keeps its login alive until Ctrl+C, and while logged in copies EFS's cards into the
# database every EFS_COPY_MINUTES (features/cards/card_list), as the card agent does: the dashboard's card list stays
# current with the agent off. eManager still ends every login after about a day.
def cmd_efs_login(args) -> None:
    window.start()
    print("The eManager window is open. Log in there; this keeps the login alive and copies EFS's cards. Ctrl+C stops it.",
          flush=True)
    was, copied = None, None  # what was last said; when the cards were last copied (None: not yet)
    try:
        while True:
            alive, said = efs_login_status()
            if said != was:
                print(f"{datetime.now():%H:%M} {said}", flush=True)
                was = said
            if alive and (copied is None or time.monotonic() - copied >= cards_settings.EFS_COPY_MINUTES * 60):
                card_list.copy()  # says what it copied in this window (the log)
                copied = time.monotonic()
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
    _log_to("agent.log")
    logging.getLogger(__name__).info("Card agent starting (acts: %s)", cards_settings.AGENT_ACT)
    card_agent.run()


# Logs the card checker's own Telegram login in, once: Telegram asks for Bob's phone, then the code it sends there.
def cmd_checker_login(args) -> None:
    from features.cards import telegram_agent
    print(f"Card checker logged in as {telegram_agent.login(cards_settings.CHECKER_SESSION_PATH)}.")


# One round of the card checker (features/cards/card_check), with its own log file data/checker.log. Only reads.
def cmd_card_check(args) -> None:
    from features.cards import card_check
    _log_to("checker.log")
    checked, of = card_check.run(args.most, args.unit)
    print(f"Cards checked: {checked} of {of}. Log: {config.DATA_DIR / 'checker.log'}")


# Sends this program's log to its own file in data/ as well (only `serve` writes fuel.log).
def _log_to(name: str) -> None:
    handler = RotatingFileHandler(config.DATA_DIR / name, maxBytes=config.LOG_MAX_MB * 1024 * 1024,
                                  backupCount=config.LOG_FILES_KEPT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


# Reads the truck groups' history for what drivers wrote about their fuel cards and saves the cases under
# data/card_cases, for the replay. Only reads: nothing is written to any group.
def cmd_card_cases(args) -> None:
    from features.cards import cases
    print(f"{cases.collect(args.days, args.most)} cases saved in {cases.CASES_DIR}")


# Plays the saved cases to the card agent as live tags, on the real eManager (log in in its window first). Nothing is
# sent to a driver or the office, and the only card changed is the test card, which is put back. Writes a report.
def cmd_card_replay(args) -> None:
    from features.cards import replay
    logging.getLogger().setLevel(logging.INFO)
    window.start()
    print(f"Report: {replay.run(args.most)}")


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
    if args.xref is not None:
        return f"set the X-Ref to {args.xref!r}", lambda: fuel_cards.set_xref(args.account, row, args.xref)
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
