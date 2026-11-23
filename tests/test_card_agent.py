# Tests the card agent, built the way bob-agent's agent works: whose card a request is for, the owner's rule for it,
# that the tools hold whatever the model asks (only the truck's driver's own card, opened once for one fill, one
# reply, never a number, every opening reported), what wakes it, and how Claude is called (the Claude Code login, no
# built-in tools). eManager, Telegram and Claude are fakes here.
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from base import config
from base.models import ChatLine, DatatruckDriver, EfsCard, EfsCardRow, Store, Truck
from base.store import db
from features.cards import job, rules
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
    monkeypatch.setattr(config, "AGENT_OFFICE_CHAT_ID", None)
    monkeypatch.setattr(config, "AGENT_ACT", True)
    w = SimpleNamespace(cards={}, opened=[], writes=[])
    for c in (card("c10001", "3189", "JOHN DOE"), card("c20002", "3189", "MARY ROE"), card("c30003", "31890", "JOHN DOE")):
        w.cards[c[0].card_id] = c
    monkeypatch.setattr(job.efs_cards, "cards", lambda account, by, text:
                        [r for r, _ in w.cards.values() if account == "DT" and r.unit.startswith(text)])
    monkeypatch.setattr(job.efs_cards, "card", lambda account, row: w.cards[row.card_id][1])

    def override(account, row, times):
        w.opened.append((account, row.card_id, times))
        return EfsCard(**{**w.cards[row.card_id][1].__dict__, "override": True})

    async def write(client, chat, text, reply_to=None):
        w.writes.append((chat, text, reply_to))
        return 1

    monkeypatch.setattr(job.efs_cards, "set_override", override)
    monkeypatch.setattr(job.telegram_agent, "write", write)
    return w


# A request from unit 3189's group, message 42, written by `sender`.
def task(sender: str = "John Doe", drivers=(JOHN,), text: str = "card declined at Pilot, open please") -> job.Task:
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 42, "3189", NOW, text)
    return job.Task(None, -100, 42, text, sender, TRUCK, list(drivers))


# Runs one of the agent's async tools and returns its answer's text.
def said(call) -> str:
    return asyncio.run(call)["content"][0]["text"]


# Same person: two words in common, or one when a name has one word; Datatruck's brackets don't count.
def test_same_person():
    assert rules.same_person("John Doe", "JOHN DOE (CD team)")
    assert rules.same_person("Johnny", "JOHNNY WALKER")
    assert not rules.same_person("John Smith", "JOHN DOE")
    assert not rules.same_person("", "JOHN DOE")


# Whose card: the one driver; on a team truck the one writing, by name; no clear match goes to a person.
def test_whose():
    assert rules.whose([JOHN], "Big Boss") == JOHN
    assert rules.whose([JOHN, MARY], "Mary Roe") == MARY
    with pytest.raises(NeedsPerson):
        rules.whose([JOHN, MARY], "Dispatch Night")
    with pytest.raises(NeedsPerson):
        rules.whose([], "John")


# Their card: on the unit exactly and in the driver's name; none or two go to a person, with the cards on the unit.
def test_their_card():
    found = [("DT", card("a1", "3189", "JOHN DOE")[0]), ("DT", card("a2", "31890", "JOHN DOE")[0]),
             ("DT", card("a3", "3189", "MARY ROE")[0])]
    assert rules.their_card(found, "3189", JOHN)[1].card_id == "a1"
    with pytest.raises(NeedsPerson, match="0 cards on unit 3189"):
        rules.their_card(found, "3189", DatatruckDriver(9, "SAM NEW", None, "active", "DT", "3189"))


# The owner's table: active and not open, open it; held or inactive, activate then open after a person's yes;
# anything else (already open) goes to a person.
def test_rule():
    row, page = card("c1", "3189", "X")
    assert rules.rule(page, "DT", row) == (rules.OPEN, False)
    assert rules.rule(card("c1", "3189", "X", "HOLD")[1], "DT", row) == (rules.ACTIVATE_AND_OPEN, True)
    with pytest.raises(NeedsPerson, match="override already on"):
        rules.rule(card("c1", "3189", "X", override=True)[1], "DT", row)
    assert rules.too_soon(NOW - timedelta(hours=2), NOW, 6) and rules.too_soon(NOW - timedelta(hours=7), NOW, 6) is None


# What wakes it and what it is told: a tag by name, or a card request answering it; facts with no driver ID.
def test_woken_and_facts():
    assert rules.woken("thanks", True) and not rules.woken("ok thanks", False) and rules.woken("card declined", False)
    assert rules.only_a_tag("@desk ") and not rules.only_a_tag("@desk card")
    text = rules.facts(TRUCK, [JOHN], "watch", [Store("7", "Seguin", "TX", 30.0, -96.6, 6.0, 5.5, "2026-11-23")], [], NOW)
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


# On a team truck the card of the one writing is opened; someone not clearly a driver goes to the office.
def test_team_truck(world):
    assert "try again" in said(task("Mary Roe", (JOHN, MARY)).declined_card({}))
    assert world.opened == [("DT", "c20002", 1)]
    world.opened.clear()
    assert "Needs a person" in said(task("Night Dispatch", (JOHN, MARY)).declined_card({}))
    assert world.opened == [] and "not clearly one of them" in world.writes[-1][1]


# A held card goes to the office (activating is a person's yes); one opened by the agent hours ago too; and
# watch-only opens nothing.
def test_held_soon_and_watch_only(world, monkeypatch):
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE", "HOLD")
    assert "being checked" in said(task().declined_card({})) and world.opened == []
    world.cards["c10001"] = card("c10001", "3189", "JOHN DOE")
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 7, "3189", NOW, "x")
        db.record_agent_open(conn, -100, 7, "c10001", datetime.now(timezone.utc) - timedelta(hours=1))
    assert "Needs a person" in said(task().declined_card({})) and world.opened == []
    with db.connect() as conn:
        conn.execute("UPDATE agent_runs SET opened_card = NULL")
    monkeypatch.setattr(config, "AGENT_ACT", False)
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
# four tools by their server names, the model and limits from config, the photos as pictures before the text.
def test_claude_call(world, monkeypatch, tmp_path):
    from features.cards import claude
    seen = {}

    async def fake_query(prompt, options):
        seen["options"] = options
        seen["message"] = [m async for m in prompt]
        yield claude.ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                                   session_id="s", total_cost_usd=0.01, result="done")

    monkeypatch.setattr(claude, "query", fake_query)
    got = asyncio.run(claude.run("rules", "the chat", [b"\xff\xd8jpg"], task().tools(), tmp_path / "w"))
    options = seen["options"]
    assert got.text == "done" and got.problem == ""
    assert options.tools == [] and options.permission_mode == "dontAsk" and options.setting_sources == []
    assert options.allowed_tools == ["mcp__fuel__declined_card", "mcp__fuel__look_up_card", "mcp__fuel__reply_to_driver",
                                     "mcp__fuel__hand_to_office"]
    assert options.model == config.AGENT_MODEL and options.max_turns == claude.MAX_TURNS
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

    monkeypatch.setattr(job.telegram_agent, "chat_before", chat_before)
    monkeypatch.setattr(job, "work", work)
    monkeypatch.setattr(job, "_truck_of", lambda chat_id: (TRUCK, [JOHN]) if chat_id == -100 else (None, []))

    def tag(chat_id: int, msg_id: int, text: str, named: bool = True) -> None:
        asyncio.run(job.on_tag(None, SimpleNamespace(message=text, chat_id=chat_id, id=msg_id), named))

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
        return SimpleNamespace(text="", problem="", cost_usd=0.01)

    alive = [True]

    async def emanager():
        return alive[0]

    monkeypatch.setattr(job.claude, "run", model)
    monkeypatch.setattr(job, "_emanager_alive", emanager)
    monkeypatch.setattr(job, "prompt", lambda t, chat: "")
    asyncio.run(job.work(task(), []))
    with db.connect() as conn:
        assert tuple(conn.execute("SELECT outcome, opened_card FROM agent_runs WHERE message_id = 42").fetchone()) == \
            ("opened c10001, replied", "c10001")

    alive[0] = False
    t = task()
    t.message_id = 43
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 43, "3189", NOW, "x")
    asyncio.run(job.work(t, []))
    with db.connect() as conn:
        assert "not logged in" in conn.execute("SELECT outcome FROM agent_runs WHERE message_id = 43").fetchone()[0]
    assert "eManager is not logged in" in world.writes[-1][1]

    async def broken(*args):
        raise RuntimeError("Claude Code is not logged in")

    alive[0] = True
    monkeypatch.setattr(job.claude, "run", broken)
    t.message_id = 44
    with db.connect() as conn:
        db.claim_agent_run(conn, -100, 44, "3189", NOW, "x")
    asyncio.run(job.work(t, []))
    with db.connect() as conn:
        assert conn.execute("SELECT outcome FROM agent_runs WHERE message_id = 44").fetchone()[0] == "failed"
    assert "could not finish" in world.writes[-1][1]
