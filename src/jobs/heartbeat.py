# Heartbeat: every few minutes, in its own thread (so it still works when the refreshes are stuck or busy), checks every
# part of the program (core/health) and alerts once in Telegram when one breaks and once when it works again. On start it
# also tells if the program itself was down (a crash, a power cut). What it finds is kept in `health_alerts`, which the
# dashboard shows. The user's go, 2026-11-19, after the Datatruck login ran out overnight and nobody knew.
# It also asks Google itself at every check (sources/google_reach) and records the answer in `source_health` like a
# source refresh: nothing else would show Google out of reach (the office network refused it unseen, 2026-11-22).
import logging
import time
from datetime import datetime, timedelta, timezone

import config
import db
from core import health
from models import Problem
from sources import google_reach, telegram

log = logging.getLogger(__name__)
NAME = "Heartbeat"  # its runs are recorded in job_runs under this name; the Data tab lists it with the refreshes
GOOGLE = "Google Maps"  # the Routes and Places APIs in source_health: one row, so one alert when Google is out of reach


# Forever: tells if the program was down before this start, then checks every HEARTBEAT_MIN. `schedule`: each
# scheduled job's minutes between runs (None for a nightly one), to tell a late job.
def loop(schedule: dict[str, int | None]) -> None:
    _tell_gap(datetime.now(timezone.utc))
    while True:
        try:
            run(schedule, datetime.now(timezone.utc))
        except Exception:  # a check failing (the database busy) must not end the heartbeat: next time it tries again
            log.exception("Heartbeat check failed")
        time.sleep(config.HEARTBEAT_MIN * 60)


# One check: asks Google, finds what is down, alerts on what started or ended, and keeps the rest for the dashboard.
def run(schedule: dict[str, int | None], now: datetime) -> list[Problem]:
    started = db.now()
    google_error = google_reach.unreachable()  # asked before the database is opened: a slow network mustn't hold it
    with db.connect() as conn:
        db.record_source(conn, GOOGLE, now, google_error)
        found = _problems(conn, schedule, now)
        kept, ended = health.changes(found, db.health_alerts(conn))
    for p in ended:
        if not p.told or _send(health.up_text(p, now)):  # never told: nothing to take back
            with db.connect() as conn:
                db.clear_alert(conn, p.component)
    for p in kept:
        told = p.told or _send(health.down_text(p))  # an alert that couldn't go out is tried again next time
        with db.connect() as conn:
            db.set_alert(conn, Problem(p.component, p.text, p.since, told))
    with db.connect() as conn:
        db.record_job(conn, NAME, started, db.now(), None)
    return kept


# Everything down now: sources failing, jobs crashed or late, data not coming in, messages not going out.
def _problems(conn, schedule: dict[str, int | None], now: datetime) -> list[Problem]:
    runs = [(r["job"], datetime.fromisoformat(r["started_at"]), r["error"]) for r in db.job_runs(conn).values()]
    gps_at, fuel_at, sheet_day = db.newest_data(conn)
    return (health.source_problems(db.source_health(conn), now, config.SOURCE_DOWN_MIN)
            + health.job_problems(runs, schedule, now, config.JOB_LATE_MIN)
            + health.data_problems(gps_at, fuel_at, sheet_day, now, config.GPS_STALE_MIN, config.PURCHASE_STALE_H,
                                   config.PURCHASE_DAY_HOURS, config.PRICE_SHEET_BY)
            + health.send_problems(_unsent(conn, now), config.UNSENT_MIN))


# Fuel messages made for live trucks that have a group, in the last UNSENT_MIN minutes, that didn't go out. A truck
# with no group can't be sent to; that isn't Telegram failing (the Data tab's holes list it).
def _unsent(conn, now: datetime) -> int:
    since = now - timedelta(minutes=config.UNSENT_MIN)
    grouped = {t.unit for t in db.fleet(conn) if t.chat_id}
    return sum(1 for r in db.recommendations(conn, since.date().isoformat())
               if r.made_at >= since and r.unit in config.LIVE_UNITS and r.unit in grouped and not r.sent_at)


# On start: when the heartbeat last ran is the last sign of life; a gap over DOWN_GAP_MIN means the program was down.
def _tell_gap(now: datetime) -> None:
    try:
        with db.connect() as conn:
            last = db.job_runs(conn).get(NAME)
        if last and last["finished_at"]:
            ended = datetime.fromisoformat(last["finished_at"])
            if now - ended > timedelta(minutes=config.DOWN_GAP_MIN):
                _send(health.gap_text(ended, now))
    except Exception:
        log.exception("Heartbeat could not check the time down")


# Sends an alert to ALERT_CHAT_ID (the test group when unset). True when it went out, or when there is nowhere to send
# (the dashboard shows the problem anyway); False when sending failed, so it is tried again.
def _send(text: str) -> bool:
    chat = config.ALERT_CHAT_ID or config.TEST_CHAT_ID
    log.warning("Health: %s", text)
    if not chat:
        return True
    try:
        telegram.send(chat, text)
        return True
    except Exception as error:
        log.warning("Health alert not sent: %r", error)
        return False
