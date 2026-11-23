# Telegram for the card agent: its own login (AGENT_SESSION_PATH) on the assistant's account, apart from the engine's
# (sources/telegram: one login file can't be opened twice). It hears every new message in the account's groups that
# tags it or replies to it, reads the chat before that message, and writes back.
from datetime import timezone
from typing import Awaitable, Callable

from telethon import events
from telethon.sync import TelegramClient  # its calls are plain calls outside an event loop (login), awaited inside it
from telethon.tl.types import MessageEntityMentionName

import config
from models import ChatLine


# Logs the agent's login in once, interactively: Telegram sends a code to the account's app and you type it here.
# Returns the account's name.
def login() -> str:
    client = _client()
    client.start(phone=config.AGENT_PHONE or config.secret("TG_PHONE"))  # asks for the code, and a 2FA password
    me = client.get_me()
    client.disconnect()
    return f"{me.first_name or ''} {me.last_name or ''}".strip() or str(me.id)


# Forever: calls `on_tag(client, message, named)` for each new group message that tags the account or replies to one
# of its messages; `named` is True when it was tagged by @username or by name, not only replied to. Old messages are
# never replayed: only what arrives while it runs.
async def listen(on_tag: Callable[[TelegramClient, object, bool], Awaitable[None]]) -> None:
    client = _client()
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("The card agent's Telegram login is missing: run `main.py agent-login` once.")
    me = await client.get_me()
    handle = f"@{me.username}".lower() if me.username else None

    @client.on(events.NewMessage(incoming=True))
    async def heard(event) -> None:
        if not event.is_group or not event.message.mentioned:
            return
        text = (event.message.message or "").lower()
        named = bool(handle and handle in text) or any(isinstance(e, MessageEntityMentionName) and e.user_id == me.id
                                                       for e in event.message.entities or [])
        await on_tag(client, event.message, named)

    await client.run_until_disconnected()


# The last `limit` messages of a chat up to and with `message_id`, oldest first, with who wrote each; the newest
# `photos` photos among them are fetched as JPEG bytes.
async def chat_before(client: TelegramClient, chat_id: int, message_id: int, limit: int, photos: int) -> list[ChatLine]:
    me = await client.get_me()
    found = [m async for m in client.iter_messages(chat_id, limit=limit, max_id=message_id + 1)]
    lines, fetched = [], 0
    for m in found:  # newest first: the photos fetched are the newest ones
        photo = None
        if m.photo and fetched < photos:
            photo = await client.download_media(m, file=bytes)
            fetched += 1
        sender = await m.get_sender()
        name = " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])) \
            or getattr(sender, "title", None) or str(m.sender_id)
        lines.append(ChatLine(m.id, m.date.astimezone(timezone.utc), name, m.sender_id == me.id, m.message or "", photo))
    return lines[::-1]


# Writes in a chat; as a reply to `reply_to` when given. Returns the new message's id.
async def write(client: TelegramClient, chat_id: int, text: str, reply_to: int | None = None) -> int:
    sent = await client.send_message(chat_id, text, reply_to=reply_to, link_preview=False)
    return sent.id


# The client that keeps the agent's login in its own session file.
def _client() -> TelegramClient:
    return TelegramClient(str(config.AGENT_SESSION_PATH), int(config.secret("TG_API_ID")), config.secret("TG_API_HASH"))
