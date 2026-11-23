# Tests reading EFS statements: page 1's figures, the lines from word positions, the year of a line, a bad file.
from pathlib import Path

import pytest

from base.models import EfsStatement
from features.accounting import efs_statement

PAGE_1 = """Customer Number
ALIF UZ CORP 0006702400100
Transaction Summary Account Summary:
DIESEL TOTAL 61,270.0500 327,509.40 Previous Balance 251,385.18
MONEY CODE TOTAL 174.0000 60,853.93
OTHER 99.99 Adjustments 0.00
TOTAL CREDITS 16.0000 -3,360.10 Statement Amt Due 399,827.24
TRANSACTION FEE TOTAL 502.50 Current Charges 385,605.72
CURRENT CHARGES 385,605.72
TRANSACTION TOTAL 385,605.72
Statement Date Customer No. Statement No. Statement Due Date Statement Amount Due
11/15/2026 0006702400100 102999946 11/17/2026 385,605.72
"""


# Page 1: the account, the statement's number and date, Current Charges and the summary rows (the sums left out).
def test_front_page():
    s = efs_statement.front_page(PAGE_1)
    assert (s.statement_no, s.account, s.statement_day, s.charges) == ("102999946", "ALIF UZ CORP", "2026-11-15", 385605.72)
    assert s.summary == (("DIESEL TOTAL", 327509.4), ("MONEY CODE TOTAL", 60853.93), ("OTHER", 99.99),
                         ("TOTAL CREDITS", -3360.1), ("TRANSACTION FEE TOTAL", 502.5))


# A page 1 that isn't EFS's is refused.
def test_front_page_not_a_statement():
    with pytest.raises(ValueError):
        efs_statement.front_page("Some other PDF")


# A word as pdfplumber gives it: its text, left and right edges and top.
def word(text, x0, top=100.0, x1=None):
    return {"text": text, "x0": x0, "x1": x1 if x1 is not None else x0 + 20, "top": top}


# Words on a transaction number's row land in their columns; the next row's words and a card subtotal don't.
def test_rows():
    words = [word("516947", 60), word("OKEMAH", 130), word("OK", 200), word("1603707497-1402758361", 220), word("11/14", 310),
             word("ULTRA", 445), word("LOW", 470), word("5.0190", 520, x1=540), word(".248", 580, x1=600), word("2.50", 620, x1=640),
             word("46.160", 660, x1=700), word("231.68", 720, x1=740),
             word("SULFUR", 445, top=110), word("DIESEL", 470, top=110), word("334.840", 660, top=130, x1=700)]
    [row] = efs_statement.rows(words)
    assert (row["unit"], row["city"], row["state"], row["day"], row["description"]) == ("516947", "OKEMAH", "OK", "11/14", "ULTRA LOW")
    assert (row["fee"], row["quantity"], row["amount"]) == (2.5, 46.16, 231.68)


# A line's year is the statement's, or the year before for a December line on a January statement.
def test_line_year():
    jan = EfsStatement("1", "A", "2027-01-03", 0.0, ())
    row = {"tn": "1-1", "unit": "", "city": "", "state": "", "day": "12/30", "description": "X", "quantity": 1.0, "amount": 1.0, "fee": 0.0}
    assert efs_statement._line(jan, 0, row).day == "2026-12-30"
    assert efs_statement._line(jan, 0, row | {"day": "01/02"}).day == "2027-01-02"


# A file that isn't a PDF is refused with its name, not a crash.
def test_read_bad_file(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(ValueError, match="x.pdf"):
        efs_statement.read(Path(bad))
