# Statement evidence job: for the EFS statements read, asks Samsara (1) once per statement, every truck's engine fuel
# used, miles and gauge over the statement's days, and (2) once per diesel fill, the gauge's biggest rise around it and
# where the truck was then, a few trucks per run so the other jobs keep their turn. Kept in statement_burn and
# fill_evidence; the Accounting view reads them.
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from base import config, fuel, geo
from base.models import EfsStatement, FillEvidence, FuelLine, TruckBurn
from base.sources import samsara
from base.store import db
from features.accounting import accounting, evidence

log = logging.getLogger(__name__)

GPS_AROUND = timedelta(minutes=5)  # the truck's place is its GPS point nearest the moment, looked for this far either side


# Looks up what is missing, newest statement first: the fuel used, then the fills of up to `trucks` trucks (None: all).
# Returns how many fills were looked up.
def run(trucks: int | None = config.EVIDENCE_TRUCKS_PER_RUN) -> int:
    with db.connect() as conn:
        statements = db.statements(conn)
        samsara_ids = {t.unit: t.samsara_id for t in db.fleet(conn)}
    waiting: dict[str, list[FuelLine]] = defaultdict(list)  # unit -> its fills not looked up yet
    for statement in statements:
        fills = _burn_and_fills(statement)
        for f in fills:
            if f.unit in samsara_ids:
                waiting[f.unit].append(f)
    units = list(waiting)[:trucks]
    looked_up = 0
    for unit in units:  # kept truck by truck: a run cut short keeps what it found
        found = _truck(samsara_ids[unit], waiting[unit])
        with db.connect() as conn:
            db.add_fill_evidence(conn, found)
        looked_up += len(found)
    log.info("Fill evidence: %d fills of %d trucks looked up, %d trucks wait", looked_up, len(units), len(waiting) - len(units))
    return looked_up


# One statement: looks up its trucks' fuel used when not done yet, and returns its diesel fills (their Datatruck lines)
# with no evidence yet.
def _burn_and_fills(statement: EfsStatement) -> list[FuelLine]:
    with db.connect() as conn:
        _, lines = db.statement(conn, statement.statement_no)
        days = sorted(l.day for l in lines)
        datatruck = db.fuel_lines_between(conn, fuel.shift_days(days[0], -1), fuel.shift_days(days[-1], 1))
        burned = db.statement_burn(conn, statement.statement_no)
    found = accounting.match([l for l in lines if accounting.is_purchase(l)], datatruck)
    if not burned:
        try:
            _burn(statement.statement_no, days[0], days[-1])
        except Exception as error:  # Samsara down or slow: tried again next run; the fills go on meanwhile
            log.warning("Fuel used for statement %s not looked up: %r", statement.statement_no, error)
    diesel = [found[l.seq] for l in lines if l.seq in found and accounting.row_of(l) == "DIESEL TOTAL"]
    with db.connect() as conn:
        done = db.fill_evidence(conn, [f.line_id for f in diesel])
    return [f for f in diesel if f.line_id not in done]


# Every Samsara truck's fuel used, miles and gauge from the start of the first day to the end of the last (Central).
# Not before those days are over: a part of them would be kept as if it were all.
def _burn(statement_no: str, first_day: str, last_day: str) -> None:
    start = datetime.combine(date.fromisoformat(first_day), time(), fuel.CENTRAL)
    end = datetime.combine(date.fromisoformat(last_day) + timedelta(days=1), time(), fuel.CENTRAL)
    if end > datetime.now(fuel.CENTRAL):
        return
    fresh = timedelta(days=config.GAUGE_FRESH_DAYS)
    used, before, after = samsara.fuel_used(start, end), samsara.gauges_at(start, fresh), samsara.gauges_at(end, fresh)
    burns = [TruckBurn(statement_no, vid, gallons, miles, before.get(vid), after.get(vid)) for vid, (gallons, miles) in used.items()]
    with db.connect() as conn:
        db.add_statement_burn(conn, statement_no, burns)
    log.info("Statement %s: fuel used of %d Samsara trucks looked up", statement_no, len(burns))


# One truck's fills, one Samsara call each; none when a call fails (the truck is tried again next run).
def _truck(samsara_id: str, fills: list[FuelLine]) -> list[FillEvidence]:
    try:
        return [_fill(samsara_id, f) for f in fills]
    except Exception as error:  # Samsara down or slow: this truck waits for the next run, the others go on
        log.warning("Fills of Samsara vehicle %s not looked up: %r", samsara_id, error)
        return []


# Around one fill: the gauge's biggest rise and where the truck was when it topped out (at Datatruck's time without one).
# Two small calls: the gauge over the hours around the fill, then the GPS just around that moment.
def _fill(samsara_id: str, line: FuelLine) -> FillEvidence:
    at = fuel.utc(line.fueled_at)
    start, end = at - timedelta(hours=config.EVIDENCE_BEFORE_H), at + timedelta(hours=config.EVIDENCE_AFTER_H)
    readings = samsara.fuel_history(samsara_id, at - timedelta(hours=config.EVIDENCE_PARKED_H), end)
    rise = evidence.biggest_rise(readings, start, end)
    moment = rise[2] if rise else at
    where = geo.where_at(samsara.placed_track(samsara_id, moment - GPS_AROUND, moment + GPS_AROUND), moment)
    return FillEvidence(line_id=line.line_id, gauge_from=rise[0] if rise else None, gauge_to=rise[1] if rise else None,
                        risen_at=rise[2] if rise else None, lat=where.lat if where else None,
                        lng=where.lng if where else None, place=where.place if where else None)
