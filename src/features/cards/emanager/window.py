# The Chrome window eManager runs in: start it, find the eManager tab, run a script inside that tab, and hold it for
# one piece of work at a time. eManager's bot check (Imperva) lets only a real browser through, so every request is
# sent from inside the tab.
import json
import msvcrt
import os
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from websockets.sync.client import connect

from features.cards import settings

HOME = "https://emgr.efsllc.com/"
# Where Windows installs Chrome.
CHROME = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
)
# The file whose lock says a program is working in the window (the card agent, the card cleanup).
LOCK = settings.EMANAGER_PROFILE.parent / "efs-window.lock"
WAIT_S = 0.2   # how often a program waiting for the window looks again


# The window or eManager is not as expected; the message says what to do. A RuntimeError, so a command prints it
# as a short error.
class EfsError(RuntimeError):
    pass


# Opens the eManager window, unless it is already open.
def start(wait_seconds: float = 20) -> None:
    if _tabs():
        return
    program = next((path for path in CHROME if path.is_file()), None)
    if program is None:
        raise EfsError("Chrome is not installed where Windows keeps it. Install Google Chrome, then try again.")
    settings.EMANAGER_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(program), f"--remote-debugging-port={settings.EMANAGER_CHROME_PORT}",
                      f"--user-data-dir={settings.EMANAGER_PROFILE}", "--no-first-run", "--no-default-browser-check",
                      HOME])
    deadline = time.monotonic() + wait_seconds
    while not _tabs():
        if time.monotonic() > deadline:
            raise EfsError("The eManager window did not start. Close any Chrome window on its profile and try again.")
        time.sleep(0.5)


# Holds the window for one piece of work (a card change, a lookup), waiting while another program on this PC holds it.
# eManager has one session (one account at a time, a prompt edit in two steps), so two programs at once could mix up
# a card. Windows lets the lock go when the program holding it ends.
@contextmanager
def held():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+b") as file:
        file.seek(0)  # the lock is on the file's first byte; locking past its end is allowed
        while True:
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(WAIT_S)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


# Runs a script in the eManager tab and returns its value; a script that returns a promise is awaited.
def run(script: str, timeout: float = 120):
    with connect(_emanager_tab(), max_size=None, open_timeout=10) as socket:
        socket.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                "params": {"expression": script, "awaitPromise": True, "returnByValue": True}}))
        # Chrome may send other messages first; the answer is the one with our id
        while (reply := json.loads(socket.recv(timeout=timeout))).get("id") != 1:
            pass
    if "error" in reply:
        raise EfsError(f"Chrome refused the script: {reply['error'].get('message')}")
    result = reply["result"]
    if "exceptionDetails" in result:
        raise EfsError(f"The script failed in the eManager tab: {result['exceptionDetails'].get('text')}")
    return result["result"].get("value")


# The control address of the open eManager tab.
def _emanager_tab() -> str:
    pages = [tab for tab in _tabs() if tab.get("type") == "page"]
    on_emanager = [tab for tab in pages if tab.get("url", "").startswith(HOME)]
    if on_emanager:
        return on_emanager[0]["webSocketDebuggerUrl"]
    if pages:
        # e.g. EFS's sign-in page (ent.tch.com) while someone logs in
        where = urlsplit(pages[0].get("url", "")).netloc or "another page"
        raise EfsError(f"The eManager window shows {where}, not eManager. Finish logging in there, or open {HOME}")
    raise EfsError("The eManager window is not open. Run: efs-login")


# The tabs the window reports; empty when it is not running.
def _tabs() -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{settings.EMANAGER_CHROME_PORT}/json/list", timeout=2) as answer:
            return json.load(answer)
    except OSError:
        return []
