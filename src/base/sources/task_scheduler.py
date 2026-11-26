# Windows' Task Scheduler on this PC (read-only): whether a scheduled task is running now and when it runs next.
import csv
import subprocess
from datetime import datetime

TIMEOUT_S = 10


# A task's state as Windows names it ("Ready" between runs, "Running", "Disabled") and its next run as a real moment
# (None when it has none); (None, None) when there is no such task or Windows doesn't answer in time.
def next_run(name: str) -> tuple[str | None, datetime | None]:
    try:
        answer = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "csv", "/nh"], capture_output=True,
                                text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, None
    rows = list(csv.reader(answer.stdout.splitlines()))
    if answer.returncode or not rows:
        return None, None
    _, when, state = rows[0]  # one row per start time, each with the task's next run
    try:  # on this PC's clock, written the US way: "11/26/2026 7:00:00 PM"
        return state, datetime.strptime(when, "%m/%d/%Y %I:%M:%S %p").astimezone()
    except ValueError:  # "N/A": no next run (the task is off)
        return state, None
