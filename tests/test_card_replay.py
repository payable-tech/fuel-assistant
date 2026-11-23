# Tests the replay's guards: only the test card can be changed, an opening asked for a driver's card lands on the test
# card and is taken off again, the test card is put back, and nothing can be written to Telegram. eManager is a fake.
import asyncio
from dataclasses import replace

import pytest

from base.models import EfsCard, EfsCardRow
from features.cards import replay, settings, telegram_agent
from features.cards.emanager import fuel_cards

TEST = EfsCardRow(settings.TEST_CARD_ID, "708305******0672", "1", settings.TEST_CARD_UNIT, "99999", "ALIF UZ CORP", "", "INACTIVE")
JOHNS = EfsCardRow("c10001", "556748******0001", "1", "3189", "4455", "JOHN DOE", "", "ACTIVE")


# A card page in a given state.
def page(card_id: str, status: str, override: bool = False) -> EfsCard:
    return EfsCard(card_id, status, "POLICY", "CARD", "POLICY", "1", "", "Oct 1, 2029", "", override, ())


# A fake eManager holding the test card and John's card, with every change written down.
@pytest.fixture
def emanager(monkeypatch):
    state = {TEST.card_id: page(TEST.card_id, "INACTIVE"), JOHNS.card_id: page(JOHNS.card_id, "ACTIVE")}
    changes = []

    # Writes a change down and applies it to the fake card.
    def change(name, card_id, **new):
        changes.append((name, card_id))
        state[card_id] = replace(state[card_id], **new)
        return state[card_id]

    monkeypatch.setattr(fuel_cards, "cards", lambda account, by="all", text="": [TEST] if text == settings.TEST_CARD_UNIT else [JOHNS])
    monkeypatch.setattr(fuel_cards, "card", lambda account, row: state[row.card_id])
    monkeypatch.setattr(fuel_cards, "set_status", lambda account, row, status: change("status " + status, row.card_id, status=status))
    monkeypatch.setattr(fuel_cards, "set_override", lambda account, row, times, hand_enter=False: change("open", row.card_id, override=True))
    monkeypatch.setattr(fuel_cards, "remove_override", lambda account, row: change("close", row.card_id, override=False))
    monkeypatch.setattr(fuel_cards, "set_prompt", lambda account, row, prompt, value: change("prompt", row.card_id))
    for name in replay.CHANGERS:  # the guard, put on for this test only
        monkeypatch.setattr(fuel_cards, name, replay._guarded(getattr(fuel_cards, name)))
    return changes


# The guard: a change of any card but the test card is refused, whichever changer is used.
def test_only_the_test_card_can_change(emanager):
    for call in (lambda: fuel_cards.set_override("DT", JOHNS, 1), lambda: fuel_cards.set_status("DT", JOHNS, "HOLD"),
                 lambda: fuel_cards.remove_override("DT", JOHNS), lambda: fuel_cards.set_prompt("DT", JOHNS, "unit", "1"),
                 lambda: fuel_cards.set_override("DT", TEST, 1)):  # the test card's id in the wrong account
        with pytest.raises(replay.ReplayError):
            call()
    assert emanager == []
    fuel_cards.set_status(settings.TEST_CARD_ACCOUNT, TEST, "ACTIVE")
    assert emanager == [("status ACTIVE", TEST.card_id)]


# An opening asked for John's card is made on the test card (activated first, opened, closed again), John's card is
# never touched, and the agent is told his card is open. Afterwards the test card is put back as it was found.
def test_an_opening_lands_on_the_test_card_and_it_is_put_back(emanager):
    row, before = replay.test_card()
    assert replay.at_rest(row, before)
    cards = replay.OnTestCard(row, before)
    told = cards.set_override("DT", JOHNS, 1)
    assert told.card_id == JOHNS.card_id and told.override
    assert emanager == [("status ACTIVE", TEST.card_id), ("open", TEST.card_id), ("close", TEST.card_id)]
    cards.set_override("DT", JOHNS, 1)  # the next case: already active
    assert emanager[3:] == [("open", TEST.card_id), ("close", TEST.card_id)]
    cards.restore()
    assert emanager[-1] == ("status INACTIVE", TEST.card_id) and replay.at_rest(*replay.test_card())
    assert all(card_id == TEST.card_id for _, card_id in emanager)


# The test card not at rest (someone left it active): seen before anything starts.
def test_a_test_card_not_at_rest_is_seen(emanager):
    fuel_cards.set_status(settings.TEST_CARD_ACCOUNT, TEST, "ACTIVE")
    assert not replay.at_rest(*replay.test_card())


# What the agent would write is kept in a list, and no Telegram login can be opened.
def test_nothing_reaches_telegram(monkeypatch):
    written = []
    for module, name in ((telegram_agent, "write"), (telegram_agent, "_client"), (replay.telegram, "send"), (replay.telegram, "_client")):
        monkeypatch.setattr(module, name, getattr(module, name))  # put back after the test
    replay.no_telegram(written)
    asyncio.run(telegram_agent.write(None, -100, "Card is ready, try again now.", reply_to=42))
    assert written == [(-100, "Card is ready, try again now.", 42)]
    with pytest.raises(replay.ReplayError):
        telegram_agent._client()
    with pytest.raises(replay.ReplayError):
        replay.telegram.send(-100, "x")


# The report's one-word kind of each case, and the page escapes what came from Telegram.
def test_report_kinds_and_escaping():
    base = {"unit": "3189", "at": "2026-11-20T14:00:00+00:00", "age_days": 3, "chat": ["John: <b>card</b> declined"],
            "after": [], "outcome": "x", "reply": None, "office": [], "steps": []}
    assert replay.kind(base | {"steps": ["declined_card: opened card …0001 for 1 fill"]}) == "opened"
    assert replay.kind(base | {"steps": ["declined_card: needs a person, 0 cards"]}) == "to the office"
    assert replay.kind(base | {"error": "RuntimeError('x')"}) == "failed"
    assert replay.kind(base | {"reply": "ok"}) == "replied only" and replay.kind(base) == "did nothing"
    text = replay.page([base], 0)
    assert "&lt;b&gt;card&lt;/b&gt;" in text and "<b>card</b>" not in text
