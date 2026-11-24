# Tests the card agent: whose card a request is for, the user's rule for it (opened whatever its status, an inactive
# card of his activated first), that the tools hold whatever the model asks (only a card on the truck's unit, opened
# once for one fill, one reply, never a number, every opening reported), what wakes it, and how Claude is called (the Claude Code login, no
# built-in tools). eManager, Telegram and Claude are fakes here.
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from base import config
from base.models import ChatLine, DatatruckDriver, EfsCard, EfsCardRow, Store, Truck
from base.store import db
from features.cards import agent, rules, settings as cards_settings, tools, wording
from features.cards.rules import NeedsPerson

NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)
JOHN = DatatruckDriver(1, "JOHN DOE (CD team)", "company_driver", "active", "DT", "3189")
MARY = DatatruckDriver(2, "MARY ROE (CD team)", "company_driver", "active", "DT", "3189")
TRUCK = Truck("3189", "1", "V", "Unit 3189", "John Doe", 7.0, 22.0, NOW, 30.0, -97.0, "I-35, Austin, TX", NOW, 150.0,
              "manual", None, -100, "auto", None, True)


# A Card Lookup row and its card page.
def card(card_id: str, unit: str, driver: str, status: str = "ACTIVE", override: bool = False) -> tuple:
    row = EfsCardRow(card_id, f"556748******{card_id[-4:]}", "1", unit, "4455", driver, "", status)
    page = EfsCard(card_id, status, "POLICY", "CARD", "POLICY", "1", "", "Oct 1, 2029", "Nov 20, 2026", override,
                   (("Unit Number", "Exact Match", unit), ("Driver ID", "Exact Match", "4455")))
    return row, page


# A temporary database, fake eManager cards on unit 3189 (John's, Mary's) and 31890, and every Telegram write caught.
@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "TEST_CHAT_ID", -555)
    monkeypatch.setattr(cards_settings, "AGENT_OFFICE_CHAT_ID", None)
    monkeypatch.setattr(cards_settings, "AGENT_ACT", True)
    w = SimpleNamespace(cards={}, opened=[], activated=[], writes=[])
    for c in (card("c10001", "3189", "JOHN DOE"), card("c20002", "3189", "MARY ROE"), card("c30003", "31890", "JOHN DOE")):
        w.cards[c[0].card_id] = c
    monkeypatch.setattr(tools.fuel_cards, "cards", lambda account, by, text:
                        [r for r, _ in w.cards.values() if account == "DT" and r.unit.startswith(text)])
    monkeypatch.setattr(tools.fuel_cards, "card", lambda account, row: w.cards[row.card_id][1])

    def override(account, row, times):
        w.opened.append((account, row.card_id, times))
        return EfsCard(**{**w.cards[row.card_id][1].__dict__, "override": True})

    def status(account, row, to):
        w.activated.append((row.card_id, to))
        w.cards[row.card_id] = (row, EfsCard(**{**w.cards[row.card_id][1].__dict__, "status": to}))
        return w.cards[row.card_id][1]

    async def write(client, chat, text, reply_to=None):
        w.writes.append((chat, text, reply_to))
        return 1

    monkeypatch.setattr(tools.fuel_cards, "set_override", override)
    monkeypatch.setattr(tools.fuel_cards, "set_status", status)
    monkeypatch.setattr(tools.telegram_agent, "write", write)
    return w


# A request from unit 3189's group, message 42, written by `sender`.
def task(sender: str = "John Doe", drivers=(JOHN,), text: str = "card declined at Pilot, open please") -> tools.Request:
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 42, "3189", NOW, text)
    return tools.Request(None, -100, 42, text, sender, TRUCK, list(drivers))


# Runs one of the agent's async tools and returns its answer's text.
def said(call) -> str:
    return asyncio.run(call)["content"][0]["text"]


# Same person: two words in common, or one when a name has one word; Datatruck's brackets don't count.
def test_same_person():
    assert rules.same_person("John Doe", "JOHN DOE (CD team)")
    assert rules.same_person("Johnny", "JOHNNY WALKER")
    assert not rules.same_person("John Smith", "JOHN DOE")
    assert not rules.same_person("", "JOHN DOE")


# Whose card: the one driver; on a team truck the one writing, by name, and when the name fits both, the one it fits
# word for word; no one when that can't be told.
def test_whose():
    assert rules.whose([JOHN], "Big Boss") == JOHN
    assert rules.whose([JOHN, MARY], "Mary Roe") == MARY
    assert rules.whose([JOHN, MARY], "Dispatch Night") is None and rules.whose([], "John") is None
    both = DatatruckDriver(3, "JEFF PERN / Roe Mary", None, "active", "DT", "3189")
    assert rules.whose([both, MARY], "Mary Roe") == MARY


# Their card: on the unit exactly and in the driver's name. With none in his name (or no driver told), the one card
# in use on the unit; a person decides only when that still leaves no one card.
def test_their_card():
    found = [("DT", card("a1", "3189", "JOHN DOE")[0]), ("DT", card("a2", "31890", "JOHN DOE")[0]),
             ("DT", card("a3", "3189", "MARY ROE")[0])]
    assert rules.their_card(found, "3189", JOHN) == ("DT", found[0][1], True)
    sam = DatatruckDriver(9, "SAM NEW", None, "active", "DT", "3189")
    with pytest.raises(NeedsPerson, match="can't tell which card on unit 3189 is for SAM NEW"):
        rules.their_card(found, "3189", sam)
    with pytest.raises(NeedsPerson, match="the driver who wrote"):
        rules.their_card(found, "3189", None)
    old = [("DT", card("b1", "3189", "OLD DRIVER", "INACTIVE")[0]), ("DT", card("b2", "3189", "KASH NEW")[0])]
    assert rules.their_card(old, "3189", sam) == ("DT", old[1][1], False)     # the one card in use, not in his name
    assert rules.their_card(old, "3189", None) == ("DT", old[1][1], False)
    two = [("ALIF", card("d1", "3189", "JOHN DOE", "INACTIVE")[0]), ("DT", card("d2", "3189", "DOE JOHN", "HOLD")[0])]
    assert rules.their_card(two, "3189", JOHN) == ("DT", two[1][1], True)     # two in his name: the one in use


# The user's rule: any status but inactive is opened as it is (hold and fraud too); an inactive card is activated
# first, but only the driver's own; a card already open is left; a repeat is noticed within its hours.
def test_verdict():
    row, page = card("c1", "3189", "X")
    assert rules.verdict(page, "DT", row, True, True) == rules.OPEN
    for status in ("HOLD", "FRAUD"):
        assert rules.verdict(card("c1", "3189", "X", status)[1], "DT", row, False, True) == rules.OPEN
    inactive = card("c1", "3189", "X", "INACTIVE")[1]
    assert rules.verdict(inactive, "DT", row, True, True) == rules.ACTIVATE_AND_OPEN
    with pytest.raises(NeedsPerson, match="not in the driver's name"):
        rules.verdict(inactive, "DT", row, False, True)
    assert rules.verdict(card("c1", "3189", "X", "FRAUD", override=True)[1], "DT", row, True, True) == rules.ALREADY_OPEN
    assert rules.verdict(page, "DT", row, True, False) == rules.WATCH_ONLY
    assert rules.repeat(NOW - timedelta(hours=2), NOW, 24) == timedelta(hours=2)
    assert rules.repeat(NOW - timedelta(hours=30), NOW, 24) is None and rules.repeat(None, NOW, 24) is None


# What wakes it and what it is told: a tag by name, or a card request answering it; facts with no driver ID.
def test_woken_and_facts():
    assert rules.woken("thanks", True) and not rules.woken("ok thanks", False) and rules.woken("card declined", False)
    assert rules.only_a_tag("@desk ") and not rules.only_a_tag("@desk card")
    text = wording.facts(TRUCK, [JOHN], "watch", [Store("7", "Seguin", "TX", 30.0, -96.6, 6.0, 5.5, "2026-11-23")], [], NOW)
    assert "unit 3189" in text and "22%" in text and "Seguin" in text and "4455" not in text


# The usual request: the driver's own card is opened once for one fill, reported to the office (last four digits
# only), and the line to tell the driver comes back; then the reply goes to the driver's message.
def test_declined_card_opens_his_card(world):
    t = task()
    line = said(t.declined_card({}))
    assert "try again now" in line and world.opened == [("DT", "c10001", 1)]
    office = world.writes[0]
    assert office[0] == -555 and "Opened card …0001" in office[1] and "556748" not in office[1]
    assert said(t.declined_card({})).startswith("The card was already opened")       # once per request
    assert world.opened == [("DT", "c10001", 1)]
    assert said(t.reply_to_driver({"text": "Card is ready, try again now."})) == "Sent."
    assert world.writes[-1] == (-100, "Card is ready, try again now.", 42)
    assert "already replied" in said(t.reply_to_driver({"text": "ok"}))
    with db.connect() as conn:
        assert db.agent_last_opened(conn, "c10001") is not None                       # recorded at once
    assert t.outcome() == "opened c10001, replied"


# On a team truck the card of the one writing is opened; someone not clearly a driver, with two cards in use on the
# unit, goes to the office.
def test_team_truck(world):
    assert "try again" in said(task("Mary Roe", (JOHN, MARY)).declined_card({}))
    assert world.opened == [("DT", "c20002", 1)]
    world.opened.clear()
    assert "Needs a person" in said(task("Night Dispatch", (JOHN, MARY)).declined_card({}))
    assert world.opened == [] and "can't tell which card" in world.writes[-1][1]


# A held or fraud-flagged card is only overridden; an inactive one of his is activated first; the office reads which.
def test_held_fraud_and_inactive_cards_are_opened(world):
    for status in ("HOLD", "FRAUD"):
        world.cards["c10001"] = card("c10001", "3189", "JOHN DOE", status)
        assert "try again now" in said(task().declined_card({}))
        assert world.activated == [] and f"Its status is {status}" in world.writes[-1][1]
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE", "INACTIVE")
    t = task()
    assert "try again now" in said(t.declined_card({}))
    assert world.activated == [("c10001", "ACTIVE")] and world.opened[-1] == ("DT", "c10001", 1)
    assert "activated first" in world.writes[-1][1] and "Repeat: the fuel desk opened this card" in world.writes[-1][1]
    assert said(t.reply_to_driver({"text": "Card is ready, try again now."})) == "Sent."


# An activation that worked before the override failed is said to the office: the card is ACTIVE now, not open.
def test_a_failed_opening_after_activating_says_so(world, monkeypatch):
    def refuse(account, row, times):
        raise tools.EfsError("eManager said no")

    monkeypatch.setattr(tools.fuel_cards, "set_override", refuse)
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE", "INACTIVE")
    assert "Opening failed" in said(task().declined_card({}))
    assert "is ACTIVE now, but not open" in world.writes[-1][1]


# A card already open is left as it is and the driver may be told to try again; a card opened by the agent an hour
# ago is opened again; with no card in the driver's name, the one card in use on the unit is opened, an inactive one
# never; and watch-only opens nothing.
def test_open_already_again_another_name_and_watch_only(world, monkeypatch):
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE", override=True)
    t = task()
    assert "already open" in said(t.declined_card({})) and world.opened == []
    assert "nothing changed" in world.writes[-1][1]
    assert said(t.reply_to_driver({"text": "Card is ready, try again now."})) == "Sent."
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE")
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 7, "3189", NOW, "x")
        db.record_agent_open(conn, -100, 7, "c10001", datetime.now(timezone.utc) - timedelta(hours=1))
    assert "try again now" in said(task().declined_card({})) and world.opened == [("DT", "c10001", 1)]
    assert "Repeat" in world.writes[-1][1]
    world.opened.clear()
    del world.cards["c20002"]
    world.cards["c10001"] = card("c10001", "3189", "SOMEONE ELSE")
    assert "try again now" in said(task().declined_card({})) and world.opened == [("DT", "c10001", 1)]
    assert "not in the driver's name" in world.writes[-1][1]
    world.opened.clear()
    world.cards["c10001"] = card("c10001", "3189", "SOMEONE ELSE", "INACTIVE")
    assert "Needs a person" in said(task().declined_card({})) and world.opened == [] and world.activated == []
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE")
    monkeypatch.setattr(cards_settings, "AGENT_ACT", False)
    assert "Watch-only" in said(task().declined_card({})) and world.opened == []
    assert "Would open" in world.writes[-1][1]


# A reply never carries a long number, and never says the card is ready when none was opened.
def test_reply_guards(world):
    t = task()
    assert "Not sent" in said(t.reply_to_driver({"text": "Your driver ID is 445566"}))
    assert "Not sent" in said(t.reply_to_driver({"text": "Card is ready, try again"}))
    assert world.writes == []
    assert said(t.reply_to_driver({"text": "Checking your card, the office will write shortly."})) == "Sent."


# How Claude is called: this PC's Claude Code login (no key), none of Claude Code's own tools or settings, only these
# three tools by their server names, the model and limits from config, the photos as pictures before the text. Its
# thinking is asked for as text, and the run's trace keeps what it thought, used and wrote, in order.
def test_claude_call(world, monkeypatch, tmp_path):
    from features.cards import claude
    seen = {}

    async def fake_query(prompt, options):
        seen["options"] = options
        seen["message"] = [m async for m in prompt]
        yield claude.AssistantMessage(model="m", content=[
            claude.ThinkingBlock(thinking="he is at the pump", signature="s"), claude.ThinkingBlock(thinking="", signature="s"),
            claude.ToolUseBlock(id="1", name="mcp__fuel__declined_card", input={}), claude.TextBlock(text="done")])
        yield claude.ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                                   session_id="s", total_cost_usd=0.01, result="done")

    monkeypatch.setattr(claude, "query", fake_query)
    got = asyncio.run(claude.run("rules", "the chat", [b"\xff\xd8jpg"], task().tools(), tmp_path / "w"))
    options = seen["options"]
    assert got.text == "done" and got.problem == ""
    assert got.trace == (("thought", "he is at the pump"), ("used", "declined_card"), ("said", "done"))
    assert options.thinking == {"type": "adaptive", "display": "summarized"}
    assert options.tools == [] and options.permission_mode == "dontAsk" and options.setting_sources == []
    assert options.allowed_tools == ["mcp__fuel__declined_card", "mcp__fuel__reply_to_driver", "mcp__fuel__hand_to_office"]
    assert options.model == cards_settings.AGENT_MODEL and options.max_turns == claude.MAX_TURNS
    content = seen["message"][0]["message"]["content"]
    assert content[0]["type"] == "image" and content[-1] == {"type": "text", "text": "the chat"}


# What wakes a run: a card request in a truck's group, once. Not its own office or test chat, not a group with no
# truck, not an "ok" to its fuel messages, not the same message twice, not a bare tag right after a request there.
def test_on_tag(world, monkeypatch):
    worked = []

    async def chat_before(client, chat_id, message_id, limit, photos):
        return [ChatLine(message_id, NOW, "John Doe", False, "card declined")]

    async def work(t, chat):
        worked.append((t.chat_id, t.message_id, t.sender))

    monkeypatch.setattr(agent.telegram_agent, "chat_before", chat_before)
    monkeypatch.setattr(agent, "work", work)
    monkeypatch.setattr(agent, "_truck_of", lambda chat_id: (TRUCK, [JOHN]) if chat_id == -100 else (None, []))

    def tag(chat_id: int, msg_id: int, text: str, named: bool = True) -> None:
        asyncio.run(agent.on_tag(None, SimpleNamespace(message=text, chat_id=chat_id, id=msg_id), named))

    tag(-555, 1, "card declined")              # the test group, where its reports go
    tag(-200, 2, "card declined")              # a group linked to no truck
    tag(-100, 3, "ok thanks", named=False)     # an answer to one of its fuel messages
    tag(-100, 4, "card declined at Pilot")
    tag(-100, 4, "card declined at Pilot")     # the same message again
    tag(-100, 5, "@desk")                      # a bare tag right after: joins the request just taken
    assert worked == [(-100, 4, "John Doe")]


# A whole request with Claude faked: recorded with what was done. eManager logged out: the office is told and Claude
# isn't asked. A failure goes to the office and is recorded.
def test_work(world, monkeypatch):
    async def model(system, text, photos, tools, workspace):
        by = {t.name: t for t in tools}
        await by["declined_card"].run({})
        await by["reply_to_driver"].run({"text": "Card is ready, try again now."})
        return SimpleNamespace(text="", problem="", cost_usd=0.01, trace=(("thought", "he is at the pump"),))

    alive = [True]

    async def emanager():
        return alive[0]

    monkeypatch.setattr(agent.claude, "run", model)
    monkeypatch.setattr(agent, "_emanager_alive", emanager)
    monkeypatch.setattr(agent, "prompt", lambda t, chat: "")
    asyncio.run(agent.work(task(), []))
    with db.connect() as conn:
        assert tuple(conn.execute("SELECT outcome, opened_card FROM agent_runs WHERE message_id = 42").fetchone()) == \
            ("opened c10001, replied", "c10001")
        kept = json.loads(conn.execute("SELECT record FROM agent_runs WHERE message_id = 42").fetchone()[0])
    assert kept["trace"] == [["thought", "he is at the pump"]] and kept["sender"] == "John Doe"
    assert [t["tool"] for t in kept["talk"]] == ["declined_card", "reply_to_driver"] and "try again now" in kept["talk"][0]["answer"]

    alive[0] = False
    t = task()
    t.message_id = 43
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 43, "3189", NOW, "x")
    asyncio.run(agent.work(t, []))
    with db.connect() as conn:
        assert "not logged in" in conn.execute("SELECT outcome FROM agent_runs WHERE message_id = 43").fetchone()[0]
    assert "eManager is not logged in" in world.writes[-1][1]

    async def broken(*args):
        raise RuntimeError("Claude Code is not logged in")

    alive[0] = True
    monkeypatch.setattr(agent.claude, "run", broken)
    t.message_id = 44
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 44, "3189", NOW, "x")
    asyncio.run(agent.work(t, []))
    with db.connect() as conn:
        assert conn.execute("SELECT outcome FROM agent_runs WHERE message_id = 44").fetchone()[0] == "failed"
    assert "could not finish" in world.writes[-1][1]


# After its set number of jobs the agent is paused: a card request goes to the office and Claude isn't asked; a
# message with no card words is left without a word. A run that used no tool is not a job.
def test_paused_after_its_jobs(world, monkeypatch):
    asked = []

    async def model(system, text, photos, tools, workspace):
        asked.append(text)
        if "declined" in text:
            await {t.name: t for t in tools}["declined_card"].run({})
        return SimpleNamespace(text="", problem="", cost_usd=0.01, trace=())

    async def alive():
        return True

    monkeypatch.setattr(agent.claude, "run", model)
    monkeypatch.setattr(agent, "_emanager_alive", alive)
    monkeypatch.setattr(agent, "prompt", lambda t, chat: t.text)
    monkeypatch.setattr(cards_settings, "AGENT_MAX_JOBS", 1)
    monkeypatch.setattr(cards_settings, "AGENT_JOBS_SINCE", NOW - timedelta(hours=1))

    def request(message_id: int, text: str) -> tools.Request:
        with db.connect() as conn:
            db.claim_agent_run(conn, -100, message_id, "3189", NOW, text)
        return tools.Request(None, -100, message_id, text, "John Doe", TRUCK, [JOHN])

    asyncio.run(agent.work(request(1, "thanks"), []))             # read only: not a job
    asyncio.run(agent.work(request(2, "card declined"), []))      # the one job
    asyncio.run(agent.work(request(3, "card declined again"), []))
    asyncio.run(agent.work(request(4, "ok thanks"), []))
    assert len(asked) == 2 and world.opened == [("DT", "c10001", 1)]
    assert "done its 1 jobs and is paused" in world.writes[-1][1] and "card declined again" in world.writes[-1][1]
    with db.connect() as conn:
        outcomes = [r[0] for r in conn.execute("SELECT outcome FROM agent_runs WHERE message_id IN (3, 4) ORDER BY message_id")]
    assert outcomes == ["paused after 1 jobs: left for the office"] * 2
