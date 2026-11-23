# Fuel cards in eManager: look them up, read one, set its status, put it in override mode and take it out, edit its
# unit, driver ID and driver name. Every change sends the card's other settings back as its page showed them, then
# opens the card again and stops if anything is not as asked.
import html as markup
import re
from urllib.parse import quote

from base import config
from base.models import EfsCard, EfsCardRow
from features.cards import efs_web
from features.cards.efs_chrome import EfsError
from features.cards.efs_page import Page

STATUSES = ("ACTIVE", "INACTIVE", "HOLD")
# How Card Lookup can search, by our name for each of its choices.
LOOKUPS = {"card": "NUMBER", "unit": "UNIT", "driver-id": "DRIVERID", "driver": "DRIVERNAME", "xref": "XREF",
           "policy": "POLICY"}
# The card's own settings, all sent back on every save.
HEADER = ("card.header.policyNumber", "card.header.companyXRef", "card.header.status", "card.header.handEnter",
          "card.header.infoSource", "card.header.mobileTransaction")
# Settings the website does not send with Remove Override (bob-agent's recording, 2026-10-08).
NOT_SENT_ON_REMOVE = ("card.header.policyNumber", "policy.header.contractId", "card.header.mobileTransaction")
MOST_TIMES = 9      # an override lasts this many transactions at most
# The prompts that can be edited, by our name: eManager's id for the prompt, and the label its card page prints.
# Card Lookup's unit, driver ID and driver name are these prompts; unit and driver ID (Exact Match) are also what the
# driver must type at the pump.
PROMPTS = {"unit": ("UNIT", "Unit Number"), "driver-id": ("DRID", "Driver ID"), "driver": ("NAME", "Driver Name")}
# Where a prompt's edit form keeps its value: an Exact Match prompt in the first box, a Report Only one in the second.
VALUE_BOXES = ("cardInfo.matchValue", "cardInfo.reportValue")


# One account's cards ("ALIF", "DT"), found the way Card Lookup finds them. "all" looks up each policy in turn.
def cards(account: str, by: str = "all", text: str = "") -> list[EfsCardRow]:
    if by == "all":
        return [row for policy in config.EMANAGER_POLICIES[account] for row in cards(account, "policy", policy)]
    if by not in LOOKUPS:
        raise EfsError(f"Card Lookup cannot search by {by!r}; choose all or one of: {', '.join(LOOKUPS)}")
    if not text.strip():
        raise EfsError(f"Say what to look up by {by}.")
    efs_web.act_as(account)
    form = efs_web.fetch("/cards/CardLookup.action").form_with("searchCard")
    fields = {**form.fields, "lookupInfoRadio": LOOKUPS[by], "cardSearchTxt": text.strip()}
    rows = efs_web.send(form, fields, "searchCard").rows.get("cardSummary", [])
    # the heading row has names, not a card id
    return [_card_row(cells) for cells in rows if len(cells) >= 8 and cells[1].isdigit()]


# One card's own page.
def card(account: str, row: EfsCardRow) -> EfsCard:
    efs_web.act_as(account)
    return _card(_card_page(row))


# Sets a card's status (ACTIVE, INACTIVE, HOLD), every other setting left as it is. Returns the card as eManager shows
# it afterwards.
def set_status(account: str, row: EfsCardRow, status: str) -> EfsCard:
    if status not in STATUSES:
        raise EfsError(f"A card status is one of {', '.join(STATUSES)}, not {status!r}.")
    efs_web.act_as(account)
    page = _card_page(row)
    before = _card(page)
    if before.status == status:
        return before
    if before.override:
        raise EfsError(f"Card {row.number} is in override mode; remove the override before changing its status.")
    form = page.form_with("saveCardInformation")
    # the contract choice stays locked, as it does on the website
    fields = {name: value for name, value in form.fields.items() if not name.startswith("policy.header.")}
    answer = efs_web.send(form, {**fields, "card.header.status": status}, "saveCardInformation")
    return _confirm(row, answer, {**_header(page), "card.header.status": status}, override=False)


# Puts an active card in override mode for 1-9 transactions, always for All Locations (the user, 2026-11-22);
# hand_enter ticks "Allow Hand Enter". "Product/Limit Override" is never ticked: it opens a limits page first, not
# recorded yet (seen live 2026-11-22).
def set_override(account: str, row: EfsCardRow, times: int, hand_enter: bool = False) -> EfsCard:
    if not 1 <= times <= MOST_TIMES:
        raise EfsError(f"An override lasts 1 to {MOST_TIMES} transactions, not {times}.")
    efs_web.act_as(account)
    page = _card_page(row)
    before = _card(page)
    if before.status != "ACTIVE":
        raise EfsError(f"Only an active card can be overridden; card {row.number} is {before.status}.")
    if before.override:
        raise EfsError(f"Card {row.number} is already in override mode; remove that override first.")
    form = efs_web.fetch(f"/cards/CardPromptManagement.action?overrideCard=overrideCard&cardOverride=-1"
                         f"&card.cardId={quote(row.card_id)}&card.displayNumber={quote(row.number)}"
                         ).form_with("overrideCard")
    if form.fields.get("card.cardId") != row.card_id:
        raise EfsError(f"eManager opened the override for a different card than {row.number}.")
    answer = efs_web.send(form, _override_fields(form.fields, times, hand_enter), "overrideCard")
    # eManager shows no page with the number of times afterwards (checked 2026-11-22): only override mode is confirmed
    return _confirm(row, answer, _header(page), override=True)


# Takes a card out of override mode, every other setting left as it is.
def remove_override(account: str, row: EfsCardRow) -> EfsCard:
    efs_web.act_as(account)
    page = _card_page(row)
    before = _card(page)
    if not before.override:
        return before
    form = page.form_with("deleteCardOverride")
    fields = {name: value for name, value in form.fields.items() if name not in NOT_SENT_ON_REMOVE}
    answer = efs_web.send(form, fields, "deleteCardOverride")
    return _confirm(row, answer, _header(page), override=False)


# Sets one prompt of a card (unit, driver-id or driver: see PROMPTS) to a value, everything else left as it is.
def set_prompt(account: str, row: EfsCardRow, prompt: str, value: str) -> EfsCard:
    if prompt not in PROMPTS:
        raise EfsError(f"A card prompt to edit is one of {', '.join(PROMPTS)}, not {prompt!r}.")
    if not value.strip():
        raise EfsError(f"Say the new {prompt}.")
    info_id, label = PROMPTS[prompt]
    value = value.strip()
    efs_web.act_as(account)
    page = _card_page(row)
    before = _card(page)
    if before.override:
        raise EfsError(f"Card {row.number} is in override mode; remove the override before editing it.")
    current = {name: old for name, _, old in before.prompts}.get(label)
    if current is None:
        raise EfsError(f"Card {row.number} has no {label} prompt.")
    if current.casefold() == value.casefold():
        return before
    # each prompt row has its own edit form, told apart by its row number
    edit = page.form_with("editInformation", {"infoIndex": _prompt_row(page, info_id)})
    form = efs_web.send(edit, edit.fields, "editInformation").form_with("updateCardPrompt")
    if (form.fields.get("card.cardId"), form.fields.get("cardInfo.infoId")) != (row.card_id, info_id):
        raise EfsError(f"eManager opened a different prompt than {label} of card {row.number}.")
    boxes = [box for box in VALUE_BOXES if box in form.fields]
    if len(boxes) != 1:
        raise EfsError(f"eManager's {label} edit form has no single value box any more. The site changed.")
    answer = efs_web.send(form, {**form.fields, boxes[0]: value}, "updateCardPrompt")
    after = _confirm(row, answer, _header(page), override=False)
    if _folded(after.prompts) != _folded(_with_value(before.prompts, label, value)):
        raise EfsError(f"Card {row.number}: {label} did not change as asked; its prompts now read {after.prompts}. "
                       "Check the card in eManager before doing anything else.")
    return after


# The row number of a card's prompt, read from the row's own forms (the delete button there is never pressed).
def _prompt_row(page: Page, info_id: str) -> str:
    for form in page.forms:
        if form.fields.get("cardInfo.infoId") == info_id and "infoIndex" in form.fields:
            return form.fields["infoIndex"]
    raise EfsError(f"eManager's card page no longer says which row is the {info_id} prompt. The site changed.")


# A card's prompts with one prompt's value replaced.
def _with_value(prompts: tuple, label: str, value: str) -> tuple:
    return tuple((name, check, value if name == label else old) for name, check, old in prompts)


# Prompts as compared after an edit, without case: Card Lookup prints a name in capitals however it was typed.
def _folded(prompts: tuple) -> tuple:
    return tuple((name, check, value.casefold()) for name, check, value in prompts)


# The override form as the website would send it for these choices.
def _override_fields(fields: dict, times: int, hand_enter: bool) -> dict:
    sent = {**fields, "cardOverride": str(times), "locationOverrideRadio": "ALL"}
    # the website switches the one-location box off for All Locations
    sent.pop("locationId", None)
    # a ticked box sends "true"; an unticked one sends nothing
    return sent | ({"handOverride": "true"} if hand_enter else {})


# Opens the card again after a change rather than trust eManager's answer, which is not always the card page.
# Stops when the settings or the override mode are not what was asked.
def _confirm(row: EfsCardRow, answer: Page, settings: dict[str, str], override: bool) -> EfsCard:
    page = _card_page(row)
    after = _card(page)
    if _header(page) != settings or after.override != override:
        raise EfsError(f"Card {row.number} did not change as asked (eManager answered {answer.url}). It now shows "
                       f"settings {_header(page)}, override {'on' if after.override else 'off'}. "
                       "Check the card in eManager before doing anything else.")
    return after


# A card's own page, checked to be that card.
def _card_page(row: EfsCardRow) -> Page:
    page = efs_web.fetch(f"/cards/CardPromptManagement.action?card.cardId={quote(row.card_id)}"
                         f"&card.displayNumber={quote(row.number)}")
    if page.form_with("saveCardInformation").fields.get("card.cardId") != row.card_id:
        raise EfsError(f"eManager opened a different card than {row.number} ({row.card_id}).")
    return page


# A Card Lookup row: card #, card id, policy, unit, driver id, driver name, X-Ref, status.
def _card_row(cells: list[str]) -> EfsCardRow:
    number, card_id, policy, unit, driver_id, driver_name, xref, status = cells[:8]
    return EfsCardRow(card_id, number, policy, unit, driver_id, driver_name, xref, status.upper())


# A card page's settings, as they would be sent back.
def _header(page: Page) -> dict[str, str]:
    fields = page.form_with("saveCardInformation").fields
    return {name: fields.get(name, "") for name in HEADER}


# A card page as an EfsCard. A card in override mode offers Remove Override on its page.
def _card(page: Page) -> EfsCard:
    form = page.form_with("saveCardInformation")
    fields = form.fields
    # prompt rows start with their source, Card or Policy: source, prompt, validation, value
    prompts = tuple(tuple(cells[1:4]) for rows in page.rows.values() for cells in rows
                    if len(cells) >= 4 and cells[0] in ("Card", "Policy"))
    return EfsCard(card_id=fields.get("card.cardId", ""), status=fields.get("card.header.status", ""),
                   hand_enter=fields.get("card.header.handEnter", ""),
                   info_source=fields.get("card.header.infoSource", ""),
                   mobile=fields.get("card.header.mobileTransaction", ""),
                   policy=fields.get("card.header.policyNumber", ""), xref=fields.get("card.header.companyXRef", ""),
                   expires=_labelled(page.html, "card.header.expireDate"),
                   last_used=_labelled(page.html, "card.header.lastUsedDate"),
                   override="deleteCardOverride" in form.buttons, prompts=prompts)


# The text printed right after a label on the card page: "Expire Date Oct 1, 2029".
def _labelled(source: str, label: str) -> str:
    found = re.search(rf'<label for="{re.escape(label)}">[^<]*</label>\s*([^<]*?)\s*<', source)
    return " ".join(markup.unescape(found.group(1)).split()) if found else ""
