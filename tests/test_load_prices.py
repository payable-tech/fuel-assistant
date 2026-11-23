# Tests pulling Love's sheets from Telegram in the prices job: it asks only for what is newer than the newest sheet
# already saved, and Telegram failing never stops the job.
import config
from jobs import load_prices
from sources import telegram


# The newest message id in the folder's file names is where the next pull starts; an empty folder starts from 0.
def test_pull_starts_after_the_newest_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TG_PRICES_DIR", tmp_path)
    asked = []
    monkeypatch.setattr(telegram, "save_sheets", lambda chat, after, folder: asked.append(after) or [])
    load_prices.pull_from_telegram()
    (tmp_path / "tg-5.xlsx").write_bytes(b"")
    (tmp_path / "tg-12.xlsx").write_bytes(b"")
    load_prices.pull_from_telegram()
    assert asked == [0, 12]


# Telegram down or logged out: reported, not raised.
def test_pull_failure_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TG_PRICES_DIR", tmp_path)

    # A Telegram that can't be reached.
    def down(*_):
        raise ConnectionError("no network")

    monkeypatch.setattr(telegram, "save_sheets", down)
    load_prices.pull_from_telegram()
