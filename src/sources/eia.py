# U.S. EIA weekly retail diesel prices by region: the market yardstick our own fuel decisions can't move.
# Public file, no login: https://www.eia.gov/petroleum/gasdiesel/ ("Weekly Retail On-Highway Diesel Prices").
import httpx
import xlrd

from models import MarketPrice, US

URL = "https://www.eia.gov/petroleum/gasdiesel/xls/psw18vwall.xls"
SERIES = {  # EIA series key -> region. The finest regions EIA publishes; together they cover every state.
    "EMD_EPD2D_PTE_NUS_DPG": US,
    "EMD_EPD2D_PTE_R1X_DPG": "New England",
    "EMD_EPD2D_PTE_R1Y_DPG": "Central Atlantic",
    "EMD_EPD2D_PTE_R1Z_DPG": "Lower Atlantic",
    "EMD_EPD2D_PTE_R20_DPG": "Midwest",
    "EMD_EPD2D_PTE_R30_DPG": "Gulf Coast",
    "EMD_EPD2D_PTE_R40_DPG": "Rocky Mountain",
    "EMD_EPD2D_PTE_SCA_DPG": "California",
    "EMD_EPD2D_PTE_R5XCA_DPG": "West Coast except California",
}
KEYS_ROW, NAMES_ROW = 1, 2  # in each data sheet: row 1 holds the series keys, row 2 their names, data follows


# Downloads the EIA file and returns every weekly price of our regions.
def weekly_prices() -> list[MarketPrice]:
    response = httpx.get(URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    book = xlrd.open_workbook(file_contents=response.content)
    sheets = [[sheet.row_values(r) for r in range(sheet.nrows)] for sheet in book.sheets()]
    return read(sheets, book.datemode)


# Finds the weekly sheet among the file's sheets (each a list of rows) and returns its prices of our regions.
# `datemode` tells how the file counts days, needed to turn its date numbers into dates.
def read(sheets: list[list[list]], datemode: int) -> list[MarketPrice]:
    rows = next((s for s in sheets if _is_weekly(s)), None)
    if rows is None:
        raise ValueError("EIA file has no weekly diesel sheet; its layout may have changed")
    columns = {i: SERIES[key] for i, key in enumerate(rows[KEYS_ROW]) if key in SERIES}
    missing = set(SERIES.values()) - set(columns.values())
    if missing:
        raise ValueError(f"EIA weekly sheet is missing regions: {', '.join(sorted(missing))}")
    prices = []
    for row in rows[NAMES_ROW + 1:]:
        if not isinstance(row[0], float):
            continue  # notes or blank lines under the data
        day = xlrd.xldate_as_datetime(row[0], datemode).date().isoformat()
        prices += [MarketPrice(day, region, row[i]) for i, region in columns.items() if isinstance(row[i], float)]
    return prices


# True for the sheet of weekly prices that holds our series. A monthly sheet has the same keys, but its series
# names don't start with "Weekly".
def _is_weekly(rows: list[list]) -> bool:
    return (len(rows) > NAMES_ROW and "EMD_EPD2D_PTE_NUS_DPG" in rows[KEYS_ROW]
            and str(rows[NAMES_ROW][1]).startswith("Weekly"))
