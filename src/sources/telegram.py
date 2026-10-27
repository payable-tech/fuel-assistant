# Telegram through user accounts (Telethon): the assistant's account (TG_PHONE) logs in once and sends the messages;
# the list of driver groups is read from the account in TG_GROUPS_SESSION_PATH (Bob's, while it is in more groups).
import asyncio
from contextlib import contextmanager
from pathlib import Path

from telethon.sync import TelegramClient

import config
from models import TelegramGroup


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


# Sends a message (Telegram HTML: bold, links, crossed-out text) to a chat from the assistant's account, without
# link previews. Returns the message's id, to edit it later.
def send(chat_id: int, text: str) -> int:
    with _session(config.TG_SESSION_PATH) as client:
        return client.send_message(_chat(client, chat_id), text, parse_mode="html", link_preview=False).id


# Replaces the text of a message the assistant's account sent earlier; the chat isn't notified.
def edit(chat_id: int, message_id: int, text: str) -> None:
    with _session(config.TG_SESSION_PATH) as client:
        client.edit_message(_chat(client, chat_id), message_id, text, parse_mode="html", link_preview=False)


# The assistant's account: its name, and which of `chat_ids` it is a member of (so it can write there).
def member_of(chat_ids: list[int]) -> tuple[str, set[int]]:
    with _session(config.TG_SESSION_PATH) as client:
        mine = {d.id for d in client.iter_dialogs() if d.is_group}
        return client.get_me().first_name, mine & set(chat_ids)


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
