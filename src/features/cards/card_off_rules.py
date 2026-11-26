# Turning a card off (pure): which cards are due and what each gets, by the user's rule of 2026-11-26. A driver whom
# Datatruck has as inactive (terminated): the card is parked (99999 / 99999 / ALIF UZ CORP) with X-Ref
# "QUIT <Datatruck driver ID> <MMDD>". Anyone else (home time, the truck in the shop, a team mate resting): INACTIVE
# with X-Ref "HOMETIME <MM-DD>", the unit, driver ID and name left as they are, so it is switched back on in one step.
# The doer is features/cards/card_off.
from datetime import date, datetime

QUIT, HOMETIME = "quit", "hometime"


# What turning one card off does: (QUIT or HOMETIME, its X-Ref). Only Datatruck saying "inactive" parks a card, never
# the check's words alone: parking is the change that is hard to undo.
def action(dt_driver_status: str | None, dt_driver_id: int | None, day: date) -> tuple[str, str]:
    if dt_driver_status == "inactive" and dt_driver_id:
        return QUIT, f"QUIT {dt_driver_id} {day:%m%d}"
    return HOMETIME, f"HOMETIME {day:%m-%d}"


# The cards to turn off: ACTIVE in the copy, and their latest check says off and was made at `since` or later.
def due(cards: list[dict], since: datetime) -> list[dict]:
    stamp = since.isoformat(sep=" ", timespec="seconds")
    return [c for c in cards if c["status"] == "ACTIVE" and c["should_be"] == "off" and (c["checked_at"] or "") >= stamp]
