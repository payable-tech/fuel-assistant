# Watchdog: restarts the program when the jobs freeze. A job hanging (e.g. on a network call that never answers) doesn't
# crash, so nothing would start the program again: the watchdog sees that nothing has moved for STUCK_MIN and ends the
# program, and run.bat starts it fresh. The scheduler and the long jobs tell it they are alive with `tick` (a job done,
# a pass over, one truck looked at), so a long job isn't taken for a hang. It talks to nothing (no database, no
# network), so it still works when everything else is stuck.
import logging
import os
import threading
import time

from base import config

log = logging.getLogger(__name__)
_last = time.monotonic()  # when the jobs last moved on


# Notes that the jobs moved on just now.
def tick() -> None:
    global _last
    _last = time.monotonic()


# Seconds since the jobs last moved on.
def idle_sec() -> float:
    return time.monotonic() - _last


# True when the jobs have gone this many seconds without moving on: far longer than any job runs without a tick
# (~17 min at most; the engine ticks after each truck, so its slow first pass after a restart counts as moving).
def stuck(seconds_idle: float) -> bool:
    return seconds_idle > config.STUCK_MIN * 60


# Starts the watchdog in a background thread that ends with the program.
def start() -> threading.Thread:
    thread = threading.Thread(target=_watch, name="watchdog", daemon=True)
    thread.start()
    return thread


# Forever: when the jobs have not moved on for STUCK_MIN, ends the whole program, so run.bat starts it again fresh.
# A crash ends it anyway; a hang wouldn't.
def _watch() -> None:
    while True:
        time.sleep(60)
        if stuck(idle_sec()):
            # ends the program even if the lines below can't be written (a stuck console blocks every log line)
            threading.Timer(10, os._exit, args=(1,)).start()
            log.error("The refreshes made no progress for %d min: restarting the program", config.STUCK_MIN)
            logging.shutdown()  # the line above reaches the log file before the program ends
            os._exit(1)
