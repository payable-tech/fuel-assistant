# Tests the Love's exits: reading the highway and exit off a store's page, keeping them per store, and the job that
# reads each store once and gives up for the night when the site doesn't answer.
import pytest

from base import config
from base.models import Store
from base.sources import loves
from base.store import db
from features.engine import store_exits

# A store page's heading as Love's site sends it: its words split by empty comments.
PAGE = ('<h1 class="x">Love\'s Travel Stop<!-- --> #<!-- -->563</h1><h2>Belmont<!-- -->, <!-- -->OH<!-- --> | '
        'Exit 208/OH-149 on I-70</h2><ul><li><h5>Exit 208</h5>')


# Points the database at a temporary file so tests never touch data/fuel.db, and takes the pause between pages out.
@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "EXITS_PAUSE_SEC", 0)


# The heading "Exit 208/OH-149 on I-70" becomes "I-70 (Exit 208)"; a heading without an exit gives none; a page that
# isn't the store's is refused.
def test_way_from_the_page():
    assert loves.way(PAGE, "563") == "I-70 (Exit 208)"
    assert loves.way(PAGE.replace("Exit 208/OH-149 on I-70", "Exit 64 on I-15"), "563") == "I-15 (Exit 64)"
    assert loves.way(PAGE.replace("Exit 208/OH-149 on I-70", "Exit 37/Griffith Rd on I-40"), "563") == "I-40 (Exit 37)"
    assert loves.way(PAGE.replace("Exit 208/OH-149 on I-70", "Exit 1A on I-10 &amp; US-90"), "563") == "I-10 & US-90 (Exit 1A)"
    assert loves.way(PAGE.replace(" | Exit 208/OH-149 on I-70", ""), "563") is None
    assert loves.way(PAGE.replace("Exit 208/OH-149 on I-70", "Exit FM 1960 on Hwy 290"), "563") is None  # a cross road, no number
    assert loves.way(PAGE.replace("Exit 208/OH-149 on I-70", "Exit 2nd St on US Hwy-36"), "563") is None  # a street
    assert loves.way(PAGE.replace("Exit 208/OH-149 on I-70", "Exit 237B on CA Hwy-99"), "563") == "CA Hwy-99 (Exit 237B)"
    with pytest.raises(LookupError):
        loves.way(PAGE, "999")


# A store's exit is kept apart from the price sheets: a new sheet replaces the stores and the exit stays.
def test_exit_is_kept_with_the_store():
    store = Store("563", "Belmont", "OH", 40.0, -81.0, 6.0, 5.4, "2026-11-10")
    with db.connect() as conn:
        db.replace_stores(conn, [store, Store("340", "Las Vegas", "NV", 36.4, -114.9, 6.5, 5.8, "2026-11-10")])
        assert db.stores_without_exit(conn) == ["340", "563"]
        db.save_store_exit(conn, "563", "I-70 (Exit 208)")
        db.save_store_exit(conn, "340", None)
        db.replace_stores(conn, [store])  # the next day's sheet
        assert db.stores_without_exit(conn) == []
        assert [(s.store_no, s.way) for s in db.stores(conn)] == [("563", "I-70 (Exit 208)")]


# The job reads only the stores not read yet, keeps what each page says, and tries a failed page again next time.
def test_job_reads_each_store_once(monkeypatch):
    asked = []
    pages = {"1": "I-10 (Exit 1)", "2": None}

    def exit_of(store_no: str):
        asked.append(store_no)
        if store_no == "3":
            raise RuntimeError("page down")
        return pages[store_no]

    monkeypatch.setattr(store_exits.loves, "exit_of", exit_of)
    with db.connect() as conn:
        db.replace_stores(conn, [Store(no, "Town", "TX", 30.0, -97.0, 6.0, 5.5, "2026-11-10") for no in ("1", "2", "3")])
    assert store_exits.run() == 2 and asked == ["1", "2", "3"]
    assert store_exits.run() == 0 and asked == ["1", "2", "3", "3"]  # only the failed one again
    with db.connect() as conn:
        assert {s.store_no: s.way for s in db.stores(conn)} == {"1": "I-10 (Exit 1)", "2": None, "3": None}


# When the site doesn't answer, the job stops after a few pages in a row instead of holding the other jobs up.
def test_job_stops_when_the_site_is_down(monkeypatch):
    asked = []
    monkeypatch.setattr(store_exits.loves, "exit_of", lambda no: asked.append(no) or (_ for _ in ()).throw(RuntimeError("down")))
    with db.connect() as conn:
        db.replace_stores(conn, [Store(str(no), "Town", "TX", 30.0, -97.0, 6.0, 5.5, "2026-11-10") for no in range(100, 130)])
    assert store_exits.run() == 0 and len(asked) == store_exits.MAX_FAILS
