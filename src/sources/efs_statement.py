# EFS weekly statements: the PDF EFS makes for each account, saved by hand into data/efs. Reads page 1's figures and
# every line after it. Only text PDFs (EFS's own download) are read: a scanned copy has no text and is refused.
import re
from datetime import date
from pathlib import Path

import pdfplumber

import config
from models import EfsLine, EfsStatement

TN = re.compile(r"^\d{8,10}-\d{9,10}$")    # a transaction number, "1603707497-1402758361"; payments and adjustments differ
DAY = re.compile(r"^\d\d/\d\d$")
NUM = re.compile(r"^-?[\d,]*\.\d+$")
UNIT = re.compile(r"^\d{3,6}$")
STATE = re.compile(r"^[A-Z]{2}$")
# The remittance coupon's line: statement date, customer no., statement no., due date, amount due.
COUPON = re.compile(r"(\d\d)/(\d\d)/(\d{4}) \d{10,} (\d{9}) \d\d/\d\d/\d{4} (-?[\d,]+\.\d\d)")
ACCOUNT = re.compile(r"Customer Number\s*\n(.+?) \d{10,}")
CHARGES = re.compile(r"Current Charges (-?[\d,]+\.\d\d)")
# A row of page 1's Transaction Summary: its name, then a quantity and dollars, or dollars alone.
SUMMARY_ROW = re.compile(r"^([A-Z][A-Z ]*[A-Z]) (-?[\d,]*\.\d+)(?: (-?[\d,]*\.\d+))?", re.M)
TOTALS = ("CURRENT CHARGES", "TRANSACTION TOTAL")  # page 1's sums of the rows, not rows
NEAR_PT = 4.5  # a word belongs to the line whose transaction number is within this many points up or down


# The statement PDFs saved in data/efs.
def files() -> list[Path]:
    return sorted(config.STATEMENTS_DIR.glob("*.pdf"))


# Reads one statement: page 1's figures and every line on the pages after it. ValueError when the file isn't a
# readable EFS statement.
def read(path: Path) -> tuple[EfsStatement, list[EfsLine]]:
    try:
        with pdfplumber.open(path) as pdf:
            statement = front_page(_plain(pdf.pages[0].extract_text() or ""))
            found = [row for page in pdf.pages[1:] for row in rows(_words(page))]
    except Exception as error:  # a broken or locked file (pdfplumber's errors) or a page 1 that isn't EFS's: one kind to report
        raise ValueError(f"{path.name}: {error}") from error
    if not found:
        raise ValueError(f"{path.name}: no statement lines found (a scanned copy? save the PDF from EFS instead)")
    lines = [_line(statement, seq, row) for seq, row in enumerate(found)]
    return statement, lines


# Page 1's figures: the account, statement number and date, Current Charges and the Transaction Summary rows.
def front_page(text: str) -> EfsStatement:
    coupon, account, charges = COUPON.search(text), ACCOUNT.search(text), CHARGES.search(text)
    if not (coupon and account and charges):
        raise ValueError("page 1 is not an EFS statement's (no remittance coupon, customer or current charges)")
    month, day, year, number, _ = coupon.groups()
    block = text[text.find("Transaction Summary"):]
    summary = tuple((name, _num(b or a)) for name, a, b in SUMMARY_ROW.findall(block) if name not in TOTALS)
    return EfsStatement(statement_no=number, account=account.group(1).strip(), statement_day=f"{year}-{month}-{day}",
                        charges=_num(charges.group(1)), summary=summary)


# The lines on one page, from its words (text with x/top positions): one per transaction number, with the words on
# its row sorted into columns by where they sit. The second line of a description ("SULFUR DIESEL") is left out.
def rows(words: list[dict]) -> list[dict]:
    anchors = sorted((w for w in words if TN.match(w["text"])), key=lambda w: w["top"])
    found = [{"tn": a["text"], "top": a["top"], "unit": "", "city": "", "state": "", "day": "", "description": "",
              "quantity": 0.0, "amount": 0.0, "fee": 0.0} for a in anchors]
    for w in words:
        if not found or TN.match(w["text"]):
            continue
        row = min(found, key=lambda r: abs(r["top"] - w["top"]))
        if abs(row["top"] - w["top"]) <= NEAR_PT:
            _place(row, w)
    return [r for r in found if r["day"]]


# Puts one word into its column of a row, by its position on the page (EFS's layout, measured on its statements).
def _place(row: dict, w: dict) -> None:
    text, x0 = w["text"], w["x0"]
    if NUM.match(text) and x0 >= 500:
        column = _number_column(w["x1"])
        if column:
            row[column] = _num(text)
    elif x0 < 120 and UNIT.match(text):
        row["unit"] = text
    elif 120 <= x0 < 198:
        row["city"] = f"{row['city']} {text}".strip()
    elif 198 <= x0 < 214 and STATE.match(text):
        row["state"] = text
    elif 300 < x0 < 340 and DAY.match(text):
        row["day"] = text
    elif 440 <= x0 < 515:
        row["description"] = f"{row['description']} {text}".strip()


# Which number column a right-aligned number is in, by its right edge; None for the ones not kept (unit cost, taxes).
def _number_column(x1: float) -> str | None:
    if x1 < 605:
        return None  # unit cost, state and federal tax: already inside the line's total
    if x1 < 650:
        return "fee"
    if x1 < 705:
        return "quantity"
    return "amount"


# One parsed row as a statement line. Its day takes the statement's year, or the year before for a December line on
# a January statement.
def _line(statement: EfsStatement, seq: int, row: dict) -> EfsLine:
    month, day = int(row["day"][:2]), int(row["day"][3:])
    stated = date.fromisoformat(statement.statement_day)
    year = stated.year - 1 if month > stated.month else stated.year
    return EfsLine(statement_no=statement.statement_no, seq=seq, tn=row["tn"], day=date(year, month, day).isoformat(),
                   unit=row["unit"], city=row["city"], state=row["state"], description=row["description"],
                   quantity=row["quantity"], amount=row["amount"], fee=row["fee"])


# A page's words with their positions, minus signs made plain.
def _words(page) -> list[dict]:
    return [w | {"text": _plain(w["text"])} for w in page.extract_words(x_tolerance=1.5, y_tolerance=2)]


# EFS prints minus signs and dashes as soft hyphens: makes them plain.
def _plain(text: str) -> str:
    return text.replace("\xad", "-")


# A printed number as a float: "1,234.50" -> 1234.5, "-.248" -> -0.248.
def _num(text: str) -> float:
    return float(text.replace(",", ""))
