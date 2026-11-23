# Replays saved driver cases (features/cards/cases) to the card agent against the real eManager, sending nothing. Each
# case goes through agent.work() exactly as a live tag would, with three things replaced: what is written to Telegram
# is kept in a list instead, the database is a copy, and a change in eManager lands on the user's own test card, never
# on a driver's. The result is a report in data/card_cases: what each driver wrote, what the agent did and would have
# replied, and what the office really did afterwards.
import asyncio
import html
import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from base import config
from base.models import EfsCard, EfsCardRow
from base.sources import telegram
from base.store import db
from features.cards import agent, cases, settings, telegram_agent, tools
from features.cards.emanager import fuel_cards
from features.cards.emanager.window import EfsError

log = logging.getLogger(__name__)
CHANGERS = ("set_status", "set_override", "remove_override", "set_prompt")  # everything in fuel_cards that changes a card
# eManager saying the rest of the batch can't work either (its own words, in a step or an outcome)
STOP_ON = ("EFS's bot check", "eManager is not logged in", "eManager not logged in", "eManager window is not open")


# The replay may not go on: the test card is not as expected, or a change was asked for on another card.
class ReplayError(RuntimeError):
    pass


# Makes every card change in this program refuse any card but the test card. The guard of the replay: whatever else
# goes wrong, a driver's card can't be changed from here.
def only_the_test_card() -> None:
    for name in CHANGERS:
        setattr(fuel_cards, name, _guarded(getattr(fuel_cards, name)))


# One changer of fuel_cards that first checks which card it was asked to change.
def _guarded(change):
    # The same change, on the test card only.
    def guarded(account: str, row: EfsCardRow, *args, **kwargs):
        if (account, row.card_id) != (settings.TEST_CARD_ACCOUNT, settings.TEST_CARD_ID):
            raise ReplayError(f"the replay refused to change card {row.card_id} in {account}: only the test card may change")
        return change(account, row, *args, **kwargs)

    return guarded


# Makes this program unable to write to Telegram: what the agent would write is kept in `written` instead, and no
# login can be opened.
def no_telegram(written: list[tuple[int, str, int | None]]) -> None:
    # Fails loudly: the replay must never reach a real Telegram login.
    def refuse(*args, **kwargs):
        raise ReplayError("the replay tried to reach Telegram")

    # Keeps what would have been written: the chat, the text, and the message it would reply to.
    async def keep(client, chat_id: int, text: str, reply_to: int | None = None) -> int:
        written.append((chat_id, text, reply_to))
        return len(written)

    telegram_agent.write, telegram_agent._client, telegram.send, telegram._client = keep, refuse, refuse, refuse


# The test card as eManager has it now: its Card Lookup row and its page. ReplayError when it can't be found.
def test_card() -> tuple[EfsCardRow, EfsCard]:
    rows = [r for r in fuel_cards.cards(settings.TEST_CARD_ACCOUNT, "unit", settings.TEST_CARD_UNIT)
            if r.card_id == settings.TEST_CARD_ID]
    if len(rows) != 1:
        raise ReplayError(f"the test card {settings.TEST_CARD_ID} was not found on unit {settings.TEST_CARD_UNIT} "
                          f"in {settings.TEST_CARD_ACCOUNT}")
    return rows[0], fuel_cards.card(settings.TEST_CARD_ACCOUNT, rows[0])


# True while the test card is at rest, as the user left it: inactive, not open, on its parking unit.
def at_rest(row: EfsCardRow, card: EfsCard) -> bool:
    return card.status == "INACTIVE" and not card.override and row.unit.strip() == settings.TEST_CARD_UNIT


# eManager's cards as the replay hands them to a request: lookups and card pages are the drivers' real ones, read only;
# an opening is made for real on the test card and reported back as if it were the driver's.
class OnTestCard:
    # `row` and `before`: the test card and its page as found at rest, before any change.
    def __init__(self, row: EfsCardRow, before: EfsCard):
        self.row, self.before, self.changes = row, before, 0

    # Card Lookup, for real.
    def cards(self, account: str, by: str, text: str) -> list[EfsCardRow]:
        return fuel_cards.cards(account, by, text)

    # A card's page, for real.
    def card(self, account: str, row: EfsCardRow) -> EfsCard:
        return fuel_cards.card(account, row)

    # The opening asked for a driver's card, made on the test card: activated first if it is at rest, opened, then the
    # override taken off again so the next case finds it ready. Returns the driver's card with the test card's result.
    def set_override(self, account: str, row: EfsCardRow, times: int, hand_enter: bool = False) -> EfsCard:
        mine = settings.TEST_CARD_ACCOUNT
        if fuel_cards.card(mine, self.row).status != "ACTIVE":
            fuel_cards.set_status(mine, self.row, "ACTIVE")
            self.changes += 1
        opened = fuel_cards.set_override(mine, self.row, times, hand_enter)
        fuel_cards.remove_override(mine, self.row)
        self.changes += 2
        return replace(fuel_cards.card(account, row), override=opened.override)

    # Puts the test card back as it was found and reads it again. ReplayError when it is not back at rest.
    def restore(self) -> None:
        mine = settings.TEST_CARD_ACCOUNT
        now = fuel_cards.card(mine, self.row)
        if now.override:
            fuel_cards.remove_override(mine, self.row)
        if now.status != self.before.status:
            fuel_cards.set_status(mine, self.row, self.before.status)
        row, card = test_card()
        if not at_rest(row, card) or card.status != self.before.status:
            raise ReplayError(f"the test card is NOT back as it was: status {card.status}, override {card.override}, "
                              f"unit {row.unit}. Put it back by hand.")


# Replays up to `most` saved cases, newest first, and writes the report. Returns the report's path.
def run(most: int) -> Path:
    todo = cases.saved()[:most]
    if not todo:
        raise ReplayError("no cases saved yet: run `card-cases` first")
    written: list[tuple[int, str, int | None]] = []
    no_telegram(written)
    only_the_test_card()
    copy = cases.CASES_DIR / "replay.db"
    _copy_database(copy)
    config.DB_PATH = copy
    settings.AGENT_ACT = True  # the whole path, as live; its writes are kept, its changes land on the test card
    row, before = test_card()
    if not at_rest(row, before):
        raise ReplayError(f"the test card is not at rest (status {before.status}, override {before.override}, unit "
                          f"{row.unit}): nothing was started")
    (cases.CASES_DIR / "test_card_before.json").write_text(json.dumps({"row": row.__dict__, "card": before.__dict__},
                                                                      indent=1, default=str), encoding="utf-8")
    cards = OnTestCard(row, before)
    results = []
    try:
        for case in todo:
            result = asyncio.run(_one(case, cards, written))
            results.append(result)
            log.info("Replayed unit %s (%s): %s", case["unit"], case["at"][:16], result["outcome"])
            if any(word in " ".join([str(result["outcome"]), *result["steps"]]) for word in STOP_ON):
                log.warning("eManager is not usable: stopped after %d of %d cases", len(results), len(todo))
                break
    finally:
        cards.restore()
    (cases.CASES_DIR / "replay.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    report = cases.CASES_DIR / "report.html"
    report.write_text(page(results, cards.changes), encoding="utf-8")
    return report


# One case through the agent, as a live tag: the run is claimed, the request worked to its end, and what it did kept.
async def _one(case: dict, cards: OnTestCard, written: list) -> dict:
    with db.connect() as conn:
        conn.execute("DELETE FROM agent_runs")  # each case starts clean: no reopen wait left by the case before it
    truck, drivers = agent._truck_of(case["chat_id"])
    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(case["at"])).days
    seen = {"unit": case["unit"], "at": case["at"], "age_days": age_days, "sender": case["sender"], "text": case["text"],
            "chat": [f"{c['sender']}{' (us)' if c['ours'] else ''}: {c['text']}{' [photo]' if c['photo'] else ''}"
                     for c in case["chat"]], "after": [f"{a['sender']}: {a['text']}" for a in case["after"]]}
    if truck is None:
        return seen | {"outcome": "no truck on this group any more", "steps": [], "reply": None, "office": []}
    with db.connect() as conn:
        db.claim_agent_run(conn, case["chat_id"], case["message_id"], truck.unit, datetime.now(timezone.utc), case["text"][:2000])
    request = tools.Request(None, case["chat_id"], case["message_id"], case["text"], case["sender"], truck, drivers)
    request.efs = cards
    start = len(written)
    await agent.work(request, cases.chat_of(case))
    mine = written[start:]
    with db.connect() as conn:
        recorded = conn.execute("SELECT outcome, error FROM agent_runs WHERE message_id = ?", (case["message_id"],)).fetchone()
    return seen | {"outcome": recorded["outcome"], "error": recorded["error"], "steps": request.steps,
                   "reply": next((text for chat, text, _ in mine if chat == case["chat_id"]), None),
                   "office": [text for chat, text, _ in mine if chat != case["chat_id"]],
                   "drivers_now": [d.full_name for d in drivers]}


# Copies the live database (read only) for the replay to work on.
def _copy_database(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for old in target.parent.glob(target.name + "*"):
        old.unlink()
    source = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    with sqlite3.connect(target) as copy:
        source.backup(copy)
    source.close()


# What a replayed case came to, in one word, for the report's counts.
def kind(result: dict) -> str:
    steps = " ".join(result["steps"])
    if result.get("error"):
        return "failed"
    if "opened" in steps:
        return "opened"
    if "would open" in steps:
        return "would open"
    if "needs a person" in steps or "asked the office" in steps or "hand_to_office" in steps:
        return "to the office"
    if result["reply"]:
        return "replied only"
    return "did nothing"


# The report as one HTML page: the counts on top, then every case with the chat, what the agent did, and what the
# office really did. Everything from Telegram is escaped.
def page(results: list[dict], changes: int) -> str:
    counts = {}
    for r in results:
        counts[kind(r)] = counts.get(kind(r), 0) + 1
    e = html.escape
    rows = []
    for r in results:
        rows.append(f"""<section><h2>Unit {e(r['unit'])} · {e(r['at'][:16].replace('T', ' '))} UTC · {r['age_days']} days ago
<span class="k {e(kind(r).replace(' ', '-'))}">{e(kind(r))}</span></h2>
<div class="cols"><div><h3>The chat before the driver's message</h3><pre>{e(chr(10).join(r['chat']))}</pre></div>
<div><h3>What the agent did</h3><pre>{e(chr(10).join(r['steps']) or '(no tool used)')}</pre>
<p><b>Outcome:</b> {e(str(r['outcome']))}{' · <b>error:</b> ' + e(str(r['error'])) if r.get('error') else ''}</p>
<p><b>Would reply to the driver:</b> {e(r['reply'] or '(nothing)')}</p>
<p><b>Would post to the office:</b></p><pre>{e(chr(10).join(r['office']) or '(nothing)')}</pre></div>
<div><h3>What was really written afterwards</h3><pre>{e(chr(10).join(r['after']) or '(nothing)')}</pre></div></div></section>""")
    summary = " · ".join(f"{e(k)}: {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    return f"""<!doctype html><meta charset="utf-8"><title>Card agent replay</title>
<style>body{{font:14px/1.45 "Segoe UI",system-ui,sans-serif;margin:24px;background:#0c1118;color:#e6eaf1}}
h1{{font-size:22px}}h2{{font-size:16px;margin:28px 0 8px;border-top:1px solid #243041;padding-top:14px}}h3{{font-size:12px;
color:#8e9aae;text-transform:uppercase;letter-spacing:.06em;margin:0 0 6px}}pre{{white-space:pre-wrap;background:#131a24;
padding:10px;border-radius:8px;margin:0 0 8px}}.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
gap:14px}}.k{{font-size:12px;padding:2px 8px;border-radius:10px;background:#243041;margin-left:8px}}.opened{{background:#1f6f4f}}
.to-the-office{{background:#7a5a12}}.failed{{background:#8a2f33}}p{{margin:4px 0}}</style>
<h1>Card agent replay: {len(results)} real cases</h1>
<p>{summary}</p>
<p>Nothing was sent to any driver or to the office, and no driver's card was changed: {changes} real changes were made, all on the
test card, which was put back. The truck, its drivers and its card are as they are today, not as on the message's day.</p>
{''.join(rows)}"""
