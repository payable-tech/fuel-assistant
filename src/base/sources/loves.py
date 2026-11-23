# Love's price sheets: finds every .xlsx under data/love's/ (subfolders too) and reads one into one Store per row.
import logging
from pathlib import Path

import openpyxl

from base import config
from base.models import Store

log = logging.getLogger(__name__)

# Sheet header -> Store field. Columns are found by header name, so their order in the file doesn't matter.
COLUMNS = {
    "Loves Store No.": "store_no",
    "City": "city",
    "State": "state",
    "Latitude": "lat",
    "Longitude": "lng",
    "Retail Price": "retail",
    "Best Discounted Price": "net",
    "Effective Date": "price_date",
}


# Returns every price sheet in the prices folder and its subfolders, oldest file first. Which day a sheet is for
# comes from its "Effective Date" column, not from its file name or time.
def sheets() -> list[Path]:
    return sorted(config.PRICES_DIR.rglob("*.xlsx"), key=lambda p: p.stat().st_mtime)


# Returns all stores of one sheet; rows with empty required cells are skipped and logged.
def stores(path: Path) -> list[Store]:
    found, skipped = read(path)
    if skipped:
        log.warning("%s: skipped %d rows with empty cells (sheet lines %s)", path.name, len(skipped), skipped[:20])
    return found


# Reads one sheet. Returns (stores, sheet line numbers of rows skipped for empty required cells).
def read(path: Path) -> tuple[list[Store], list[int]]:
    rows = openpyxl.load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True)
    header = list(next(rows))
    missing = COLUMNS.keys() - set(header)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {', '.join(sorted(missing))}")
    position = {field: header.index(name) for name, field in COLUMNS.items()}
    found, skipped = [], []
    for line, row in enumerate(rows, start=2):
        values = {field: row[i] for field, i in position.items()}
        if all(cell in (None, "") for cell in row):
            continue  # blank line, not a data problem
        if any(value in (None, "") for value in values.values()):
            skipped.append(line)
            continue
        found.append(_store(values))
    return found, skipped


# Builds a Store from one row's values.
def _store(values: dict) -> Store:
    return Store(store_no=str(values["store_no"]).strip(), city=str(values["city"]).strip(),
                 state=str(values["state"]).strip(), lat=float(values["lat"]), lng=float(values["lng"]),
                 retail=float(values["retail"]), net=float(values["net"]),
                 price_date=str(values["price_date"])[:10])  # works for both "2026-10-14" text and Excel dates
