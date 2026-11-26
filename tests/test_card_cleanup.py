# The card cleanup: its rule (each Datatruck unit keeps its card, a card in use on no Datatruck unit is left for a
# person, every other card is parked), and parking and putting back on a pretend eManager.
import csv
from dataclasses import replace
from types import SimpleNamespace

import pytest

from base.models import EfsCard, EfsCardRow
from features.cards import cleanup, cleanup_rules as rules
from features.cards.emanager.window import EfsError

DRIVERS = {"3189": ["JOHN DOE (CD team)"], "4100": []}   # Datatruck units with their active drivers
LISTED = {("3189", "0806")}                               # cards Datatruck lists on a unit: unit, last 4


# Decides one card with the test's units.
def decide(status, unit, last4="1111", name=None, driver_id=None):
    return rules.decide(status, unit, last4, name, driver_id, DRIVERS, LISTED)[0]


# A card in use stays on a Datatruck unit and is left for a person on any other; an inactive card stays only as the
# unit's card (Datatruck lists it, or it is in the name of the unit's driver).
def test_decide():
    assert decide("ACTIVE", "3189") == rules.KEEP and decide("HOLD FOR FRAUD", " 3189 ") == rules.KEEP
    assert decide("ACTIVE", "73148") == rules.LEAVE and decide("HOLD FOR FRAUD", None) == rules.LEAVE
    assert decide("INACTIVE", "3189", "0806") == rules.KEEP
    assert decide("INACTIVE", "3189", name="JOHN DOE") == rules.KEEP
    assert decide("INACTIVE", "3189", name="MARY ROE") == rules.PARK      # an earlier driver's card
    assert decide("INACTIVE", "4100", "0806") == rules.PARK               # listed on another unit
    assert decide("INACTIVE", "555", name="JOHN DOE") == rules.PARK       # on no Datatruck unit


# A card is parked already only with all three prompts parked; a driver ID not known doesn't count against it, and an
# active card on 99999 is left for a person.
def test_parked_already():
    assert decide("INACTIVE", "99999", name="ALIF UZ CORP") == rules.PARKED
    assert decide("INACTIVE", "99999", name="alif uz corp", driver_id="99999") == rules.PARKED
    assert decide("INACTIVE", "99999", name="ALIF UZ CORP", driver_id="445566") == rules.PARK
    assert decide("INACTIVE", "99999", name="JOHN DOE") == rules.PARK
    assert decide("ACTIVE", "99999", name="ALIF UZ CORP") == rules.LEAVE


# The units whose cards are all parked end with no card.
def test_left_without_card():
    assert rules.left_without_card(DRIVERS, {"3189"}) == ["4100"]


# A pretend eManager with three cards in ALIF: an old driver's (c1), one in override mode (c2), one in use now (c3);
# the plan says to park all three. Every prompt change is noted, and a change can be made to fail.
@pytest.fixture
def efs(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup, "PLAN_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "LOG", tmp_path / "log.csv")
    monkeypatch.setattr(cleanup.window, "LOCK", tmp_path / "efs-window.lock")
    monkeypatch.setattr(cleanup, "GIVE_WAY_S", 0)
    monkeypatch.setattr(cleanup, "_datatruck", lambda: (DRIVERS, LISTED))
    w = SimpleNamespace(cards={}, set=[], fail=None)
    for card_id, status, override in (("c1", "INACTIVE", False), ("c2", "INACTIVE", True), ("c3", "ACTIVE", False)):
        prompts = (("Unit Number", "Exact Match", "3189"), ("Driver ID", "Exact Match", "4455"),
                   ("Driver Name", "Report Only", "MARY ROE"))
        w.cards[card_id] = (EfsCardRow(card_id, f"556748******000{card_id[-1]}", "1", "3189", "4455", "MARY ROE", "",
                                       status),
                            EfsCard(card_id, status, "POLICY", "CARD", "POLICY", "1", "", "Oct 1, 2029", "Nov 2, 2026",
                                    override, prompts, tuple(n for n, _, _ in prompts)))

    # One prompt change on the pretend card: noted, its row and page updated, or the failure asked for.
    def set_prompt(account, row, prompt, value):
        if w.fail == prompt:
            raise EfsError("eManager did not change it")
        w.set.append((row.card_id, prompt, value))
        old_row, page = w.cards[row.card_id]
        field = {"unit": "unit", "driver-id": "driver_id", "driver": "driver_name"}[prompt]
        label = cleanup.LABELS[prompt]
        w.cards[row.card_id] = (replace(old_row, **{field: value}),
                                replace(page, prompts=tuple((n, c, value if n == label else v) for n, c, v in page.prompts)))
        return w.cards[row.card_id][1]

    monkeypatch.setattr(cleanup.fuel_cards, "cards", lambda account, by, text="": [r for r, _ in w.cards.values()])
    monkeypatch.setattr(cleanup.fuel_cards, "card", lambda account, row: w.cards[row.card_id][1])
    monkeypatch.setattr(cleanup.fuel_cards, "set_prompt", set_prompt)
    plan = tmp_path / "plan.csv"
    with plan.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, cleanup.COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({"action": rules.PARK, "account": "ALIF", "card_id": c} for c in ("c1", "c2", "c3"))
    w.plan = plan
    return w


# The log's lines, as dicts.
def logged() -> list[dict]:
    with cleanup.LOG.open(encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


# Only the old inactive card is parked, its prompts logged first; the one in override mode is skipped, the one in use
# now is left; a second run finds it parked already.
def test_park(efs):
    done = cleanup.park(efs.plan, most=5)
    assert done == {"parked": 1, "skipped": 1, "left: changed since the plan": 1}
    assert efs.set == [("c1", "unit", "99999"), ("c1", "driver-id", "99999"), ("c1", "driver", "ALIF UZ CORP")]
    lines = logged()
    assert [(l["card_id"], l["event"]) for l in lines] == [("c1", "before"), ("c1", "parked"),
                                                           ("c2", "skipped: in override mode"),
                                                           ("c3", "left: now in use on its unit")]
    assert (lines[0]["unit"], lines[0]["driver_id"], lines[0]["driver_name"]) == ("3189", "4455", "MARY ROE")
    assert cleanup.park(efs.plan, most=5)["parked already"] == 1


# A run parks no more than it is told; a failed change stops the run with the card's prompts already logged.
def test_park_most_and_stop(efs):
    efs.cards["c2"] = (efs.cards["c2"][0], replace(efs.cards["c2"][1], override=False))
    assert cleanup.park(efs.plan, most=1)["parked"] == 1 and {c for c, _, _ in efs.set} == {"c1"}
    efs.fail = "driver"
    with pytest.raises(EfsError):
        cleanup.park(efs.plan, most=5)
    assert [(l["card_id"], l["event"]) for l in logged()][-1] == ("c2", "before")


# A stock card whose unit and driver ID come from its policy has nothing on it to park: it is skipped untouched,
# and later runs leave it without reading it again.
def test_stock_card_is_skipped(efs):
    efs.cards["c1"] = (efs.cards["c1"][0], replace(efs.cards["c1"][1], own_prompts=("Driver Name",)))
    assert cleanup.park(efs.plan, most=5)["skipped"] == 2 and efs.set == []
    assert logged()[0]["event"] == "skipped: Unit Number, Driver ID not on the card (its policy's)"
    cleanup.park(efs.plan, most=5)
    assert [l["card_id"] for l in logged()].count("c1") == 1   # the second run left c1 without reading it


# A parked card is put back as its first "before" line says, and later runs leave it.
def test_undo(efs):
    cleanup.park(efs.plan, most=5)
    efs.set.clear()
    assert cleanup.undo("c1").startswith("Card …0001 put back")
    assert efs.set == [("c1", "unit", "3189"), ("c1", "driver-id", "4455"), ("c1", "driver", "MARY ROE")]
    assert "parked" not in cleanup.park(efs.plan, most=5)
    with pytest.raises(RuntimeError):
        cleanup.undo("c9")
