# Shared by every test. No test may reach the real eManager window or open a real Telegram login: a test that forgets
# to put a fake in their place fails here, instead of touching a real fuel card or a real driver group.
import pytest

from base.sources import telegram
from features.cards import telegram_agent
from features.cards.emanager import window


# Replaces the ways out to eManager and Telegram with a refusal for the length of each test.
@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    # Fails the test that got here: it reached for something real.
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached for the real eManager window or a real Telegram login")

    monkeypatch.setattr(window, "run", refuse)
    monkeypatch.setattr(window, "start", refuse)
    monkeypatch.setattr(telegram, "_client", refuse)
    monkeypatch.setattr(telegram_agent, "_client", refuse)
