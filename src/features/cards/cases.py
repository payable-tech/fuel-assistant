# Test cases for the card agent: what drivers really wrote about their fuel cards in their truck's group, read from the
# groups' history with the agent's own Telegram login and saved under data/card_cases (never sent anywhere, never in
# git). Only groups linked to a truck are read, only messages written by that truck's own driver are kept, and nothing
# is ever written to a group. The replay (features/cards/replay) plays these cases to the agent.
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

from base import config
from base.models import ChatLine, DatatruckDriver
from base.store import db
from features.cards import rules, settings, telegram_agent

CASES_DIR = config.DATA_DIR / "card_cases"
SEARCH = ("card", "declined")              # the words looked for in each group (Telegram searches one at a time)
ABOUT_A_CARD = re.compile(r"card|declin", re.IGNORECASE)
BURST = timedelta(minutes=15)              # card messages of one driver this close together are one case: its last one
AFTER = 6                                  # messages kept after a case: what the office did (never shown to the agent)
PAUSE_S = 0.4                              # between two searches, so Telegram doesn't make the account wait


# Reads the truck groups' last `days` days and saves up to `most` cases, newest first. Returns how many were saved.
def collect(days: int, most: int) -> int:
    with db.connect() as conn:
        trucks = [t for t in db.fleet(conn) if t.chat_id]
        drivers = [d for d in db.dt_drivers(conn) if d.employee_status == "active"]
    groups = {t.chat_id: (t.unit, [d for d in drivers if d.unit == t.unit]) for t in trucks}
    cases = asyncio.run(_read(groups, datetime.now(timezone.utc) - timedelta(days=days), most))
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    (CASES_DIR / "cases.json").write_text(json.dumps(cases, indent=1, ensure_ascii=False), encoding="utf-8")
    return len(cases)


# The saved cases, newest first; empty before the first `card-cases`.
def saved() -> list[dict]:
    path = CASES_DIR / "cases.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


# A saved case's chat as the agent reads it: the messages up to the driver's, with the photos that were saved.
def chat_of(case: dict) -> list[ChatLine]:
    return [ChatLine(c["message_id"], datetime.fromisoformat(c["at"]), c["sender"], c["ours"], c["text"],
                     (CASES_DIR / c["photo"]).read_bytes() if c["photo"] else None) for c in case["chat"]]


# True when a message is a driver's card case: written by one of the truck's own active drivers, about a card.
def is_case(text: str, sender: str, drivers: list[DatatruckDriver]) -> bool:
    return bool(ABOUT_A_CARD.search(text or "")) and any(rules.same_person(sender, d.full_name) for d in drivers)


# Of one group's card messages, (message id, when) each, the last of every burst: several messages of one complaint
# are one case, and its last message has the whole complaint before it.
def last_of_bursts(hits: list[tuple[int, datetime]], gap: timedelta) -> list[int]:
    kept, ordered = [], sorted(hits, key=lambda h: h[1])
    for i, (message_id, at) in enumerate(ordered):
        if i == len(ordered) - 1 or ordered[i + 1][1] - at > gap:
            kept.append(message_id)
    return kept


# Reads the groups: searches each for the card words since `since`, keeps the drivers' own messages, and for every case
# reads the chat before it (as the agent would) and the messages after it. Only reads; disconnects at the end.
async def _read(groups: dict[int, tuple[str, list[DatatruckDriver]]], since: datetime, most: int) -> list[dict]:
    client = telegram_agent._client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("The card agent's Telegram login is missing: run `main.py agent-login` once.")
        known = {d.id for d in await client.get_dialogs()}  # also teaches this login the groups, so they can be read
        found = []
        for chat_id, (unit, drivers) in groups.items():
            if chat_id not in known or not drivers:
                continue
            hits = {}
            for word in SEARCH:
                async for m in client.iter_messages(chat_id, search=word, limit=200):
                    if m.date < since:
                        break
                    if is_case(m.message, _name(m.sender, m.sender_id), drivers):
                        hits[m.id] = m.date
                await asyncio.sleep(PAUSE_S)
            found += [(hits[i], chat_id, unit, i) for i in last_of_bursts(list(hits.items()), BURST)]
        cases = []
        for at, chat_id, unit, message_id in sorted(found, reverse=True)[:most]:
            cases.append(await _case(client, chat_id, unit, message_id, at))
        return cases
    finally:
        await client.disconnect()


# One case: the chat before the driver's message (photos saved as files), and what was written after it.
async def _case(client, chat_id: int, unit: str, message_id: int, at: datetime) -> dict:
    chat = await telegram_agent.chat_before(client, chat_id, message_id, settings.AGENT_HISTORY, settings.AGENT_MAX_PHOTOS)
    after = [m async for m in client.iter_messages(chat_id, min_id=message_id, reverse=True, limit=AFTER)]
    lines = []
    for c in chat:
        photo = None
        if c.photo:
            photo = f"{abs(chat_id)}_{c.message_id}.jpg"
            (CASES_DIR / photo).parent.mkdir(parents=True, exist_ok=True)
            (CASES_DIR / photo).write_bytes(c.photo)
        lines.append({"message_id": c.message_id, "at": c.at.isoformat(), "sender": c.sender, "ours": c.ours,
                      "text": c.text, "photo": photo})
    return {"chat_id": chat_id, "unit": unit, "message_id": message_id, "at": at.astimezone(timezone.utc).isoformat(),
            "sender": chat[-1].sender if chat else "", "text": chat[-1].text if chat else "", "chat": lines,
            "after": [{"at": m.date.astimezone(timezone.utc).isoformat(), "sender": _name(m.sender, m.sender_id),
                       "text": m.message or ("[photo]" if m.photo else "")} for m in after]}


# A sender's name as Telegram shows it: first and last name, a channel's title, else the id.
def _name(sender, sender_id) -> str:
    return " ".join(filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])) \
        or getattr(sender, "title", None) or str(sender_id)
