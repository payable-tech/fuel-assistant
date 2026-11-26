# The card checker (features/cards/card_check and its rules): what Claude is shown, which answers can be saved, and a
# round over the ACTIVE cards with Telegram and Claude replaced by fakes. Nothing is sent anywhere.
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from base import config
from base.models import ChatLine, EfsCardRow, Order, Truck
from base.store import db
from features.cards import card_check, card_check_rules as rules, claude

NOW = datetime(2026, 11, 26, 14, 0, tzinfo=timezone.utc)  # 08:00 Central


# A truck as the fleet view gives it: a unit, its group (or none) and its last position.
def truck(unit: str, chat_id: int | None) -> Truck:
    return Truck(unit, f"s{unit}", f"V{unit}", f"TTL {unit}", "ALI", None, None, None, None, None, "Dallas, TX",
                 NOW - timedelta(hours=3), None, None, None, chat_id, "auto" if chat_id else None, None, False)


CARD = {"account": "ALIF", "card_id": "c0050", "last4": "0050", "status": "ACTIVE", "unit": "1518", "driver_id": "1518",
        "driver_name": "DREPSON JACQUES", "last_used": "2026-11-24", "override": 0, "dt_card_id": 7, "dt_assigned_to": "driver",
        "dt_driver": "Drepson Jacques", "dt_driver_status": "active", "dt_unit": "1518"}


# Claude is shown the card, Datatruck's driver, the truck's load and position, then the group oldest first, in Central
# time, with how long the group has been quiet.
def test_what_claude_is_shown():
    lines = [ChatLine(1, NOW - timedelta(days=2, hours=1), "Drepson Jacques", False, "dropped the truck at the yard, going home"),
             ChatLine(2, NOW - timedelta(days=2), "Bob", True, "ok, safe trip")]
    order = Order(9, "576378385", "in_transit", "1518", datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc), ())
    text = rules.facts(CARD, "1518", truck("1518", -100), [order], lines, NOW)
    assert "Now: Nov 26 08:00 CT." in text and "Card …0050 (ALIF), ACTIVE in EFS." in text
    assert "EFS last saw it used: Nov 24 (2 days ago)." in text
    assert "Datatruck assigns this card to Drepson Jacques (an active driver), on unit 1518." in text
    assert "Truck 1518: load 576378385 in transit (pickup Nov 25 08:00)." in text and "Dallas, TX, 3 h ago" in text
    assert "its last 2 messages, oldest first (the newest 2 days ago)" in text
    assert text.index("going home") < text.index("Bob (our account): ok, safe trip")
    left = rules.facts({**CARD, "dt_driver_status": "inactive"}, "1518", None, [], [], NOW)
    assert "a driver who is inactive in Datatruck" in left and "no load in Datatruck" in left and "has no messages" in left


# Only an answer with a known should_be and sure and a short why can be saved; the reason says what to fix.
def test_which_answers_can_be_saved():
    good = {"should_be": "off", "why": "Home time since Nov 24", "sure": "high", "evidence": "x"}
    assert rules.problem(good) == ""
    assert "should_be" in rules.problem({**good, "should_be": "maybe"})
    assert "sure" in rules.problem({**good, "sure": "95%"})
    assert "why" in rules.problem({**good, "why": "x" * 61}) and "why" in rules.problem({**good, "why": " "})


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    efs = lambda card_id, unit, status: EfsCardRow(card_id, f"556748******{card_id[-4:]}", "1", unit, unit, "DRIVER", "", status)
    with db.connect() as conn:
        db.replace_efs_cards(conn, "ALIF", [efs("c0050", "1518", "ACTIVE"), efs("c0060", "777", "ACTIVE"),
                                            efs("c0070", "1518", "INACTIVE"), efs("c0080", "900", "ACTIVE")])
    monkeypatch.setattr(card_check.db, "fleet", lambda conn: [truck("1518", -100), truck("777", None), truck("900", -900)])

    class Client:
        async def disconnect(self):
            pass

    async def checker():
        return Client()

    async def latest(client, chat_id, limit, scan):
        return [ChatLine(1, NOW, "Driver", False, "going home" if chat_id == -100 else "nothing")]

    asked = []

    async def run(system, text, photos, tools, workspace, model, effort):
        asked.append(text)
        if "going home" in text:  # one card's answer is wrong first, then fixed
            assert (await tools[0].run({"should_be": "maybe", "why": "x", "sure": "high"}))["is_error"]
            await tools[0].run({"should_be": "off", "why": "Home time", "sure": "high", "evidence": "'going home' today"})
        return claude.Answer("", "", None)  # the other card's run records nothing

    monkeypatch.setattr(card_check.telegram_agent, "checker", checker)
    monkeypatch.setattr(card_check.telegram_agent, "latest", latest)
    monkeypatch.setattr(card_check.claude, "run", run)
    return asked


# A round checks the ACTIVE cards only: one read and recorded, one with no group saved as unsure without Claude, and one
# whose run recorded nothing keeps no check; the inactive card is not checked.
def test_a_round(world):
    assert card_check.run() == (2, 3)
    assert len(world) == 2  # Claude asked about the two cards whose truck has a group
    with db.connect() as conn:
        checks = {r["card_id"]: (r["should_be"], r["why"], r["sure"]) for r in conn.execute("SELECT * FROM card_checks")}
    assert checks == {"c0050": ("off", "Home time", "high"), "c0060": ("unsure", "No group found", "low")}
    assert card_check.run(unit="777") == (1, 1)


# A card's own group is the open one naming its unit and its driver (the name on the card, or Datatruck's driver),
# even when the truck's linked group is another driver's; the same driver's groups marked INACTIVE are told apart.
# With no own group, the truck's linked group is read; with neither, none.
def test_the_group_read():
    from base.models import TelegramGroup
    groups = [TelegramGroup(-1, "TTL: Devon Jr Robinson (C) | Unit 581583"), TelegramGroup(-2, "TTL: Leonard Wilson (LO) | Unit 581583"),
              TelegramGroup(-3, "**INACTIVE** TTL: Devon Robinson (C) | Unit 581583"), TelegramGroup(-4, "TTL: Ali Vali | Unit 777")]
    card = {**CARD, "unit": "581583", "driver_name": "DEVON JR ROBINSON", "dt_unit": None, "dt_driver": "Julio Millien"}
    group, closed = rules.group_of(card, -2, groups)
    assert group.chat_id == -1 and closed == ["**INACTIVE** TTL: Devon Robinson (C) | Unit 581583"]
    assert rules.group_of({**card, "driver_name": "SOMEONE ELSE"}, -2, groups)[0].chat_id == -2
    assert rules.group_of({**card, "driver_name": "SOMEONE ELSE"}, None, groups) == (None, [])
    text = rules.facts(card, "581583", None, [], [], NOW, group.title, tuple(closed))
    assert 'marked INACTIVE: "**INACTIVE** TTL: Devon Robinson (C) | Unit 581583"' in text
    assert 'The Telegram group "TTL: Devon Jr Robinson (C) | Unit 581583" has no messages.' in text
