# Tests the Accounting view: which page-1 row a line belongs to, joining lines to Datatruck, the tree's boxes and
# checks, the checks on the fills (the statement in numbers, Love's promise), and the numbers read from the database.
from dataclasses import replace

import pytest

import config
import dashboard
import db
from core import accounting, fill_checks
from models import EfsLine, EfsStatement, FuelLine


# A statement line; only what a test cares about is given.
def line(seq, description="ULTRA LOW", amount=100.0, quantity=20.0, day="2026-11-10", fee=0.0, state="TX", unit="") -> EfsLine:
    return EfsLine("1", seq, f"{seq}-1", day, unit, "", state, description, quantity, amount, fee)


# A Datatruck fuel line; only what a test cares about is given.
def dt(line_id, amount=100.0, gallons=20.0, day="2026-11-10", location="LOVES #1", billable=True, company="TAYLOR",
       state="TX", unit=None, product="ULSD") -> FuelLine:
    return FuelLine(line_id, f"{day} 10:00", "fuel", product, gallons, amount + 10, amount, 0.0, billable, location, "",
                    state, company, unit, None, None, None, None, None)


# The tree as the dashboard builds it: the purchases joined to Datatruck first.
def build(statement, lines, datatruck, companies) -> dict:
    found = accounting.match([l for l in lines if accounting.is_purchase(l)], datatruck)
    return accounting.tree(statement, lines, found, datatruck, companies)


# The statement in numbers: swipes (one per transaction number), diesel fills and gallons, trucks and drivers found
# in Datatruck, money codes.
def test_headline():
    lines = [line(0), line(1, "DIESEL EXHAUST", 10.0, 2.0), line(2, quantity=30.0), line(3, "MONEY CODE", 500.0, 1.0)]
    lines[1] = replace(lines[1], tn=lines[0].tn)  # diesel and DEF in one swipe
    found = {0: dt(10, unit="7"), 1: dt(11, unit="7"), 2: dt(12, unit="9")}
    found = {seq: replace(f, driver_id=1) for seq, f in found.items()}
    assert fill_checks.headline(lines, found) == {"swipes": 2, "diesel_fills": 2, "diesel_gallons": 50.0, "units": 2,
                                                  "drivers": 1, "money_codes": 1}


# Love's fills against that day's sheet: to the cent is as promised; above it counts its dollars over; a store not on
# the sheet is no deal (the discount missed at that day's average); a day with no sheet can't be checked; others are
# left out.
def test_loves_promise():
    lines = [line(0, amount=110.0), line(1, amount=111.0), line(2, amount=110.0), line(3, amount=110.0, day="2026-11-12"),
             line(4, amount=110.0)]
    found = {0: dt(10, location="LOVES #1"), 1: dt(11, location="LOVES #1"), 2: dt(12, location="LOVES #2"),
             3: dt(13, location="LOVES #1", day="2026-11-12"), 4: dt(14, location="PILOT #9")}
    sheets = {"2026-11-10": {"1": 5.5}}  # 20 gal at $5.50 = $110
    result = fill_checks.loves_promise(lines, found, sheets, {"2026-11-10": 0.8})
    groups = {g["verdict"]: (g["fills"], g["off"]) for g in result["groups"]}
    assert groups[fill_checks.AS_PROMISED] == (1, 0.0)
    assert groups[fill_checks.MORE] == (1, 1.0)
    assert groups[fill_checks.NO_DEAL] == (1, 16.0)  # 20 gal at 80¢
    assert groups[fill_checks.NO_SHEET] == (1, None)
    assert [f["verdict"] for f in result["odd"]] == [fill_checks.NO_DEAL, fill_checks.MORE]  # most dollars first


# Each line goes to page 1's row EFS puts it in; a money code below zero is a credit.
def test_row_of():
    assert accounting.row_of(line(0, "ULTRA LOW")) == "DIESEL TOTAL"
    assert accounting.row_of(line(0, "PRODUCT [FUEL]")) == "DIESEL TOTAL"
    assert accounting.row_of(line(0, "DIESEL EXHAUST")) == "DIESEL EXHAUST FLUID"
    assert accounting.row_of(line(0, "SCALES")) == "SCALE"
    assert accounting.row_of(line(0, "PRODUCT [MERC]")) == "MERCHANDISE"
    assert accounting.row_of(line(0, "PRODUCT [UNRG]")) == "UNLEADED TOTAL"
    assert accounting.row_of(line(0, "MONEY CODE", 500.0)) == "MONEY CODE TOTAL"
    assert accounting.row_of(line(0, "MONEY CODE", -40.0)) == "TOTAL CREDITS"
    assert accounting.row_of(line(0, "MONTHLY ACCT")) == "OTHER"


# Same day, gallons and dollars first; then same gallons with other dollars (a sales tax folded in); then a day off.
# A Datatruck line is used once, and one in the same state wins among equals.
def test_match():
    lines = [line(0), line(1, amount=101.74), line(2, day="2026-11-11", quantity=30.0), line(3, quantity=55.0)]
    datatruck = [dt(10, state="OK"), dt(11), dt(12), dt(13, gallons=30.0, day="2026-11-10")]
    found = accounting.match(lines, datatruck)
    assert found[0].line_id == 11  # same state first
    assert found[1].line_id in (10, 12)  # dollars differ, gallons agree
    assert found[2].line_id == 13  # a day before
    assert 3 not in found  # nothing with 55 gallons
    assert len({f.line_id for f in found.values()}) == len(found)


# Two $15.25 scales on one day: each statement line gets the Datatruck line of its own unit, whatever the order.
def test_match_same_unit_first():
    lines = [line(0, "SCALES", 15.25, 1.0, unit="555"), line(1, "SCALES", 15.25, 1.0, unit="777")]
    found = accounting.match(lines, [dt(10, 15.25, 1.0, unit="777"), dt(11, 15.25, 1.0, unit="555")])
    assert (found[0].line_id, found[1].line_id) == (11, 10)


# Badges' figures: lines found and not, Datatruck's dollars minus the statement's, and on top the account's Datatruck
# lines on no statement line (another company's left out); money codes and fees carry none; unknown companies: not checked.
def test_tree_versus_datatruck():
    statement = EfsStatement("1", "ACCT", "2026-11-15", 410.0, (("DIESEL TOTAL", 400.0), ("TRANSACTION FEE TOTAL", 10.0)))
    lines = [line(0, amount=100.0), line(1, amount=101.74, quantity=30.0, fee=10.0), line(2, amount=198.26, quantity=9.0)]
    datatruck = [dt(10, 100.0), dt(11, 100.0, 30.0), dt(12, 1.74, 1.0, product="STAX"), dt(13, 50.0, 5.0, company="OTHER CO")]
    root = build(statement, lines, datatruck, ("TAYLOR",))
    assert root["datatruck"] == {"found": 2, "missing": 1, "off": -1.74, "extra": 1, "extra_dollars": 1.74, "extra_items": {"STAX": 1}}
    diesel, fees = root["children"]
    assert diesel["datatruck"] == {"found": 2, "missing": 1, "off": -1.74} and "datatruck" not in fees
    assert build(statement, lines, datatruck, None)["datatruck"]["extra"] is None


# Top: the charges; under it page 1's rows with EFS's figures; diesel splits by where, who pays and company; a line
# Datatruck doesn't have stops at "Not in Datatruck"; the fees split by the row of the line they are on.
def test_tree():
    statement = EfsStatement("1", "ACCT", "2026-11-15", 1015.0, (("DIESEL TOTAL", 300.0), ("MONEY CODE TOTAL", 700.0),
                                                                    ("TRANSACTION FEE TOTAL", 15.0)))
    lines = [line(0, amount=100.0), line(1, amount=150.0, quantity=30.0), line(2, amount=50.0, quantity=9.0),
             line(3, "MONEY CODE", 700.0, 1.0, fee=15.0)]
    datatruck = [dt(10, 100.0, 20.0), dt(11, 150.0, 30.0, location="PILOT #5", billable=False, company="VKL")]
    root = build(statement, lines, datatruck, ("TAYLOR", "VKL"))
    assert root["label"] == "Current charges" and root["amount"] == 1015.0 and "check" not in root
    assert [(b["label"], b["amount"]) for b in root["children"]] == [("Diesel", 300.0), ("Money codes", 700.0), ("Transaction fees", 15.0)]
    diesel = root["children"][0]
    assert diesel["gallons"] == 59.0 and "check" not in diesel
    assert (diesel["pump_per_gal"], diesel["discount_per_gal"]) == (5.4, 0.4)  # over the 50 gal found: $270 at the pump, $250 billed
    where = {b["label"]: b for b in diesel["children"]}
    assert where["Elsewhere"]["amount"] == 150.0 and where["Not in Datatruck"]["children"] == []
    assert "pump_per_gal" not in where["Not in Datatruck"] and "pump_per_gal" not in root["children"][1]
    payer = where["Love's"]["children"][0]
    assert payer["label"] == "Charged back to drivers" and payer["children"][0]["label"] == "TAYLOR"
    assert where["Elsewhere"]["children"][0]["label"] == "Company"
    assert root["children"][1]["children"] == []  # money codes: not split
    assert root["children"][2]["children"][0]["label"] == "Money codes" and root["children"][2]["children"][0]["amount"] == 15.0


# A row whose lines don't add up to EFS's figure carries how far off they are; so does the top when the rows don't.
def test_tree_checks():
    statement = EfsStatement("1", "ACCT", "2026-11-15", 120.0, (("DIESEL TOTAL", 110.0),))
    root = build(statement, [line(0, amount=100.0)], [], None)
    assert root["check"] == -10.0 and root["children"][0]["check"] == -10.0


# The view's numbers: nothing read yet; the newest statement when none is asked for; an unknown one is a 404.
def test_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    assert dashboard.accounting_payload(None) == {"statements": [], "statement": None, "tree": None, "checks": None}
    with db.connect() as conn:
        for no, day in (("7", "2026-11-08"), ("8", "2026-11-15")):
            s = EfsStatement(no, "ACCT", day, 100.0, (("DIESEL TOTAL", 100.0),))
            db.add_statement(conn, f"{no}.pdf", 1, 1.0, s, [EfsLine(no, 0, "1-1", day, "", "", "TX", "ULTRA LOW", 20.0, 100.0, 0.0)])
        db.replace_fuel_lines(conn, [dt(10, day="2026-11-15")])
    p = dashboard.accounting_payload(None)
    assert [s["statement_no"] for s in p["statements"]] == ["8", "7"]
    assert p["statement"]["first_day"] == "2026-11-15" and p["tree"]["children"][0]["children"][0]["label"] == "Love's"
    assert dashboard.accounting_payload("7")["statement"]["statement_no"] == "7"
    with pytest.raises(LookupError):
        dashboard.accounting_payload("9")


# A statement read again (same number, a new file) replaces the old one with its lines.
def test_statement_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    s = EfsStatement("8", "ACCT", "2026-11-15", 100.0, (("DIESEL TOTAL", 100.0),))
    with db.connect() as conn:
        db.add_statement(conn, "a.pdf", 1, 1.0, s, [EfsLine("8", 0, "1-1", "2026-11-15", "", "", "TX", "ULTRA LOW", 20.0, 100.0, 0.0)] * 1)
        db.add_statement(conn, "b.pdf", 2, 2.0, s, [])
        assert db.statement_files(conn) == {"b.pdf": (2, 2.0)}
        assert db.statement(conn, "8") == (s, [])
