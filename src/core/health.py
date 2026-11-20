# The heartbeat's rules (pure): what counts as a part being down, which problems are new or fixed since the last look,
# and the words of the alerts. The parts: each source copy, each scheduled job, the data itself (Samsara positions,
# fuel purchases, the Love's price sheet) and Telegram sending.
from dataclasses import replace
from datetime import datetime, timedelta

from core.fuel import CENTRAL
from models import Problem, SourceHealth

NIGHT_LATE = timedelta(hours=26)  # a nightly job not started this long: last night's run was missed


# Sources whose refreshes have failed for `down_min` or more: one failed try is a blip, the copy is kept meanwhile.
def source_problems(sources: list[SourceHealth], now: datetime, down_min: float) -> list[Problem]:
    found = []
    for s in sources:
        if not s.error:
            continue
        since = s.last_ok_at or s.last_try_at
        if s.last_ok_at is None or now - s.last_ok_at >= timedelta(minutes=down_min):
            found.append(Problem(s.name, f"not refreshing, the last good copy is from {_clock(since)}: {s.error[:200]}", since))
    return found


# Jobs that crashed on their last run, or are late: a periodic one not started for 3 of its intervals and at least
# `late_min` past its time, a nightly one (interval None) not started for 26 h. `runs`: (job, started, error) of the
# last run of each job; `schedule`: job -> minutes between runs. A job that never ran isn't judged.
def job_problems(runs: list[tuple[str, datetime, str | None]], schedule: dict[str, int | None], now: datetime,
                 late_min: float) -> list[Problem]:
    found = []
    for job, started, error in runs:
        if job not in schedule:
            continue
        every = schedule[job]
        late = NIGHT_LATE if every is None else max(timedelta(minutes=3 * every), timedelta(minutes=every + late_min))
        if error:
            found.append(Problem(job, f"crashed on its last run ({_clock(started)}): {error[:200]}", started))
        elif now - started > late:
            found.append(Problem(job, f"hasn't run since {_clock(started)}: the refreshes are behind", started))
    return found


# What the data itself shows: Samsara's newest truck position too old; no new fuel purchase for `purchase_h` hours in
# the day (`day_hours`, Central; ~6 come in an hour then); on a weekday after `sheet_by` (Central hour) no price sheet
# of today. `fuel_at`: the newest purchase as Datatruck writes it, Central "YYYY-MM-DD HH:MM"; `sheet_day`: "YYYY-MM-DD".
def data_problems(gps_at: datetime | None, fuel_at: str | None, sheet_day: str | None, now: datetime, gps_min: float,
                  purchase_h: float, day_hours: tuple[int, int], sheet_by: int) -> list[Problem]:
    found, local = [], now.astimezone(CENTRAL)
    if gps_at and now - gps_at > timedelta(minutes=gps_min):
        found.append(Problem("Samsara positions", f"the newest truck position is from {_clock(gps_at)}: Samsara isn't sending", gps_at))
    if fuel_at and day_hours[0] <= local.hour < day_hours[1]:
        newest = datetime.strptime(fuel_at, "%Y-%m-%d %H:%M").replace(tzinfo=CENTRAL)
        if now - newest > timedelta(hours=purchase_h):
            found.append(Problem("Fuel purchases coming in", f"no new purchase in Datatruck since {_clock(newest)}", newest))
    if sheet_day and local.weekday() < 5 and local.hour >= sheet_by and sheet_day < local.date().isoformat():
        found.append(Problem("Love's price sheet", f"today's sheet hasn't come in; the newest is of {sheet_day}"))
    return found


# Fuel messages to live trucks that weren't sent (`unsent` of the last `window_min` minutes): Telegram sending fails.
def send_problems(unsent: int, window_min: float) -> list[Problem]:
    if not unsent:
        return []
    return [Problem("Telegram sending", f"{unsent} fuel message(s) to live trucks not sent in the last {window_min:.0f} min")]


# The problems to keep after a look and those that ended. `stored`: those kept from earlier looks, by component; one
# still found keeps whether its alert went out (so it is told once), and when it began if this look can't say.
def changes(found: list[Problem], stored: dict[str, Problem]) -> tuple[list[Problem], list[Problem]]:
    kept = [replace(p, since=p.since or stored[p.component].since, told=stored[p.component].told)
            if p.component in stored else p for p in found]
    still = {p.component for p in found}
    return kept, [p for c, p in stored.items() if c not in still]


# The alert for a problem that started.
def down_text(p: Problem) -> str:
    return f"🔴 Fuel assistant · {p.component}: {p.text}"


# The alert for a problem that ended, with how long it lasted when known.
def up_text(p: Problem, now: datetime) -> str:
    lasted = f" (down {_duration(now - p.since)})" if p.since else ""
    return f"🟢 Fuel assistant · {p.component}: working again{lasted}"


# The alert that the program itself was down (a crash, a power cut): from the heartbeat's last sign to now.
def gap_text(last: datetime, now: datetime) -> str:
    return (f"⚠️ Fuel assistant was down from {_clock(last)} to {_clock(now)} ({_duration(now - last)}): "
            "no fuel messages went out meanwhile")


# A moment as Central clock time, with the day when it isn't today: "18:32 CT" / "11-18 18:32 CT".
def _clock(moment: datetime) -> str:
    local = moment.astimezone(CENTRAL)
    today = datetime.now(CENTRAL).date()
    return f"{local:%H:%M} CT" if local.date() == today else f"{local:%m-%d %H:%M} CT"


# A span of time in words: "42 min", "15 h 10 min".
def _duration(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"
