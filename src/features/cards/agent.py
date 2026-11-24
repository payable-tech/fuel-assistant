# The card agent (the user's go, 2026-11-23), built the way bob-agent's Telegram agent works: wakes when the assistant's
# account is tagged in a truck's group, reads the chat before the tag (photos too) with what we know of the truck, and
# lets Claude (this PC's Claude Code login) decide which of its tools to use (features/cards/tools). What is done to a
# card is settled by the owner's rule in code (features/cards/rules), whatever the chat says. This file is the program
# around that: hearing a tag, deciding whether to wake, working one request to its end and recording it.
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from base import config
from base.fuel import is_diesel
from base.models import ChatLine, DatatruckDriver, Truck
from base.store import db
from features.cards import claude, rules, settings, telegram_agent, tools, wording
from features.cards.emanager import fake_cards, fuel_cards, site, window
from features.cards.tools import Request

log = logging.getLogger(__name__)
WORKSPACE = config.DATA_DIR / "agent"     # where the Claude runs keep their conversations
JOIN_MINUTES = 10                         # a bare tag this soon after a request in the same group joins it: no new run
BEAT_SECONDS = 30                         # how often it notes that it is running (its pulse, for the dashboard)
_one_run = asyncio.Lock()                 # one request at a time, in the order they came


# Forever: opens the eManager window, keeps its login alive, and answers every tag in the truck groups.
def run() -> None:
    if not settings.AGENT_TEST_ONLY:  # the test group's card is a pretend one: no eManager needed
        window.start()
    asyncio.run(_main())


# The listener, the pulse, the login keeper and the copying of EFS's cards side by side; any of them stopping ends the
# program (run_agent.bat starts it again).
async def _main() -> None:
    await asyncio.gather(telegram_agent.listen(on_tag), _beat(),
                         *([] if settings.AGENT_TEST_ONLY else [_keep_login(), _keep_cards()]))


# Forever: copies EFS's card list into the database every EFS_COPY_MINUTES, for the dashboard (this program holds the
# eManager window, so the copying is its).
async def _keep_cards() -> None:
    while True:
        await copy_cards()
        await asyncio.sleep(settings.EFS_COPY_MINUTES * 60)


# One round of the copying: each account's whole card list, as Card Lookup gives it. An account that can't be read
# now (eManager logged out, a page that didn't load) or comes back empty keeps its old copy and is tried next round.
async def copy_cards() -> None:
    for account in tools.ACCOUNTS:
        try:
            cards = await tools.emanager(fuel_cards.cards, account, "all")
        except Exception as failure:
            log.warning("EFS cards of %s not copied: %r", account, failure)
            continue
        if not cards:
            log.warning("EFS cards of %s not copied: the list came back empty", account)
            continue
        with db.connect() as conn:
            db.replace_efs_cards(conn, account, cards)
        log.info("EFS cards of %s copied: %d", account, len(cards))


# Forever: notes every BEAT_SECONDS that the agent is running, so the dashboard can tell when it stopped.
async def _beat() -> None:
    while True:
        with db.connect() as conn:
            db.agent_beat(conn, datetime.now(timezone.utc))
        await asyncio.sleep(BEAT_SECONDS)


# A tag heard. Not in its own office or test chat, only in a group linked to a truck, worth waking for, not a bare tag
# right after a request there, and never the same message twice; then the chat is read and the request worked. A tag
# that is not worked is logged with the reason.
async def on_tag(client, message, named: bool) -> None:
    text = message.message or ""
    test = message.chat_id == settings.AGENT_TEST_CHAT_ID
    if (settings.AGENT_TEST_ONLY and not test) or not rules.woken(text, named):
        return _skipped(message, "not tagged by name and no card words" if not rules.woken(text, named)
                        else "only the test group is worked (AGENT_TEST_ONLY)")
    if not test and message.chat_id in (settings.AGENT_OFFICE_CHAT_ID, config.TEST_CHAT_ID):
        # its reports go there: a reply in them is the office's, not a driver's
        return _skipped(message, "this is the agent's own office or test chat")
    truck, drivers = _truck_of(message.chat_id)
    if truck is None:  # its chat is never sent anywhere
        return _skipped(message, "this group is linked to no truck")
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        if rules.only_a_tag(text) and db.agent_run_since(conn, message.chat_id, now - timedelta(minutes=JOIN_MINUTES)):
            # "@desk" again while the request just taken there is worked: it joins that one
            taken = "a bare tag right after a request there: it joins that one"
        elif not db.claim_agent_run(conn, message.chat_id, message.id, truck.unit, now, text[:2000]):
            taken = "this message was already taken"
        else:
            taken = None
            db.agent_tag(conn, now, f"unit {truck.unit}: taken")
    if taken:  # said once the database is let go: the note of it is a write of its own
        return _skipped(message, taken)
    log.info("Tag in chat %s (message %s), unit %s: working it", message.chat_id, message.id, truck.unit)
    chat = await telegram_agent.chat_before(client, message.chat_id, message.id, settings.AGENT_HISTORY,
                                            settings.AGENT_MAX_PHOTOS)
    async with _one_run:
        await work(Request(client, message.chat_id, message.id, text, chat[-1].sender if chat else "", truck, drivers), chat)


# Logs a tag that is not worked, and why, and notes it in the pulse.
def _skipped(message, why: str) -> None:
    log.info("Tag in chat %s (message %s) not worked: %s. It said: %s", message.chat_id, message.id, why,
             (message.message or "")[:80])
    with db.connect() as conn:
        db.agent_tag(conn, datetime.now(timezone.utc), f"not worked: {why}")


# Works one request to its end and records it, with the run's whole record (what Claude read, what it thought, each
# tool with its answer). After its set number of jobs it is paused: a card request is left for the office and Claude
# isn't asked. Without eManager no card can be fixed: the office is told and Claude isn't asked. A failure of Claude or
# Telegram goes to the office too.
async def work(task: Request, chat: list[ChatLine]) -> None:
    outcome, error, record = "", None, None
    try:
        if not task.test and _paused():
            if rules.CARD_WORDS.search(task.text):
                await task.office(wording.limit_reached(task.unit, settings.AGENT_MAX_JOBS, task.text))
            outcome = f"paused after {settings.AGENT_MAX_JOBS} jobs: left for the office"
        elif not task.test and not await _emanager_alive():
            await task.office(wording.not_logged_in(task.unit, task.text))
            outcome = "eManager not logged in: left for the office"
        else:
            given = prompt(task, chat)
            said = await claude.run(wording.SYSTEM, given, [c.photo for c in chat if c.photo], task.tools(), WORKSPACE)
            outcome = task.outcome() or (f"stopped: {said.problem}" if said.problem else
                                         f"nothing to do: {said.text[:200]}")
            record = json.dumps({"sender": task.sender, "given": given, "trace": said.trace, "talk": task.talk,
                                 "said": said.text, "problem": said.problem, "cost": said.cost_usd, "office": task.posts,
                                 "card": task.card,
                                 "chat": [{"at": c.at.isoformat(), "sender": c.sender, "ours": c.ours, "text": c.text,
                                           "photo": bool(c.photo)} for c in chat]}, ensure_ascii=False)
    except Exception as failure:
        error, outcome = repr(failure)[:500], "failed"
        log.exception("Card agent failed on %s / %s", task.chat_id, task.message_id)
        await task.office(wording.could_not_finish(task.unit, type(failure).__name__, task.text))
    with db.connect() as conn:
        db.finish_agent_run(conn, task.chat_id, task.message_id, outcome, json.dumps(task.steps), task.opened,
                            task.opened_at, error, record)
    log.info("Card agent, unit %s: %s", task.unit, outcome)


# True once the agent has done its set number of jobs since the count began (settings.AGENT_MAX_JOBS; None: no limit).
def _paused() -> bool:
    if settings.AGENT_MAX_JOBS is None:
        return False
    with db.connect() as conn:
        return db.agent_jobs_since(conn, settings.AGENT_JOBS_SINCE) >= settings.AGENT_MAX_JOBS


# What Claude is given to read for a request: what the database knows of the truck (its engine state, the Love's near
# it, its last diesel), and the chat, in the words of features/cards/wording.
def prompt(task: Request, chat: list[ChatLine]) -> str:
    now = datetime.now(timezone.utc)
    with db.connect() as conn:
        watch = db.truck_watch(conn, task.unit)
        loves = db.stores(conn)
        fills = [l for l in db.fuel_lines(conn, (now - timedelta(days=3)).date().isoformat())
                 if l.unit == task.unit and is_diesel(l)]
    truck_facts = wording.facts(task.truck, task.drivers, watch.state if watch else None, loves, fills, now)
    return wording.task_text(truck_facts, wording.transcript(chat), task.sender, now)


# The truck whose group this is, and its active drivers in Datatruck; (None, []) for a group linked to no truck.
def _truck_of(chat_id: int) -> tuple[Truck | None, list[DatatruckDriver]]:
    if chat_id == settings.AGENT_TEST_CHAT_ID:
        return fake_cards.TRUCK, fake_cards.DRIVERS
    with db.connect() as conn:
        truck = next((t for t in db.fleet(conn) if t.chat_id == chat_id), None)
        drivers = [d for d in db.dt_drivers(conn) if truck and d.unit == truck.unit and d.employee_status == "active"]
    return truck, drivers


# Whether eManager has someone logged in right now (Chrome closed or not answering counts as no).
async def _emanager_alive() -> bool:
    try:
        return await tools.emanager(site.heartbeat)
    except Exception:
        return False


# Forever: asks eManager every few minutes whether someone is logged in, which also keeps the login from timing out
# (90 idle minutes); logs when that changes.
async def _keep_login() -> None:
    was = None
    while True:
        alive = await _emanager_alive()
        with db.connect() as conn:
            db.agent_emanager(conn, alive, datetime.now(timezone.utc))
        if alive != was:
            (log.info if alive else log.warning)("eManager %s", "logged in" if alive else
                                                 "NOT logged in: log in in its window")
            was = alive
        await asyncio.sleep(settings.EMANAGER_HEARTBEAT_SECONDS if alive else 60)
