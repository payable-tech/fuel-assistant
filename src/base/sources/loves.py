# Love's (read-only): its price sheets (every .xlsx under data/love's/, subfolders too, one Store per row), and each
# store's own page on its website, for the highway and exit it sits at (the price sheets have no exits).
import html
import logging
import re
from pathlib import Path

import httpx
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
STORE_PAGE = "https://www.loves.com/locations/{store_no}"  # redirects to the store's page


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


# Returns a store's highway and exit as its page says them, "I-70 (Exit 208)"; None when the page names no exit.
# Raises when the page can't be read or isn't that store's.
def exit_of(store_no: str) -> str | None:
    response = httpx.get(STORE_PAGE.format(store_no=store_no), headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
                         follow_redirects=True)
    response.raise_for_status()
    return way(response.text, store_no)


# The highway and exit in a store page: its heading reads "#563 ... Belmont, OH | Exit 208/OH-149 on I-70", which becomes
# "I-70 (Exit 208)" (the exit's number only, as on the sign). None when the heading names no numbered exit; LookupError
# when the page has no heading for this store (not its page).
def way(page: str, store_no: str) -> str | None:
    text = html.unescape(re.sub(r"<!--.*?-->", "", page))  # the page splits its words with empty comments
    heading = re.search(rf"#{re.escape(store_no)}</h1><h2>([^<]*)<", text)
    if not heading:
        raise LookupError(f"No heading for store {store_no} on its Love's page")
    # "37/Griffith Rd": the number only. A numbered exit only: off the interstates the page names a cross road instead
    # ("Exit FM 1960 on Hwy 290", "Exit 2nd St on US Hwy-36"), which is no exit sign to look for
    found = re.search(r"\|\s*Exit (\d+[A-Z]?)(?![A-Za-z0-9]).* on (\S.*)$", heading.group(1).strip())
    return f"{found.group(2).strip()} (Exit {found.group(1)})" if found else None
