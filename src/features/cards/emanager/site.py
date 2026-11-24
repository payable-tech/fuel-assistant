# eManager, the EFS website, through its Chrome window: keeping the login alive, switching account, opening pages,
# and pressing only the allowed buttons.
import json
from urllib.parse import quote, urlencode

from features.cards import settings
from features.cards.emanager import window
from features.cards.emanager.window import EfsError
from features.cards.emanager.page import Form, Page, parse

BASE = "https://emgr.efsllc.com"
# The call eManager's own page makes while a person is active; it resets the 90-minute idle logout.
HEARTBEAT = "/security/Logon.action?resetSessionTimeout="
# The only buttons ever pressed: look up cards, save a card, put a card in override mode (a fraud-held card has its
# own button for it), take it out, open a prompt's edit form and update the prompt. Delete card, delete prompt,
# transfer, reset PIN and the rest are never sent.
BUTTONS = {"searchCard", "saveCardInformation", "overrideCard", "overrideFraudCard", "deleteCardOverride",
           "editInformation", "updateCardPrompt"}


# Keeps the login alive. True when eManager still has someone logged in.
def heartbeat() -> bool:
    # the page's own session manager also restarts the tab's logout countdown, when the tab has one
    text = window.run(f"window.efsllcSessionMgr && efsllcSessionMgr.sendHeartBeat();"
                          f"fetch({json.dumps(BASE + HEARTBEAT)}, {{credentials: 'same-origin'}}).then(r => r.text())")
    return "success" in (text or "")


# Who eManager has logged in right now; empty when nobody.
def logged_in() -> str:
    try:
        return fetch("/cards/Index.action").user
    except EfsError:
        return ""


# Makes the session act for one account ("ALIF", "DT"); switches only when it is on the other one.
def act_as(account: str) -> None:
    user = settings.EMANAGER_USERS.get(account)
    if not user:
        raise EfsError(f"No eManager user for {account!r}; known: {', '.join(settings.EMANAGER_USERS)}")
    if fetch("/cards/Index.action").user == user:
        return
    switched = fetch(f"/security/OWISSOLogon.action?selectedUserId={quote(user)}"
                     "&processUserSelection=processUserSelection")
    if switched.user != user:
        raise EfsError(f"eManager did not switch to {account} ({user}); it is still on {switched.user!r}.")


# Presses one button on a form. Only the buttons in BUTTONS can be pressed.
def send(form: Form, fields: dict[str, str], button: str) -> Page:
    if button not in BUTTONS or button not in form.buttons:
        raise EfsError(f"The assistant does not press {button!r} on eManager.")
    return fetch(form.action, {**fields, button: form.buttons[button]})


# Opens an eManager address inside the window; with fields, sends them the way the form does.
def fetch(path: str, fields: dict[str, str] | None = None) -> Page:
    options = {"credentials": "same-origin"}
    if fields is not None:
        options |= {"method": "POST", "body": urlencode(fields),
                    "headers": {"Content-Type": "application/x-www-form-urlencoded"}}
    got = window.run(f"fetch({json.dumps(BASE + path)}, {json.dumps(options)})"
                         ".then(async r => ({url: r.url, status: r.status, html: await r.text()}))")
    page = parse(got["url"], got["html"])
    if "_Incapsula_Resource" in page.html and not page.user:
        raise EfsError("EFS's bot check stopped the request. Reload the eManager tab, then try again.")
    if not page.user:
        raise EfsError("eManager is not logged in. Log in in the eManager window (efs-login), then try again.")
    if got["status"] != 200:
        raise EfsError(f"eManager answered {got['status']} for {path}.")
    return page
