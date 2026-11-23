# Accounting: one EFS statement as a tree of boxes. On top, what the statement charged; under it, EFS's own summary rows
# from page 1; under each row, its lines split further (where, who pays, which company) by joining them to Datatruck.
from collections import Counter
from datetime import date, timedelta

from base import fuel
from base.models import EfsLine, EfsStatement, FuelLine

FEES = "TRANSACTION FEE TOTAL"  # page 1's row for the fees: they sit on the other lines, not lines of their own
# Page 1's row names as people say them; a row not listed keeps EFS's name.
NAMES = {"DIESEL TOTAL": "Diesel", "DIESEL EXHAUST FLUID": "DEF", "MONEY CODE TOTAL": "Money codes", "SCALE": "Scales",
         "MERCHANDISE": "Merchandise", "UNLEADED TOTAL": "Unleaded gas", "OTHER": "Other", "TOTAL CREDITS": "Credits",
         FEES: "Transaction fees"}
# How each row's lines split, level by level, under it. A row not listed is not split.
SPLITS = {"DIESEL TOTAL": ("where", "payer", "company"), "DIESEL EXHAUST FLUID": ("payer", "company"),
          "SCALE": ("payer",), "MERCHANDISE": ("payer",), "UNLEADED TOTAL": ("payer",), "OTHER": ("item",), FEES: ("on",)}
MEASURED = {"DIESEL TOTAL", "DIESEL EXHAUST FLUID", "UNLEADED TOTAL"}  # rows whose quantity is gallons
PURCHASES = MEASURED | {"SCALE", "MERCHANDISE"}  # rows of card purchases: the ones Datatruck has a line for
# The order to look for a line's Datatruck twin: (days off, dollars must agree, unit must agree). The unit keyed at the
# pump is the Datatruck truck on ~90% of lines; it tells apart two $15.25 scales on one day.
TRIES = ((0, True, True), (0, True, False), (0, False, True), (0, False, False),
         (-1, True, True), (1, True, True), (-1, True, False), (1, True, False))
NOT_IN_DATATRUCK = "Not in Datatruck"  # a purchase with no Datatruck line to say more: not split further
DRIVERS, COMPANY = "Charged back to drivers", "Company"


# Which page-1 row a statement line belongs to, from EFS's description (a money code below zero is a credit).
def row_of(line: EfsLine) -> str:
    text = line.description
    if text == "MONEY CODE":
        return "TOTAL CREDITS" if line.amount < 0 else "MONEY CODE TOTAL"
    if "EXHAUST" in text:
        return "DIESEL EXHAUST FLUID"
    if "SCALE" in text:
        return "SCALE"
    if "MERC" in text:
        return "MERCHANDISE"
    if "UNRG" in text:
        return "UNLEADED TOTAL"
    if text in ("ULTRA LOW", "FUEL", "PRODUCT [FUEL]", "PRODUCT [ULSD]"):
        return "DIESEL TOTAL"
    return "OTHER"  # gasoline, account fees (MONTHLY ACCT, DATA SHARE FEE), anything new


# True for a card purchase, a line Datatruck has too (fuel, DEF, scales, store items, gas), not a money code or a fee.
def is_purchase(line: EfsLine) -> bool:
    return row_of(line) in PURCHASES or line.description.startswith("PRODUCT [")


# Joins each card purchase to its Datatruck line, in the order of TRIES: same day, gallons and dollars first; same day
# and gallons (EFS folds a sales-tax line into the fuel line); the same gallons and dollars a day either side (near
# midnight); each with the same unit before any unit. Each Datatruck line is used once; among equals, one in the line's
# state goes first. Returns {line seq: Datatruck line}.
def match(lines: list[EfsLine], datatruck: list[FuelLine]) -> dict[int, FuelLine]:
    by_day_gallons: dict[tuple[str, float], list[FuelLine]] = {}
    for f in datatruck:
        by_day_gallons.setdefault((f.fueled_at[:10], round(f.gallons, 3)), []).append(f)
    used: set[int] = set()
    found: dict[int, FuelLine] = {}
    for shift, same_dollars, same_unit in TRIES:
        for line in lines:
            if line.seq in found:
                continue
            day = (date.fromisoformat(line.day) + timedelta(days=shift)).isoformat()
            hits = [f for f in by_day_gallons.get((day, round(line.quantity, 3)), [])
                    if f.line_id not in used and (not same_dollars or round(f.billed, 2) == round(line.amount, 2))
                    and (not same_unit or f.unit == line.unit)]
            if hits:
                pick = min(hits, key=lambda f: f.state != line.state)
                found[line.seq] = pick
                used.add(pick.line_id)
    return found


# The whole tree for one statement: its charges, page 1's rows under it (EFS's own dollars), and each row's lines split.
# `check` on a box is how far its lines are from EFS's figure for it (left out when they agree). `datatruck` on a box
# with card purchases is how they compare with Datatruck; on the top box it also counts the Datatruck lines of the
# account's `companies` (None: not known) that are on no statement line. A box without it holds only what EFS alone
# has: money codes, credits, fees. `found` is match()'s answer for the statement's purchases.
def tree(statement: EfsStatement, lines: list[EfsLine], found: dict[int, FuelLine], datatruck: list[FuelLine],
         companies: tuple[str, ...] | None) -> dict:
    purchases = [l for l in lines if is_purchase(l)]
    rows = [_row(name, dollars, lines, found) for name, dollars in statement.summary]
    root = {"label": "Current charges", "dim": "statement", "amount": statement.charges, "lines": len(lines), "gallons": None,
            "children": rows, "datatruck": _versus(purchases, found) | _only_in_datatruck(lines, found, datatruck, companies)}
    return root | _check(sum(dollars for _, dollars in statement.summary), statement.charges)


# One page-1 row: EFS's figure for it, its lines (or for the fees, every line with a fee) split under it.
def _row(name: str, dollars: float, lines: list[EfsLine], found: dict[int, FuelLine]) -> dict:
    mine = [l for l in lines if (l.fee if name == FEES else row_of(l) == name)]
    box = _box(NAMES.get(name, name.title()), "what", name, mine, found, _split(mine, SPLITS.get(name, ()), found, name))
    return box | {"amount": round(dollars, 2)} | _check(_dollars(name, mine), dollars)


# Splits a row's lines by the first dimension in `dims`, then each part by the rest. A part with no Datatruck line
# stops there.
def _split(lines: list[EfsLine], dims: tuple[str, ...], found: dict[int, FuelLine], name: str) -> list[dict]:
    if not dims or not lines:
        return []
    parts: dict[str, list[EfsLine]] = {}
    for line in lines:
        parts.setdefault(_value(dims[0], line, found), []).append(line)
    boxes = [_box(label, dims[0], name, part, found, [] if label == NOT_IN_DATATRUCK else _split(part, dims[1:], found, name))
             for label, part in parts.items()]
    return sorted(boxes, key=lambda b: -b["amount"])


# A line's part along one dimension: where it was bought, who pays, the company, EFS's item text, or (for a fee)
# the row of the line it is on.
def _value(dim: str, line: EfsLine, found: dict[int, FuelLine]) -> str:
    if dim == "item":
        return line.description.title()
    if dim == "on":
        return NAMES.get(row_of(line), row_of(line))
    bought = found.get(line.seq)
    if bought is None:
        return NOT_IN_DATATRUCK
    if dim == "where":
        return fuel.LOVES if fuel.is_loves(bought) else "Elsewhere"
    if dim == "payer":
        return DRIVERS if bought.billable else COMPANY
    return bought.company  # dim == "company"


# One box of page-1 row `name`: its label, the dimension it splits on (what, where, payer, company, item, on), its
# dollars, how many statement lines it holds, its gallons (None when not fuel), how it compares with Datatruck (card
# purchases only), the pump price and discount per gallon (fuel only) and the boxes under it.
def _box(label: str, dim: str, name: str, lines: list[EfsLine], found: dict[int, FuelLine], children: list[dict]) -> dict:
    box = {"label": label, "dim": dim, "amount": round(_dollars(name, lines), 2), "lines": len(lines),
           "gallons": round(sum(l.quantity for l in lines), 3) if name in MEASURED else None, "children": children}
    bought = [] if name == FEES else [l for l in lines if is_purchase(l)]  # a fee is EFS's, whatever line it sits on
    return box | ({"datatruck": _versus(bought, found)} if bought else {}) | (_pump(lines, found) if name in MEASURED else {})


# Per gallon, over the lines found in Datatruck: the pump price (Datatruck's) and the discount, pump price minus what
# the statement charged. Nothing when none were found.
def _pump(lines: list[EfsLine], found: dict[int, FuelLine]) -> dict:
    hits = [l for l in lines if l.seq in found]
    gallons = sum(l.quantity for l in hits)
    if not gallons:
        return {}
    pump = sum(found[l.seq].pump_total for l in hits)
    return {"pump_per_gal": round(pump / gallons, 4), "discount_per_gal": round((pump - sum(l.amount for l in hits)) / gallons, 4)}


# What lines of page-1 row `name` add up to: the fee on each for the fees row, else what each cost.
def _dollars(name: str, lines: list[EfsLine]) -> float:
    return sum(l.fee if name == FEES else l.amount for l in lines)


# How statement lines compare with Datatruck: how many were found there and how many not, and Datatruck's dollars for
# the ones found minus the statement's (0 when they agree to the cent).
def _versus(lines: list[EfsLine], found: dict[int, FuelLine]) -> dict:
    hits = [l for l in lines if l.seq in found]
    off = sum(found[l.seq].billed for l in hits) - sum(l.amount for l in hits)
    return {"found": len(hits), "missing": len(lines) - len(hits), "off": round(off, 2) + 0.0}  # + 0.0: no "-0.0"


# Datatruck lines on the statement's days, of the account's companies, that match no statement line: how many, their
# dollars, and what they were by product (e.g. {"STAX": 2}). Cash advances are left out: on the statement they are
# money codes, which Datatruck never has. Not checked (None) when the account's companies aren't known.
def _only_in_datatruck(lines: list[EfsLine], found: dict[int, FuelLine], datatruck: list[FuelLine],
                       companies: tuple[str, ...] | None) -> dict:
    if companies is None:
        return {"extra": None}
    days, used = {l.day for l in lines}, {f.line_id for f in found.values()}
    extra = [f for f in datatruck if f.line_id not in used and f.company in companies and f.fueled_at[:10] in days
             and f.transaction_type != "cash_advance"]
    return {"extra": len(extra), "extra_dollars": round(sum(f.billed for f in extra), 2),
            "extra_items": dict(Counter(f.product or f.transaction_type for f in extra))}


# {"check": lines minus EFS's figure} when they differ by a cent or more, else nothing.
def _check(lines_dollars: float, efs_dollars: float) -> dict:
    off = round(lines_dollars - efs_dollars, 2)
    return {"check": off} if abs(off) >= 0.01 else {}
