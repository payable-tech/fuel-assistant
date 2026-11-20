# Checks on an EFS statement's fills, under its tree: the statement in numbers (swipes, gallons, trucks, drivers), and
# whether each Love's fill was charged the price Love's promised on that day's price sheet.
from core import fuel
from core.accounting import is_purchase, row_of
from models import EfsLine, FuelLine

TO_THE_CENT = 0.01  # $/gal: a fill charged within this of the sheet's net price was charged the sheet's price
# The verdicts on a Love's fill, in the order they are shown.
AS_PROMISED = "As promised"
MORE = "Charged more than the sheet"
LESS = "Charged less than the sheet"
NO_DEAL = "No deal: store not on the sheet"
NO_SHEET = "No sheet that day"
VERDICTS = (AS_PROMISED, MORE, LESS, NO_DEAL, NO_SHEET)


# The statement in numbers: card swipes, diesel fills and gallons, money codes, and the Datatruck trucks and drivers
# behind the purchases found there.
def headline(lines: list[EfsLine], found: dict[int, FuelLine]) -> dict:
    purchases = [l for l in lines if is_purchase(l)]
    diesel = [l for l in purchases if row_of(l) == "DIESEL TOTAL"]
    twins = [found[l.seq] for l in purchases if l.seq in found]
    return {"swipes": len({l.tn for l in purchases}), "diesel_fills": len(diesel),
            "diesel_gallons": round(sum(l.quantity for l in diesel), 1),
            "units": len({f.unit for f in twins if f.unit}), "drivers": len({f.driver_id for f in twins if f.driver_id}),
            "money_codes": sum(1 for l in lines if row_of(l) == "MONEY CODE TOTAL")}


# Every Love's diesel fill against that day's Love's price sheet (`sheets`: {day: {store: net $/gal}}): the verdicts
# with their fills, gallons, dollars charged and dollars off (above the sheet; for a store with no deal, the discount
# missed at that day's average Love's discount, `network`: {day: $/gal}), and the fills that weren't as promised.
def loves_promise(lines: list[EfsLine], found: dict[int, FuelLine], sheets: dict[str, dict[str, float]],
                  network: dict[str, float]) -> dict:
    fills = [_fill(l, found[l.seq], sheets.get(l.day), network.get(l.day)) for l in lines
             if l.seq in found and row_of(l) == "DIESEL TOTAL" and fuel.is_loves(found[l.seq])]
    odd = sorted((f for f in fills if f["verdict"] not in (AS_PROMISED, NO_SHEET)), key=lambda f: -(f["off"] or 0))
    return {"groups": [_group(v, [f for f in fills if f["verdict"] == v]) for v in VERDICTS], "odd": odd}


# One verdict's totals: its fills, gallons, dollars charged and dollars off (None for fills that can't be checked).
def _group(verdict: str, fills: list[dict]) -> dict:
    off = None if verdict == NO_SHEET else round(sum(f["off"] for f in fills if f["off"] is not None), 2)
    return {"verdict": verdict, "fills": len(fills), "gallons": round(sum(f["gallons"] for f in fills), 1),
            "charged": round(sum(f["charged"] for f in fills), 2), "off": off}


# One Love's fill: where and who, its gallons, what the statement charged in all and per gallon, the sheet's net price
# that day (None when no sheet or the store isn't on it), its verdict, and its dollars off (None when not known).
def _fill(line: EfsLine, twin: FuelLine, sheet: dict[str, float] | None, network: float | None) -> dict:
    store = fuel.store_no(twin.location)
    net = sheet.get(store) if sheet else None
    per_gal = line.amount / line.quantity
    if sheet is None:
        verdict, off = NO_SHEET, None
    elif net is None:
        verdict, off = NO_DEAL, (network * line.quantity if network is not None else None)
    else:
        gap = per_gal - net
        verdict = AS_PROMISED if abs(gap) <= TO_THE_CENT else (MORE if gap > 0 else LESS)
        off = gap * line.quantity
    return {"day": line.day, "store": store, "place": f"{twin.city}, {twin.state}".strip(", "), "unit": twin.unit,
            "driver": twin.driver_name, "gallons": round(line.quantity, 3), "charged": round(line.amount, 2),
            "per_gal": round(per_gal, 4), "sheet_per_gal": net, "verdict": verdict, "off": None if off is None else round(off, 2)}
