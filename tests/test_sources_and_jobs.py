# Tests the Love's sheet reader, the refresh rule that a failed or empty fetch keeps the previous copy, and that an
# order read twice from Datatruck's pages is kept once.
import contextlib

import openpyxl
import pytest

from base import config
from base.fleet import mirror
from base.models import TelegramGroup
from base.sources import datatruck, loves
from base.store import db


# An order that came on two pages (the list shifted while it was read) is kept once.
def test_active_orders_kept_once(monkeypatch):
    raw = {"id": 7, "load_id": "L-7", "status": "dispatched", "trip": {}, "pickup_appointment_time": None, "stops": []}
    monkeypatch.setattr(datatruck, "_client", contextlib.nullcontext)
    monkeypatch.setattr(datatruck, "_results", lambda client, path, params: iter([raw, dict(raw)]))
    assert [o.order_id for o in datatruck.active_orders()] == [7]

HEADER = ["City", "Loves Store No.", "State", "Latitude", "Longitude", "Retail Price", "Best Discounted Price",
          "Effective Date", "Extra Column"]


# Points the database at a temporary file so tests never touch data/fuel.db.
@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")


# Writes a small price sheet with the given data rows and returns its path.
def sheet(tmp_path, *rows):
    book = openpyxl.Workbook()
    book.active.append(HEADER)
    for row in rows:
        book.active.append(row)
    path = tmp_path / "prices.xlsx"
    book.save(path)
    return path


# Columns are found by header name, in any order; extra columns are ignored.
def test_sheet_columns_by_name(tmp_path):
    stores, skipped = loves.read(sheet(tmp_path, ["Loxley", "206", "AL", 30.65, -87.75, 5.949, 5.6059, "2026-10-14", "x"]))
    assert (stores[0].store_no, stores[0].city, stores[0].net, stores[0].price_date, skipped) == \
           ("206", "Loxley", 5.6059, "2026-10-14", [])


# A row with an empty required cell is skipped and reported by its sheet line.
def test_sheet_row_with_gap_skipped(tmp_path):
    stores, skipped = loves.read(sheet(tmp_path, ["Loxley", "206", "AL", 30.65, -87.75, 5.949, None, "2026-10-14"]))
    assert (stores, skipped) == ([], [2])


# A sheet missing a required column fails loudly.
def test_sheet_missing_column(tmp_path):
    book = openpyxl.Workbook()
    book.active.append(["City"])
    book.save(tmp_path / "bad.xlsx")
    with pytest.raises(ValueError):
        loves.read(tmp_path / "bad.xlsx")


# Returns the titles in the Telegram groups copy.
def titles() -> list[str]:
    with db.connect() as conn:
        return [g.title for g in db.tg_groups(conn)]


# A good fetch replaces the copy; an empty or failing fetch leaves the previous copy in place.
def test_refresh_keeps_copy_on_empty_or_error():
    assert mirror.refresh("groups", lambda: [TelegramGroup(-1, "Unit 340")], db.replace_tg_groups)
    assert not mirror.refresh("groups", lambda: [], db.replace_tg_groups)
    assert not mirror.refresh("groups", lambda: 1 / 0, db.replace_tg_groups)
    assert titles() == ["Unit 340"]
