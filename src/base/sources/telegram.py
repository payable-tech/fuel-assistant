# Telegram through user accounts (Telethon): Bob's account lists the driver groups and saves the Love's sheets posted in
# their group; the assistant's account sends, only from features/engine/job: to the test group, and to the driver groups of
# the trucks in LIVE_UNITS.
import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path

from telethon.sync import TelegramClient
from telethon.tl.types import InputMessagesFilterDocument

from base import config
from base.models import TelegramGroup

_send_lock = threading.Lock()  # see send


# Logs the assistant's account (TG_PHONE) in once, interactively: Telegram sends a code to that account's app and
# you type it here. Returns the account's name.
def login() -> str:
    client = _client(config.TG_SESSION_PATH)
    client.start(phone=config.secret("TG_PHONE"))  # asks for the code, and the 2FA password if it has one
    name = client.get_me().first_name
    client.disconnect()
    return name


# Returns every group the groups account (TG_GROUPS_SESSION_PATH) is a member of.
def groups() -> list[TelegramGroup]:
    with _session(config.TG_GROUPS_SESSION_PATH) as client:
        return [TelegramGroup(chat_id=d.id, title=d.title) for d in client.iter_dialogs() if d.is_group]


# Sends a message (Telegram HTML: links) to a chat from the assistant's account, without link previews. Returns its id.
# One send at a time: the engine and the heartbeat send from two threads, and one login file can't be opened twice.
def send(chat_id: int, text: str) -> int:
    with _send_lock, _session(config.TG_SESSION_PATH) as client:
        return client.send_message(_chat(client, chat_id), text, parse_mode="html", link_preview=False).id


# Saves every .xlsx posted in a chat after message `after_id` into `folder` as "tg-<message id>.xlsx", with the groups
# login. Each is written under a temporary name first, so a download cut short never looks like a sheet. Returns the
# files saved.
def save_sheets(chat_id: int, after_id: int, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    with _session(config.TG_GROUPS_SESSION_PATH) as client:
        for m in client.iter_messages(_chat(client, chat_id), min_id=after_id, filter=InputMessagesFilterDocument):
            if m.file and (m.file.name or "").lower().endswith(".xlsx"):
                part = Path(m.download_media(file=str(folder / f"tg-{m.id}.part")))
                saved.append(part.replace(folder / f"tg-{m.id}.xlsx"))
    return saved


# The chat to write to, as Telegram needs it.
def _chat(client: TelegramClient, chat_id: int):
    try:
        return client.get_input_entity(chat_id)
    except ValueError:  # a group this login hasn't listed yet (e.g. just joined): list them once, then it knows it
        client.get_dialogs()
        return client.get_input_entity(chat_id)


# Connects with the login saved in `path`; fails with a clear message instead of asking for a code mid-job.
@contextmanager
def _session(path: Path):
    client = _client(path)
    client.connect()
    try:
        if not client.is_user_authorized():
            raise RuntimeError(f"Telegram is not logged in ({path.name}). Run: .venv\\Scripts\\python.exe src\\main.py login")
        yield client
    finally:
        client.disconnect()


# Creates the Telethon client that keeps a login in the session file `path`.
def _client(path: Path) -> TelegramClient:
    # Telethon needs an event loop in the calling thread; the scheduler's background thread starts without one.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return TelegramClient(str(path), int(config.secret("TG_API_ID")), config.secret("TG_API_HASH"))
