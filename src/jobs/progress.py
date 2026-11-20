# Progress clock: when the refreshes last moved on (a job done, a pass over, one truck looked at). The scheduler's
# watchdog restarts the program when it stands still too long, so a long job ticks it as it goes and isn't taken for a hang.
import time

_last = time.monotonic()


# Notes that the refreshes moved on just now.
def tick() -> None:
    global _last
    _last = time.monotonic()


# Seconds since the refreshes last moved on.
def idle_sec() -> float:
    return time.monotonic() - _last
