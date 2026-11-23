# Tests Samsara's evidence for a statement: the gauge's biggest rise, each fill's verdict, and bought vs burned per truck.
from datetime import datetime, timedelta, timezone

from base.models import EfsLine, FillEvidence, FuelLine, FuelReading, TruckBurn
from features.accounting import evidence

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
STORE = (35.0, -97.0)  # Love's #1


# A diesel line of the statement; only what a test cares about is given.
def line(seq, gallons=100.0, state="OK", unit="226") -> EfsLine:
    return EfsLine("1", seq, f"{seq}-1", "2026-11-10", unit, "STROUD", state, "ULTRA LOW", gallons, gallons * 5, 0.0)


# Its Datatruck line.
def twin(line_id, location="LOVES #1", unit="0226") -> FuelLine:
    return FuelLine(line_id, "2026-11-10 06:00", "fuel", "ULSD", 100.0, 600.0, 500.0, 0.0, True, location, "STROUD", "OK",
                    "TAYLOR", unit, None, 7, "JOHN DOE", None, None)


# What Samsara showed: a rise from `low` to `high` %, the truck at (lat, lng) with an address.
def seen(line_id, low=20.0, high=80.0, lat=35.0, lng=-97.0, place="Main St, Stroud, OK, 74079") -> FillEvidence:
    return FillEvidence(line_id, low, high, T0, lat, lng, place)


# The biggest rise is measured from the lowest reading before it, and is filled at the first reading at 90% of it (30 ->
# 95: from 88.5 on, the 90 at 40 min); a falling gauge gives a negative rise; one reading, none.
def test_biggest_rise():
    pcts = [50, 40, 45, 30, 90, 85, 95]
    readings = [FuelReading(T0 + timedelta(minutes=10 * k), p) for k, p in enumerate(pcts)]
    assert evidence.biggest_rise(readings, T0, T0 + timedelta(hours=2)) == (30, 95, T0 + timedelta(minutes=40))
    falling = [FuelReading(T0, 60), FuelReading(T0 + timedelta(minutes=5), 50)]
    assert evidence.biggest_rise(falling, T0, T0 + timedelta(hours=1)) == (60, 50, T0 + timedelta(minutes=5))
    assert evidence.biggest_rise(readings[:1], T0, T0 + timedelta(hours=1)) is None


# A truck parked engine-off sends no readings: its last one before the window is the level it was filled from.
def test_biggest_rise_after_parking():
    readings = [FuelReading(T0 - timedelta(hours=10), 5), FuelReading(T0 + timedelta(hours=1), 96), FuelReading(T0 + timedelta(hours=1, minutes=4), 95)]
    assert evidence.biggest_rise(readings, T0, T0 + timedelta(hours=2)) == (5, 96, T0 + timedelta(hours=1))


# Each verdict: proven; rose too little for the gallons; didn't rise; away from the Love's store; another state at
# another station; no readings; not in Samsara; not looked up. Units "0226" and "226" are the same.
def test_fills():
    lines = [line(k) for k in range(8)]
    found = {0: twin(10), 1: twin(11), 2: twin(12), 3: twin(13), 4: twin(14, "PILOT #9"), 5: twin(15), 6: twin(16, unit="999"), 7: twin(17)}
    seen_by_id = {10: seen(10), 11: seen(11, 20, 40), 12: seen(12, 50, 51), 13: seen(13, lat=35.5),
                  14: seen(14, place="I-35, Wichita, KS, 67201"), 15: FillEvidence(15, None, None, None, None, None, None)}
    result = evidence.fills(lines, found, seen_by_id, {"0226"}, {"1": STORE})
    verdicts = {g["verdict"]: g["fills"] for g in result["groups"]}
    assert verdicts == {evidence.PROVEN: 1, evidence.SHORT: 1, evidence.NO_RISE: 1, evidence.ELSEWHERE: 2,
                        evidence.NO_GAUGE: 1, evidence.NOT_IN_SAMSARA: 1, evidence.WAITING: 1}
    assert {f["verdict"] for f in result["doubtful"]} == set(evidence.DOUBTFUL)
    assert result["unit_differs"] == 1  # only "999" against "226"


# Bought minus burned minus what went into the tank (gauge change × the tank its fills imply); a truck not looked up
# has bought only; biggest unexplained first.
def test_bought_vs_burned():
    lines = [line(0), line(1), line(2, unit="555")]
    found = {0: twin(10), 1: twin(11), 2: twin(12, unit="555")}
    seen_by_id = {10: seen(10, 20, 70), 11: seen(11, 30, 80)}  # 100 gal for 50 points: a 200 gal tank
    burns = {"S1": TruckBurn("1", "S1", 150.0, 1000.0, 40.0, 60.0)}  # the tank ended 20 points fuller: 40 gal
    result = evidence.bought_vs_burned(lines, found, burns, {"0226": "S1"}, seen_by_id)
    first, second = result["trucks"]
    assert (first["unit"], first["bought"], first["burned"], first["tank"], first["into_tank"], first["unexplained"]) == \
           ("0226", 200.0, 150.0, 200, 40.0, 10.0)
    assert (second["unit"], second["burned"], second["unexplained"]) == ("555", None, None)
    assert result["looked_up"] is True
