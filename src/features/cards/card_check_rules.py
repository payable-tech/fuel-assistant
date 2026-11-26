# The card checker's words and rules (pure): what Claude is told to do, its one tool, what it is shown about a card
# (the data and the truck group's latest messages, each dated), and whether its answer can be saved. The doer is
# features/cards/card_check.
from datetime import datetime

from base.fleet.link_rules import INACTIVE, names_unit_and_driver
from base.fuel import CENTRAL
from base.models import ChatLine, Order, TelegramGroup, Truck

SHOULD_BE = ("on", "off", "unsure")
SURE = ("high", "medium", "low")
WHY_MAX = 60  # characters: the Why column is read at a glance

# Claude's instructions.
INSTRUCTIONS = """You check one fuel card of a trucking company. A card should be ACTIVE only while its driver is \
working for us: on a load, between loads, or about to take one. Your job is to catch ACTIVE cards that should be \
turned off: the driver is on home time, has quit or been let go, has left the truck, or the card is not his any more.

You are shown what the company's data says about the card and its truck, then the latest messages of the truck's \
Telegram group (the driver, dispatchers, the fuel desk), oldest first, each with its date. Messages may be in English, \
Uzbek or Russian. How long the group has been quiet is a fact too.

Decide what the card should be now, and record it with the record_check tool, once:
- should_be: "on" (he is working or about to), "off" (home time, quit, let go, dropped the truck, card not his any \
more), or "unsure" (nothing tells either way). Home time means off while he is home, even for a few days: the card is \
opened again when he is back.
- why: a few words a dispatcher reads at a glance, with a date when there is one: "On a load", "Home time since Nov 24", \
"Quit Nov 20", "Truck in shop, no driver".
- sure: "high" when the group and the data say the same, "medium" when only one of them says it, "low" when there is \
nothing recent to go on.
- evidence: one or two short lines: the words in the group that decided it (quoted, with their date) and the data \
that backs it.

Do not guess: when the group says nothing about it and the data is mixed, the answer is unsure."""

RECORD_TOOL = "Record what this card should be, why, and how sure you are. Call it once."
RECORD_INPUT = {
    "type": "object",
    "properties": {
        "should_be": {"type": "string", "enum": list(SHOULD_BE)},
        "why": {"type": "string", "description": f"a few words, at most {WHY_MAX} characters"},
        "sure": {"type": "string", "enum": list(SURE)},
        "evidence": {"type": "string", "description": "one or two short lines: the deciding words, quoted and dated, "
                                                      "and the data behind it"},
    },
    "required": ["should_be", "why", "sure", "evidence"],
}

# A card whose truck has no group: nothing to read, so nothing for Claude to decide.
NO_GROUP = ("unsure", "No group found", "low", "No Telegram group is linked to this card's unit.")


# The group to read for a card, and the groups of its driver that dispatch marked INACTIVE (as it does when a driver
# leaves). Its own group is the one open group whose title names the card's unit and its driver: the name on the card,
# or the driver Datatruck has the card on. With none (or several), the truck's linked group (`linked`), if any.
def group_of(card: dict, linked: int | None, groups: list[TelegramGroup]) -> tuple[TelegramGroup | None, list[str]]:
    units = {u for u in (card.get("dt_unit"), card.get("unit")) if u}
    names = [n for n in (card.get("driver_name"), card.get("dt_driver")) if n]
    named = [g for g in groups if any(names_unit_and_driver(g.title, u, n) for u in units for n in names)]
    own = [g for g in named if not INACTIVE.search(g.title)]
    closed = [g.title for g in named if INACTIVE.search(g.title)]
    if len(own) == 1:
        return own[0], closed
    if linked is None:
        return None, closed
    return next((g for g in groups if g.chat_id == linked), TelegramGroup(linked, "")), closed  # a title isn't needed


# Why a recorded answer can't be saved, in words Claude can fix it from; "" when it can.
def problem(answer: dict) -> str:
    if answer.get("should_be") not in SHOULD_BE:
        return f"should_be must be one of {', '.join(SHOULD_BE)}."
    if answer.get("sure") not in SURE:
        return f"sure must be one of {', '.join(SURE)}."
    why = str(answer.get("why") or "").strip()
    if not why or len(why) > WHY_MAX:
        return f"why must be a few words, at most {WHY_MAX} characters."
    return ""


# What Claude is shown about one card: the card in EFS, the same card in Datatruck, the truck now (its loads, its
# last position), its driver's groups marked INACTIVE, then the messages of the group read (`title`), oldest first.
# Times on the company's clock (Central).
def facts(card: dict, unit: str | None, truck: Truck | None, orders: list[Order], lines: list[ChatLine],
          now: datetime, title: str = "", closed: tuple[str, ...] = ()) -> str:
    out = [f"Now: {_when(now)} CT.", "",
           f"Card …{card['last4']} ({card['account']}), {card['status']} in EFS"
           + (", in override (open for one fill)" if card.get("override") else "") + ".",
           f"On the card: driver {card.get('driver_name') or 'none'}, unit {card.get('unit') or 'none'}, "
           f"driver ID {card.get('driver_id') or 'none'}.",
           f"EFS last saw it used: {_used(card.get('last_used'), now)}.",
           _datatruck(card), ""]
    if unit:
        out.append(f"Truck {unit}: " + ("; ".join(_load(o) for o in orders) if orders else "no load in Datatruck") + ".")
    if truck is not None:
        out.append(f"Its last position (Samsara): {truck.place or 'unknown'}"
                   + (f", {_ago(now, truck.gps_at)} ago" if truck.gps_at else "") + ".")
    out += [f"A group of this unit and driver that dispatch marked INACTIVE: \"{t}\"." for t in closed]
    out.append("")
    group = f"The Telegram group \"{title}\"" if title else "The truck's Telegram group"
    if not lines:
        out.append(f"{group} has no messages.")
    else:
        out.append(f"{group}, its last {len(lines)} messages, oldest first (the newest {_ago(now, lines[-1].at)} ago):")
        out += [f"[{_when(l.at)}] {l.sender}{' (our account)' if l.ours else ''}: {l.text.strip() or '[no text]'}"
                for l in lines]
    return "\n".join(out)


# Whom Datatruck assigns the same card to, in one line.
def _datatruck(card: dict) -> str:
    if card.get("dt_card_id") is None:
        return "Datatruck has no card with this number."
    if card.get("dt_assigned_to") == "truck":
        return f"Datatruck assigns this card to truck {card.get('dt_unit') or '?'}, not to a driver."
    if not card.get("dt_driver"):
        return "Datatruck has this card but assigns it to nobody."
    state = "an active driver" if card.get("dt_driver_status") == "active" else \
        f"a driver who is {card.get('dt_driver_status') or 'not active'} in Datatruck"
    return f"Datatruck assigns this card to {card['dt_driver']} ({state}), on unit {card.get('dt_unit') or 'none'}."


# One of the truck's loads in Datatruck: "load 576378385 in transit (pickup Nov 25 08:00)".
def _load(order: Order) -> str:
    pickup = f" (pickup {_when(order.pickup_at)})" if order.pickup_at else ""
    return f"load {order.load_id} {order.status.replace('_', ' ')}{pickup}"


# The day EFS last saw the card used, with how long ago: "Nov 24 (2 days ago)"; "never" or "not read".
def _used(day: str | None, now: datetime) -> str:
    if not day:
        return "never, or not read yet"
    days = (now.astimezone(CENTRAL).date() - datetime.fromisoformat(day).date()).days
    return f"{datetime.fromisoformat(day):%b %d} ({'today' if days <= 0 else f'{days} day' + ('s' if days > 1 else '') + ' ago'})"


# A moment on the company's clock: "Nov 24 14:03".
def _when(moment: datetime) -> str:
    return f"{moment.astimezone(CENTRAL):%b %d %H:%M}"


# How long before `now` a moment was, roughly: "40 min", "5 h", "3 days".
def _ago(now: datetime, then: datetime) -> str:
    minutes = int((now - then).total_seconds() // 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h" if minutes < 48 * 60 else f"{minutes // 1440} days"
