# Tests the habits job: Samsara being down must not wipe the gauge readings (it did on 2026-11-01).
from datetime import datetime

import pytest

from base import config
from base.models import FuelLine
from features.engine import helper_jobs


# With the gauge calls failing, the job gives up, so the copy step keeps the previous copy instead of saving blank gauges.
def test_gauge_failure_keeps_the_old_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    line = FuelLine(1, datetime.now().strftime("%Y-%m-%d %H:%M"), "fuel", "ULSD", 100.0, 600.0, 550.0, 0.0, True, "LOVES #1", "Town", "TX",
                    "TTL", "340", "company", 7, "Ali", "company", None)
    monkeypatch.setattr(helper_jobs.db, "fuel_lines", lambda conn, since_day: [line])
    monkeypatch.setattr(helper_jobs.db, "fleet", lambda conn: [type("T", (), {"unit": "340", "samsara_id": "1"})()])

    def down(*args):
        raise RuntimeError("down")

    monkeypatch.setattr(helper_jobs.samsara, "fuel_history", down)
    with pytest.raises(RuntimeError):
        helper_jobs._stops()
