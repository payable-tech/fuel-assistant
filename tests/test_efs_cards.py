# Tests the eManager card tools against a pretend eManager that answers the way the real site did in bob-agent's
# recordings: lookup, status, override, and the buttons never pressed.
import sys
from urllib.parse import parse_qsl, urlsplit

import pytest

import main
from models import EfsCardRow
from sources import efs_cards, efs_chrome, efs_page, efs_web

TOKENS = '<input type="hidden" name="_sourcePage" value="sp" /><input type="hidden" name="__fp" value="fp" />'
ROW = EfsCardRow("1000091368925", "556748******0806", "2", "3189", "3189", "JEAN Z", "", "INACTIVE")


# The page header: who is logged in, or the logon form when nobody is.
def header(user):
    return f"<span>Logged in as:&nbsp;{user} </span>" if user else "<form action='/security/Logon.action'></form>"


# Card Lookup with its search form and a results table of (number, card id, unit, name, status) rows.
def lookup_page(user, rows):
    cells = "".join(f"<tr><td><a href='#'>{number}</a></td><td> {card_id} </td><td>2</td><td>{unit}</td>"
                    f"<td>{unit}</td><td>{name}</td><td></td><td> {status} </td><td></td></tr>"
                    for number, card_id, unit, name, status in rows)
    return (f"{header(user)}<form method='post' action='/cards/CardLookup.action'>"
            "<input name='zonarOnly' type='hidden' value='false' />"
            "<input name='lookupInfoRadio' checked='checked' type='radio' value='NUMBER' />"
            "<input name='lookupInfoRadio' type='radio' value='UNIT' />"
            "<input name='cardSearchTxt' type='text' />"
            "<input name='searchCard' type='submit' value='Look Up Cards' />"
            f"<input name='resetSearch' type='submit' value='Reset' />{TOKENS}</form>"
            "<table id='cardSummary'><thead><tr><th>Card #</th><th>Card ID</th><th>Policy #</th><th>Unit</th>"
            "<th>Driver ID</th><th>Driver Name</th><th>X-Ref</th><th>Status</th><th>SmartFunds</th></tr></thead>"
            f"<tbody>{cells}</tbody></table>")


# A row of radio buttons, the chosen one ticked.
def radios(name, chosen, values):
    return "".join(f"<input type='radio' name='{name}' value='{v}' disabled='disabled'"
                   f"{' checked=checked' if v == chosen else ''} />" for v in values)


# The prompts of the pretend card, as the real card …0672 had them: (id, label, validation, value).
PROMPTS = (("DRID", "Driver ID", "Exact Match", "3189"), ("NAME", "Driver Name", "Report Only", "Jean Z"),
           ("UNIT", "Unit Number", "Exact Match", "3189"))


# The hidden fields every form on a card page carries.
def card_fields(card_id, index):
    return (f"<input name='card.cardId' type='hidden' value='{card_id}' />"
            "<input name='policy.policyNumber' type='hidden' value='2' />"
            "<input name='oldPolicyNumber' type='hidden' value='' />"
            f"<input name='infoIndex' type='hidden' value='{index}' />")


# The prompts table: one row per prompt, each with its own edit form and delete form (rows numbered from 1).
def prompt_table(card_id, prompts):
    rows = "".join(f"<tr><td> Card </td><td> {label} </td><td> {check} </td><td> {value} </td>"
                   f"<td><form method='post' action='/cards/CardPromptManagement.action'>{card_fields(card_id, n)}"
                   f"<input type='image' name='editInformation' src='edit.gif' />{TOKENS}</form></td>"
                   f"<td><form method='post' action='/cards/CardPromptManagement.action'>{card_fields(card_id, n)}"
                   f"<input name='cardInfo.infoId' type='hidden' value='{info_id}' />"
                   f"<input type='image' name='deleteCardPrompt' src='delete.gif' />{TOKENS}</form></td></tr>"
                   for n, (info_id, label, check, value) in enumerate(prompts, start=1))
    return f"<table><tr><th>Source</th><th>Prompt</th><th>Validation</th><th>Value</th></tr>{rows}</table>"


# One prompt's edit form: an Exact Match prompt keeps its value in matchValue, a Report Only one in reportValue.
def edit_page(user, card_id, index, prompt, status):
    info_id, _, check, value = prompt
    box = "cardInfo.matchValue" if check == "Exact Match" else "cardInfo.reportValue"
    return (f"{header(user)}<form method='post' action='/cards/CardPromptManagement.action'>"
            f"{card_fields(card_id, index)}<input name='editInfoAction' type='hidden' value='editInformation' />"
            f"<input name='cardInfo.infoId' type='hidden' value='{info_id}' />"
            f"<input name='cardInfo.validationType' type='hidden' value='{check.upper().replace(' ', '_')}' />"
            f"<input name='card.header.status' type='hidden' value='{status}' />"
            f"<input name='{box}' type='text' value='{value}' />"
            "<input name='updateCardPrompt' type='submit' value='Update' />"
            f"<input name='cancel' type='submit' value='Cancel' />{TOKENS}</form>")


# A card's own page: its settings form, the buttons it offers, and its prompts.
def card_page(user, card_id, status, hand_enter="DISALLOW", override=False, prompts=PROMPTS):
    return (f"{header(user)}"
            '<label for="card.header.expireDate">Expire Date</label> Oct 1, 2029 '
            '<label for="card.header.lastUsedDate">Last Used</label> Jan 24, 2026 &nbsp; <a>1</a>'
            "<form method='post' action='/cards/CardPromptManagement.action'>"
            f"<input name='card.cardId' type='hidden' value='{card_id}' />"
            "<input name='policy.policyNumber' type='hidden' value='2' />"
            + ("<input type='submit' name='deleteCardOverride' value='Remove Override' />" if override else "")
            + "<select name='card.header.policyNumber' disabled><option value='1'>1</option>"
            "<option value='2' selected='selected'>2</option></select>"
            "<input name='card.header.companyXRef' type='text' disabled />"
            "<select name='policy.header.contractId' disabled><option value='794698' selected>794698</option></select>"
            + radios("card.header.status", status, ("ACTIVE", "INACTIVE", "HOLD"))
            + radios("card.header.handEnter", hand_enter, ("ALLOW", "DISALLOW", "POLICY"))
            + radios("card.header.infoSource", "BOTH", ("CARD", "POLICY", "BOTH"))
            + radios("card.header.mobileTransaction", "DISALLOW", ("ALLOW", "DISALLOW", "POLICY"))
            + "<input type='submit' name='saveCardInformation' value='Save' disabled />"
            "<input type='submit' name='deleteThisCard' value='Delete This Card' />"
            f"<input type='submit' name='resetPin' value='Reset PIN' />{TOKENS}</form>"
            + prompt_table(card_id, prompts))


# The override form: times, where, the one-location box, the two tick boxes.
def override_page(user, card_id):
    times = "".join(f"<option value='{n}'{' selected' if n == 1 else ''}>{n}</option>" for n in range(1, 10))
    return (f"{header(user)}<form method='post' action='/cards/CardPromptManagement.action'>"
            f"<input name='card.cardId' type='hidden' value='{card_id}' />"
            "<input name='useNewVersion' type='hidden' value='false' />"
            f"<select name='cardOverride'>{times}</select>"
            "<input name='locationOverrideRadio' type='radio' value='ALL' />"
            "<input name='locationOverrideRadio' checked='checked' type='radio' value='NETWORK' />"
            "<input name='locationId' type='text' />"
            "<input name='lookUpLocation' type='submit' value='Lookup Location' />"
            "<input name='handOverride' type='checkbox' value='true' />"
            "<input name='promptOverride' type='checkbox' value='true' />"
            "<input name='overrideCard' type='submit' value='Override Card' />"
            f"<input name='cancelVelocityOverride' type='submit' value='Cancel' />{TOKENS}</form>")


# A pretend eManager: one session, one card, answering the way the real site did in the recordings.
class Site:
    # One card in a status, maybe in override mode; saves_hand_enter makes a save change hand enter too.
    def __init__(self, status="INACTIVE", override=False, saves_hand_enter=None, prompts=PROMPTS):
        self.user, self.status, self.override, self.saves_hand_enter = "Bobalif", status, override, saves_hand_enter
        self.hand_enter = "DISALLOW"
        self.prompts = [list(prompt) for prompt in prompts]
        self.sent = []

    # Answers one request like eManager, remembering what was sent.
    def fetch(self, path, fields=None):
        self.sent.append((path, fields))
        url = urlsplit(path)
        query, fields = dict(parse_qsl(url.query)), fields or {}
        if url.path.endswith("OWISSOLogon.action"):
            self.user = query["selectedUserId"]
        if url.path.endswith("CardLookup.action"):
            row = ("556748******0806", ROW.card_id, "3189", "JEAN Z", self.status.title())
            return efs_page.parse(path, lookup_page(self.user, [row]))
        if not url.path.endswith("CardPromptManagement.action"):
            return efs_page.parse(path, header(self.user))
        if query.get("overrideCard"):
            return efs_page.parse(path, override_page(self.user, ROW.card_id))
        if "saveCardInformation" in fields:
            self.status = fields["card.header.status"]
            self.hand_enter = self.saves_hand_enter or fields["card.header.handEnter"]
        if "overrideCard" in fields:
            self.override = True
        if "deleteCardOverride" in fields:
            self.override = False
        if "editInformation" in fields:
            index = int(fields["infoIndex"])
            return efs_page.parse(path, edit_page(self.user, ROW.card_id, index, self.prompts[index - 1], self.status))
        if "updateCardPrompt" in fields:
            prompt = self.prompts[int(fields["infoIndex"]) - 1]
            value = fields.get("cardInfo.matchValue") or fields.get("cardInfo.reportValue")
            # a name read back in another case than sent still counts (Card Lookup prints capitals anyway)
            prompt[3] = value.title() if prompt[0] == "NAME" else value
        return efs_page.parse(path, card_page(self.user, ROW.card_id, self.status, self.hand_enter, self.override,
                                              [tuple(prompt) for prompt in self.prompts]))

    # The forms sent with a button pressed.
    def posted(self, button):
        return [fields for _, fields in self.sent if fields and button in fields]


# The pretend eManager with an inactive card, put in place of the real one.
@pytest.fixture
def site(monkeypatch):
    site = Site()
    monkeypatch.setattr(efs_web, "fetch", site.fetch)
    return site


# The pretend eManager with an active card, maybe in override mode.
def active(monkeypatch, override=False):
    site = Site(status="ACTIVE", override=override)
    monkeypatch.setattr(efs_web, "fetch", site.fetch)
    return site


# Card Lookup searches by what was asked and reads each card with its status.
def test_card_lookup_reads_each_card_and_its_status(site):
    assert efs_cards.cards("ALIF", "unit", "3189") == [ROW]
    (fields,) = site.posted("searchCard")
    assert fields["lookupInfoRadio"] == "UNIT" and fields["cardSearchTxt"] == "3189"
    assert fields["searchCard"] == "Look Up Cards" and "resetSearch" not in fields


# "All cards" looks up each policy in turn, because eManager's own "All Cards" finds nothing.
def test_all_cards_looks_up_each_policy(site):
    efs_cards.cards("ALIF")
    assert [(f["lookupInfoRadio"], f["cardSearchTxt"]) for f in site.posted("searchCard")] == [("POLICY", "1"),
                                                                                               ("POLICY", "2")]


# A card page gives its settings, whether it is in override mode, and its prompts.
def test_a_card_page_gives_its_settings_override_mode_and_prompts(site):
    card = efs_cards.card("ALIF", ROW)
    assert (card.status, card.hand_enter, card.policy, card.expires, card.last_used, card.override) == (
        "INACTIVE", "DISALLOW", "2", "Oct 1, 2029", "Jan 24, 2026", False)
    assert card.prompts == (("Driver ID", "Exact Match", "3189"), ("Driver Name", "Report Only", "Jean Z"),
                            ("Unit Number", "Exact Match", "3189"))


# A status change sends every other setting unchanged, and the card is opened again afterwards.
def test_a_status_change_sends_every_other_setting_unchanged_and_opens_the_card_again(site):
    assert efs_cards.set_status("ALIF", ROW, "ACTIVE").status == "ACTIVE"
    (fields,) = site.posted("saveCardInformation")
    assert not site.sent[-1][1], "the card is opened again after the save"
    assert fields["card.header.status"] == "ACTIVE" and fields["card.header.handEnter"] == "DISALLOW"
    assert fields["saveCardInformation"] == "Save" and "policy.header.contractId" not in fields
    assert not {"deleteThisCard", "resetPin"} & set(fields)


# A card already in the status asked for is left alone: nothing is sent.
def test_a_card_already_in_that_status_is_not_sent(site):
    efs_cards.set_status("ALIF", ROW, "INACTIVE")
    assert not any(fields for _, fields in site.sent)


# A save eManager ignored stops, saying how the card still reads.
def test_a_save_eManager_ignored_stops_and_says_the_card_is_unchanged(monkeypatch):
    site = Site()

    # eManager answers the save with some other page and keeps the card as it was
    def ignores_saves(path, fields=None):
        if fields and "saveCardInformation" in fields:
            return efs_page.parse(path, header("Bobalif"))
        return site.fetch(path, fields)

    monkeypatch.setattr(efs_web, "fetch", ignores_saves)
    with pytest.raises(efs_web.EfsError, match="'card.header.status': 'INACTIVE'"):
        efs_cards.set_status("ALIF", ROW, "ACTIVE")


# A save that also changed another setting stops and says to check the card.
def test_a_save_that_changed_another_setting_stops(monkeypatch):
    monkeypatch.setattr(efs_web, "fetch", Site(saves_hand_enter="ALLOW").fetch)
    with pytest.raises(efs_web.EfsError, match="Check the card in eManager"):
        efs_cards.set_status("ALIF", ROW, "ACTIVE")


# Only ACTIVE, INACTIVE and HOLD can be set.
def test_only_active_inactive_and_hold_can_be_set(site):
    with pytest.raises(efs_web.EfsError, match="ACTIVE, INACTIVE, HOLD"):
        efs_cards.set_status("ALIF", ROW, "DELETED")


# An override sends the times and where, and the card is then in override mode.
def test_an_override_sends_the_times_and_where(monkeypatch):
    site = active(monkeypatch)
    assert efs_cards.set_override("ALIF", ROW, 1).override
    (fields,) = site.posted("overrideCard")
    assert fields["cardOverride"] == "1" and fields["locationOverrideRadio"] == "ALL"
    assert "locationId" not in fields, "the website switches the one-location box off for All Locations"
    assert not {"handOverride", "promptOverride", "lookUpLocation", "cancelVelocityOverride"} & set(fields)


# Hand enter is ticked only when asked; product/limit never (it opens a limits page first).
def test_an_override_ticks_hand_enter_only_when_asked_and_never_product_limits(monkeypatch):
    site = active(monkeypatch)
    efs_cards.set_override("ALIF", ROW, 3, hand_enter=True)
    (fields,) = site.posted("overrideCard")
    assert (fields["cardOverride"], fields["locationOverrideRadio"]) == ("3", "ALL")
    assert fields["handOverride"] == "true" and "promptOverride" not in fields


# Only an active card without an override can be overridden.
def test_only_an_active_card_without_an_override_can_be_overridden(monkeypatch, site):
    with pytest.raises(efs_web.EfsError, match="Only an active card"):
        efs_cards.set_override("ALIF", ROW, 1)
    active(monkeypatch, override=True)
    with pytest.raises(efs_web.EfsError, match="already in override mode"):
        efs_cards.set_override("ALIF", ROW, 1)


# An override lasts 1 to 9 transactions.
def test_an_override_lasts_one_to_nine_transactions(site):
    for times in (0, 10):
        with pytest.raises(efs_web.EfsError, match="1 to 9"):
            efs_cards.set_override("ALIF", ROW, times)


# Removing an override sends what the website sends, and the card is out of override mode.
def test_removing_an_override_sends_what_the_website_sends(monkeypatch):
    site = active(monkeypatch, override=True)
    assert not efs_cards.remove_override("ALIF", ROW).override
    (fields,) = site.posted("deleteCardOverride")
    assert fields["deleteCardOverride"] == "Remove Override"
    assert not set(efs_cards.NOT_SENT_ON_REMOVE) & set(fields)


# A card in override mode keeps its status until the override is removed.
def test_a_card_in_override_mode_keeps_its_status(monkeypatch):
    active(monkeypatch, override=True)
    with pytest.raises(efs_web.EfsError, match="remove the override"):
        efs_cards.set_status("ALIF", ROW, "INACTIVE")


# Delete, reset PIN and cancel are never pressed.
def test_delete_reset_pin_and_cancel_are_never_pressed():
    form = efs_page.parse("u", card_page("Bobalif", ROW.card_id, "ACTIVE")).form_with("saveCardInformation")
    for button in ("deleteThisCard", "resetPin"):
        with pytest.raises(efs_web.EfsError, match="does not press"):
            efs_web.send(form, form.fields, button)
    form = efs_page.parse("u", override_page("Bobalif", ROW.card_id)).form_with("overrideCard")
    with pytest.raises(efs_web.EfsError, match="does not press"):
        efs_web.send(form, form.fields, "cancelVelocityOverride")
    form = efs_page.parse("u", card_page("Bobalif", ROW.card_id, "ACTIVE")).form_with("deleteCardPrompt")
    with pytest.raises(efs_web.EfsError, match="does not press"):
        efs_web.send(form, form.fields, "deleteCardPrompt")
    form = efs_page.parse("u", edit_page("Bobalif", ROW.card_id, 3, PROMPTS[2], "ACTIVE")).form_with("updateCardPrompt")
    with pytest.raises(efs_web.EfsError, match="does not press"):
        efs_web.send(form, form.fields, "cancel")


# A prompt edit opens that prompt's own row form, then sends the new value with everything else as the form had it.
def test_a_prompt_edit_opens_that_rows_form_and_sends_the_new_value(site):
    after = efs_cards.set_prompt("ALIF", ROW, "unit", "99999")
    assert ("Unit Number", "Exact Match", "99999") in after.prompts
    (opened,) = site.posted("editInformation")
    assert (opened["infoIndex"], opened["card.cardId"]) == ("3", ROW.card_id)
    (update,) = site.posted("updateCardPrompt")
    assert (update["cardInfo.infoId"], update["cardInfo.matchValue"], update["card.header.status"]) == (
        "UNIT", "99999", "INACTIVE")
    assert not site.posted("deleteCardPrompt") and not site.posted("cancel")


# A driver name goes in the Report Only box, and the name read back in another case counts as done.
def test_the_driver_name_goes_in_the_report_box_and_eManagers_case_is_accepted(site):
    after = efs_cards.set_prompt("ALIF", ROW, "driver", "ALIF UZ CORP")
    assert ("Driver Name", "Report Only", "Alif Uz Corp") in after.prompts
    (update,) = site.posted("updateCardPrompt")
    assert update["cardInfo.reportValue"] == "ALIF UZ CORP" and "cardInfo.matchValue" not in update


# A prompt already at that value is left alone: nothing is sent.
def test_a_prompt_already_set_is_not_sent(site):
    efs_cards.set_prompt("ALIF", ROW, "driver", "JEAN Z")
    assert not site.posted("editInformation")


# A card without that prompt says so, and nothing is sent.
def test_a_card_without_that_prompt_says_so(monkeypatch):
    site = Site(prompts=PROMPTS[:1])
    monkeypatch.setattr(efs_web, "fetch", site.fetch)
    with pytest.raises(efs_web.EfsError, match="has no Unit Number prompt"):
        efs_cards.set_prompt("ALIF", ROW, "unit", "99999")
    assert not site.posted("editInformation")


# An edit eManager ignored stops and says how the prompts read.
def test_a_prompt_edit_eManager_ignored_stops(monkeypatch):
    site = Site()

    # eManager answers the update with the card page but keeps the old value
    def ignores_updates(path, fields=None):
        if fields and "updateCardPrompt" in fields:
            return site.fetch(path, {name: value for name, value in fields.items() if name != "updateCardPrompt"})
        return site.fetch(path, fields)

    monkeypatch.setattr(efs_web, "fetch", ignores_updates)
    with pytest.raises(efs_web.EfsError, match="Unit Number did not change as asked"):
        efs_cards.set_prompt("ALIF", ROW, "unit", "99999")


# The session switches account only when it is on the other one.
def test_the_session_switches_account_only_when_it_is_on_the_other_one(site):
    efs_cards.cards("ALIF", "unit", "3189")
    assert not any("OWISSOLogon" in path for path, _ in site.sent)
    efs_cards.cards("DT", "unit", "3189")
    assert any("selectedUserId=BOB_DT" in path for path, _ in site.sent)


# A logged-out session says to log in.
def test_a_logged_out_session_says_to_log_in(monkeypatch):
    page = {"url": "https://emgr.efsllc.com/security/logon.jsp", "status": 200, "html": header("")}
    monkeypatch.setattr(efs_chrome, "run", lambda script: page)
    with pytest.raises(efs_web.EfsError, match="not logged in"):
        efs_web.fetch("/cards/Index.action")


# The bot check page says to reload the tab.
def test_the_bot_check_page_says_to_reload_the_tab(monkeypatch):
    page = {"url": "https://emgr.efsllc.com/", "status": 200, "html": "<script src='/_Incapsula_Resource?x=1'>"}
    monkeypatch.setattr(efs_chrome, "run", lambda script: page)
    with pytest.raises(efs_web.EfsError, match="bot check"):
        efs_web.fetch("/cards/Index.action")


# Runs one command line of main.py.
def run_command(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    main.main()


# efs-card without --send shows the card and the change, and sends nothing.
def test_efs_card_without_send_changes_nothing(monkeypatch, capsys):
    site = active(monkeypatch)
    run_command(monkeypatch, "efs-card", "ALIF", "3189", "--override", "1")
    assert not site.posted("overrideCard")
    assert "Would override for 1 transaction(s), all locations" in capsys.readouterr().out


# efs-card --send makes the change, once.
def test_efs_card_with_send_makes_the_change_once(monkeypatch):
    site = active(monkeypatch)
    run_command(monkeypatch, "efs-card", "ALIF", "3189", "--override", "1", "--send")
    assert len(site.posted("overrideCard")) == 1


# A unit that only starts the same way is not the card asked for: nothing is changed.
def test_efs_card_needs_the_exact_unit(monkeypatch):
    site = active(monkeypatch)
    with pytest.raises(SystemExit, match="0 cards found"):
        run_command(monkeypatch, "efs-card", "ALIF", "318", "--status", "INACTIVE", "--send")
    assert not site.posted("saveCardInformation")


# efs-card --set edits one prompt, only with --send.
def test_efs_card_set_edits_one_prompt_only_with_send(monkeypatch):
    site = active(monkeypatch)
    run_command(monkeypatch, "efs-card", "ALIF", "3189", "--set", "driver", "ALIF UZ CORP")
    assert not site.posted("updateCardPrompt")
    run_command(monkeypatch, "efs-card", "ALIF", "3189", "--set", "driver", "ALIF UZ CORP", "--send")
    assert [fields["cardInfo.reportValue"] for fields in site.posted("updateCardPrompt")] == ["ALIF UZ CORP"]
