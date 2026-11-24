# Replays saved driver cases (features/cards/cases) to the card agent against the real eManager, sending nothing. Each
# case goes through agent.work() exactly as a live tag would, with three things replaced: what is written to Telegram
# is kept in a list instead, the database is a copy, and a change in eManager lands on the user's own test card, never
# on a driver's. The agent's clock is set to the moment of the driver's message, and what the database learned after it
# (later purchases, the truck's place and gauge now, the engine's state now) is kept from it, so a case days old is
# worked as if it had just come in. The result is a report in data/card_cases: each case as one conversation, from the chat before the
# driver's message, through what the agent thought, every tool it used and what it was answered, to what the office
# really did.
import asyncio
import html
import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from base import config, fuel
from base.models import EfsCard, EfsCardRow
from base.sources import telegram
from base.store import db
from features.cards import agent, cases, claude, settings, telegram_agent, tools
from features.cards.emanager import fuel_cards

log = logging.getLogger(__name__)
CHANGERS = ("set_status", "set_override", "remove_override", "set_prompt")  # everything in fuel_cards that changes a card
# eManager saying the rest of the batch can't work either (its own words, in a step or an outcome)
STOP_ON = ("EFS's bot check", "eManager is not logged in", "eManager not logged in", "eManager window is not open")
# Why a request went to the office, by words of the step that says so: the report counts these.
HANDED_FOR = (("not clearly one of them", "team truck: can't tell which driver wrote"),
              ("no active driver", "no active driver on the truck in Datatruck"),
              ("can't tell which card", "can't tell which card on the unit is the driver's"),
              ("not in the driver's name", "the only card is inactive and in another name"),
              ("eManager", "eManager did not answer or did not confirm"),
              ("that is not for the fuel desk", "the card's status is not in the owner's table"))


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


# Makes Claude's runs leave their record: what it was given to read, its trace (thoughts, tools, words, in order) and
# its last words go into `heard` (one dict, written over at each run). Claude itself runs for real.
def listen_to_claude(heard: dict) -> None:
    real = claude.run

    # The same run, with its input and its last words kept.
    async def run(system, text, photos, tools_given, workspace):
        heard.update(given=text, photos=len(photos), said="", problem="", cost=None, trace=[])
        said = await real(system, text, photos, tools_given, workspace)
        heard.update(said=said.text, problem=said.problem, cost=said.cost_usd, trace=[list(step) for step in said.trace])
        return said

    claude.run = run


# Sets the clock the agent's files read to `moment`: during a case, "now" is when the driver wrote.
def clock_at(moment: datetime) -> None:
    # The real datetime, whose `now` is the case's moment.
    class At(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    agent.datetime = tools.datetime = At


# A moment as the fuel purchases are stamped: Central time, "YYYY-MM-DD HH:MM".
def central(moment: datetime) -> str:
    return moment.astimezone(fuel.CENTRAL).strftime("%Y-%m-%d %H:%M")


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

    # The activation asked for a driver's card: nothing is changed (the opening that follows activates the test
    # card). Returns the driver's card as if it were active now.
    def set_status(self, account: str, row: EfsCardRow, status: str) -> EfsCard:
        return replace(fuel_cards.card(account, row), status=status)

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
    heard: dict = {}
    no_telegram(written)
    only_the_test_card()
    listen_to_claude(heard)
    copy = cases.CASES_DIR / "replay.db"
    _copy_database(copy)
    config.DB_PATH = copy
    settings.AGENT_ACT = True  # the whole path, as live; its writes are kept, its changes land on the test card
    settings.AGENT_MAX_JOBS = None  # every case is worked: the live agent's pause is not the replay's
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
            result = asyncio.run(_one(case, cards, written, heard))
            results.append(result)
            log.info("Replayed unit %s (%s): %s", case["unit"], case["at"][:16], result["outcome"])
            if any(word in " ".join([str(result["outcome"]), *result["steps"]]) for word in STOP_ON):
                log.warning("eManager is not usable: stopped after %d of %d cases", len(results), len(todo))
                break
    finally:
        cards.restore()
    (cases.CASES_DIR / "replay.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    report = cases.CASES_DIR / "report.html"
    note = (f"Nothing was sent to any driver or to the office, and no driver's card was changed: {cards.changes} real changes "
            "were made, all on the test card, which was put back. The agent's clock was set to each message's own moment, "
            "and later purchases and today's gauge and place were kept from it. The truck's drivers and the card's state in "
            "eManager are still today's, not the message's day's.")
    report.write_text(page(results, note), encoding="utf-8")
    return report


# One case through the agent, as a live tag: the run is claimed, the request worked to its end, and everything it did
# kept in order: each tool it used, with what it asked and what it was answered.
async def _one(case: dict, cards: OnTestCard, written: list, heard: dict) -> dict:
    wrote_at = datetime.fromisoformat(case["at"])
    clock_at(wrote_at + timedelta(minutes=1))  # the agent wakes a minute after the driver wrote
    with db.connect() as conn:
        conn.execute("DELETE FROM agent_runs")  # each case starts clean: no reopen wait left by the case before it
        # what was learned after the message is kept from the agent (cases run newest first, so this only ever trims)
        conn.execute("DELETE FROM fuel_lines WHERE fueled_at > ?", (central(wrote_at),))
        conn.execute("DELETE FROM truck_watch")
    truck, drivers = agent._truck_of(case["chat_id"])
    if truck is not None:  # where the truck is and its gauge are today's: unknown for the moment of the message
        truck = replace(truck, fuel_pct=None, fuel_at=None, place=None, lat=None, lng=None)
    age_days = (datetime.now(timezone.utc) - wrote_at).days
    seen = {"unit": case["unit"], "at": case["at"], "age_days": age_days, "sender": case["sender"], "text": case["text"],
            "chat": [{"at": c["at"], "sender": c["sender"], "ours": c["ours"], "text": c["text"], "photo": bool(c["photo"])}
                     for c in case["chat"]], "after": case["after"]}
    if truck is None:
        return seen | {"outcome": "no truck on this group any more", "steps": [], "talk": [], "reply": None, "office": []}
    with db.connect() as conn:
        db.claim_agent_run(conn, case["chat_id"], case["message_id"], truck.unit, wrote_at, case["text"][:2000])
    request = tools.Request(None, case["chat_id"], case["message_id"], case["text"], case["sender"], truck, drivers)
    request.efs = cards
    heard.clear()
    start = len(written)
    await agent.work(request, cases.chat_of(case))
    mine = written[start:]
    with db.connect() as conn:
        recorded = conn.execute("SELECT outcome, error FROM agent_runs WHERE message_id = ?", (case["message_id"],)).fetchone()
    return seen | {"outcome": recorded["outcome"], "error": recorded["error"], "steps": request.steps, "talk": request.talk,
                   "given": heard.get("given", ""), "said": heard.get("said", ""), "problem": heard.get("problem", ""),
                   "cost": heard.get("cost"), "trace": heard.get("trace", []),
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


# Why a case went to the office, in a few words; None when it didn't. The reason is read from what the rules said
# of the card (the declined_card step), never from the note Claude wrote. A hand-over the agent chose itself (a request
# that is not a card opening: a money code, a check, a lost card) is named as that; only runs before 2026-11-24 have
# one, since Claude no longer has the tool.
def handed_for(result: dict) -> str | None:
    steps = " ".join(result["steps"])
    if "hand_to_office" not in steps and "asked the office" not in steps:
        return None
    ruled = " ".join(step for step in result["steps"] if step.startswith("declined_card"))
    for words, reason in HANDED_FOR:
        if words in ruled:
            return reason
    return "not a card opening: the agent has no tool for it"


# The report as one HTML page: the counts, `note` (how the cases were run) and the reasons for every hand-over on top,
# then each case as one conversation. Everything from Telegram and from Claude is escaped.
def page(results: list[dict], note: str) -> str:
    e = html.escape
    counts, reasons = {}, {}
    for r in results:
        counts[kind(r)] = counts.get(kind(r), 0) + 1
        why = handed_for(r)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    summary = " · ".join(f"{e(k)}: {n}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    why_rows = "".join(f"<tr><td>{n}</td><td>{e(w)}</td></tr>" for w, n in sorted(reasons.items(), key=lambda kv: -kv[1]))
    return f"""<!doctype html><meta charset="utf-8"><title>Card agent replay</title>
<style>body{{font:14px/1.45 "Segoe UI",system-ui,sans-serif;margin:24px auto;max-width:980px;padding:0 16px;background:#0c1118;color:#e6eaf1}}
h1{{font-size:22px}}h2{{font-size:16px;margin:36px 0 10px;border-top:1px solid #243041;padding-top:16px}}
.k{{font-size:12px;padding:2px 8px;border-radius:10px;background:#243041;margin-left:8px}}.opened{{background:#1f6f4f}}
.to-the-office{{background:#7a5a12}}.failed{{background:#8a2f33}}
.m{{margin:6px 0;padding:8px 12px;border-radius:10px;background:#131a24;max-width:78%;white-space:pre-wrap}}
.m b{{display:block;font-size:12px;color:#8e9aae;font-weight:600}}.ours{{background:#1a2330}}.case{{outline:2px solid #f2a33a}}
.agent{{margin-left:auto;background:#17324a}}.office{{margin-left:auto;background:#3a2f12}}.after{{opacity:.75}}
.step{{margin:6px 0 6px 22%;padding:8px 12px;border-left:3px solid #5b9cf5;background:#10161f;white-space:pre-wrap;font-size:13px}}
.step b{{color:#5b9cf5}}.refused{{border-color:#f2676b}}.thought{{border-color:#b98ae6;color:#cdbfe6;font-style:italic}}
.thought b{{color:#b98ae6;font-style:normal}}.label{{font-size:12px;color:#8e9aae;text-transform:uppercase;letter-spacing:.06em;margin:16px 0 4px}}
details{{margin:8px 0}}summary{{cursor:pointer;color:#8e9aae}}pre{{white-space:pre-wrap;background:#131a24;padding:10px;border-radius:8px}}
table{{border-collapse:collapse}}td{{padding:3px 12px 3px 0}}</style>
<h1>Card agent replay: {len(results)} real cases</h1>
<p>{summary}</p>
<p>{e(note)}</p>
<div class="label">Why requests went to the office</div><table>{why_rows or '<tr><td>none</td></tr>'}</table>
{''.join(_conversation(r) for r in results)}"""


# One case as a conversation: the chat before the driver's message, what the agent was told, what it thought and each
# tool it used with its answer (in order), what it would have written to the driver and the office, its own
# explanation at the end, and what was really written afterwards.
def _conversation(r: dict) -> str:
    e = html.escape
    before = "".join(_bubble(c["sender"], c["text"] + (" [photo]" if c["photo"] else ""), c["at"],
                             "ours" if c["ours"] else "", last=i == len(r["chat"]) - 1) for i, c in enumerate(r["chat"]))
    steps, talk = "", list(r["talk"])
    # a case kept before the trace was: its tools only, in order
    for step_kind, text in r.get("trace") or [[claude.USED, t["tool"]] for t in talk]:
        if step_kind == claude.THOUGHT:
            steps += f'<div class="step thought"><b>it thought</b> {e(text)}</div>'
        elif step_kind == claude.SAID and text != (r.get("said") or "").strip():  # its last words are shown below
            steps += f'<div class="step"><b>it noted</b> {e(text)}</div>'
        elif step_kind == claude.USED:
            used = next((t for t in talk if t["tool"] == text), None)
            if used is None:
                steps += f'<div class="step refused"><b>{e(text)}</b> (the tool did not run)</div>'
                continue
            talk.remove(used)
            steps += _tool(used)
    office = "".join(_bubble("Fuel desk (would post to the office)", text, "", "office") for text in r["office"])
    after = "".join(_bubble(a["sender"], a["text"], a["at"], "after") for a in r["after"])
    cost = f" · ${r['cost']:.2f}" if r.get("cost") else ""
    return f"""<h2>Unit {e(r['unit'])} · {e(r['at'][:16].replace('T', ' '))} UTC · {r['age_days']} days ago
<span class="k {e(kind(r).replace(' ', '-'))}">{e(kind(r))}</span></h2>
<div class="label">The chat, up to the driver's message</div>{before}
<details><summary>What the agent was told about the truck</summary><pre>{e(r.get('given', '').split(chr(10) + chr(10) + 'The chat,')[0])}</pre></details>
<div class="label">What the agent did{e(cost)}</div>{steps or '<div class="step">(it used no tool)</div>'}{office}
<div class="step"><b>its own explanation at the end</b> {e(r.get('said') or '(none)')}{' · stopped: ' + e(r['problem']) if r.get('problem') else ''}
<b>recorded outcome</b> {e(str(r['outcome']))}{' · error: ' + e(str(r['error'])) if r.get('error') else ''}</div>
<div class="label">What was really written afterwards</div>{after or '<div class="m after">(nothing)</div>'}"""


# One use of a tool as a report block: what Claude asked of it and what it answered; a reply that went out is also
# shown as the message the driver would have got.
def _tool(used: dict) -> str:
    e = html.escape
    asked = json.dumps(used["asked"], ensure_ascii=False) if used["asked"] else ""
    block = (f'<div class="step{" refused" if used["refused"] else ""}"><b>{e(used["tool"])}</b> {e(asked)}\n'
             f'→ {e(used["answer"])}</div>')
    if used["tool"] == "reply_to_driver" and not used["refused"]:
        block += _bubble("Fuel desk (would send to the driver)", used["asked"].get("text", ""), "", "agent")
    return block


# One message of a conversation as a bubble: who, when (hour and minute), and the text.
def _bubble(sender: str, text: str, at: str, style: str, last: bool = False) -> str:
    when = f" · {at[11:16]}" if at else ""
    return (f'<div class="m {style}{" case" if last else ""}"><b>{html.escape(sender)}{when}</b>'
            f'{html.escape(text or "")}</div>')
