# Tests what came of the messages: the fill after each one, what going there saved, and the fills no message asked for.
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from base.models import FuelLine, FuelStop, Recommendation, TrackPoint
from features.engine import outcomes


# What became of a recommendation: the first diesel stop after it, and what going there would have saved.
def test_outcome():
    made = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)
    rec = Recommendation(1, "0226", "Jacob", 1, "L", made, "stop", "412", "Love's Dunn, NC", 109.0, 30.0, 20.0, 17.0, 130.0, None,
                         "hard_stop", 5.25, 5.69, "2026-10-19", 6.69, 5.35, 13.0, "text", "open", None)

    def line(store: str, gallons: float, billed: float) -> FuelLine:
        return FuelLine(1, "2026-10-19 20:28", "fuel", "ULSD", gallons, gallons * 6, billed, 0.0, False, f"LOVES #{store} TRAVEL STOP",
                        "Dillon", "SC", "TTL", "0226", "company", 7, "Jacob", "company", None)

    window, within = timedelta(hours=2), timedelta(hours=48)
    elsewhere = outcomes.outcome(rec, [line("371", 142, 142 * 5.59)], window, within)
    assert not elsewhere["there"] and elsewhere["loves"] and round(elsewhere["saved"]) == 48
    there = outcomes.outcome(rec, [line("412", 142, 142 * 5.25)], window, within)
    assert there["there"] and there["saved"] == 0.0
    assert there["paid"] == 5.25 and there["pump"] == 6 and there["paid_total"] == 142 * 5.25 and there["pump_total"] == 142 * 6
    assert there["discount"] == 0.75 and there["discount_total"] == 142 * 0.75
    assert outcomes.outcome(rec, [], window, within) is None


# A purchase belongs to the newest message before it: the stop told earlier on the way doesn't count it too, and another
# truck's message changes nothing.
def test_outcomes_one_purchase_one_message():
    made = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)
    rec = Recommendation(1, "0226", "Jacob", 1, "L", made, "stop", "412", "Love's Dunn, NC", 109.0, 30.0, 20.0, 17.0, 130.0, None,
                         "hard_stop", 5.25, 5.69, "2026-10-19", 6.69, 5.35, 13.0, "text", "open", None)
    bought = FuelLine(1, "2026-10-19 20:28", "fuel", "ULSD", 142, 142 * 6, 142 * 5.25, 0.0, False, "LOVES #412 TRAVEL STOP",
                      "Dunn", "NC", "TTL", "0226", "company", 7, "Jacob", "company", None)
    window, within = timedelta(hours=2), timedelta(hours=48)
    before = replace(rec, rec_id=2, made_at=made + timedelta(hours=1))
    assert set(outcomes.outcomes([before, rec], [bought], window, within)) == {2}
    after = replace(rec, rec_id=2, made_at=made + timedelta(hours=5))
    assert set(outcomes.outcomes([after, rec], [bought], window, within)) == {1}
    other = replace(rec, rec_id=2, unit="1081", made_at=made + timedelta(hours=1))
    assert set(outcomes.outcomes([other, rec], [bought], window, within)) == {1}
    repeat = replace(before, status="repeat")  # sent again by mistake (14755 at Tolleson): the first message keeps the fill
    assert set(outcomes.outcomes([repeat, rec], [bought], window, within)) == {1}


# The fills no message asked for: the one before the message and the one after the fill it asked for.
def test_own_fills():
    made = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)
    rec = Recommendation(1, "0226", "Jacob", 1, "L", made, "stop", "412", "Love's Dunn, NC", 109.0, 30.0, 20.0, 17.0, 130.0, None,
                         "range", 5.25, 5.69, "2026-10-19", 6.69, 5.35, 13.0, "text", "open", None)

    def line(at: str, store: str) -> FuelLine:
        return FuelLine(1, at, "fuel", "ULSD", 100, 600, 525, 0.0, False, f"LOVES #{store} TRAVEL STOP", "Dunn", "NC", "TTL", "0226",
                        "company", 7, "Jacob", "company", None)

    lines = [line("2026-10-19 10:00", "300"), line("2026-10-19 20:28", "412"), line("2026-10-20 12:00", "500")]
    window = timedelta(hours=2)
    own = outcomes.own_fills("0226", outcomes.outcomes([rec], lines, window, timedelta(hours=48)), lines, window)
    assert [p["where"][:9] for p in own] == ["LOVES #30", "LOVES #50"]
    assert own[0]["gallons"] == 100 and own[0]["pump"] == 6 and own[0]["paid"] == 5.25 and own[0]["discount_total"] == 75


MADE = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)
REC = Recommendation(1, "0226", "Jacob", 1, "L", MADE, "stop", "412", "Love's Dunn, NC", 109.0, 30.0, 20.0, 17.0, 130.0, None,
                     "range", 5.25, 5.69, "2026-10-19", 6.69, 5.35, 13.0, "text", "open", None)


# A Love's diesel line of Jacob's truck at a Central time.
def bought(at: str, store: str) -> FuelLine:
    return FuelLine(1, at, "fuel", "ULSD", 100, 600, 525, 0.0, False, f"LOVES #{store} TRAVEL STOP", "Dunn", "NC", "TTL", "0226",
                    "company", 7, "Jacob", "company", None)


# A truck's last fill is its newest diesel purchase, in UTC (Datatruck's clock is Central); DEF and other trucks don't count.
def test_last_fill():
    def line(when: str, unit: str = "0226", product: str = "ULSD") -> FuelLine:
        return FuelLine(1, when, "fuel", product, 100.0, 600.0, 550.0, 0.0, False, "LOVES #412 TRAVEL STOP", "Dunn", "NC", "TTL",
                        unit, "company", 7, "Jacob", "company", None)

    lines = [line("2026-11-09 08:00"), line("2026-11-10 12:10"), line("2026-11-10 15:00", product="DEFD"), line("2026-11-11 01:00", unit="100")]
    assert outcomes.last_fill("0226", lines) == datetime(2026, 11, 10, 18, 10, tzinfo=timezone.utc)
    assert outcomes.last_fill("9999", lines) is None


# What became of a message: there, at another Love's or outside Love's once bought; else by how it was settled.
def test_became():
    assert outcomes.became(REC, {"there": True}) == "there"
    assert outcomes.became(REC, {"there": False, "loves": True}) == "loves"
    assert outcomes.became(REC, {"there": False, "loves": False}) == "outside"
    assert [outcomes.became(replace(REC, status=s), None) for s in ("passed", "fueled", "open", "replaced", "load ended")] == \
           ["passed", "waiting", "open", "off", "off"]


# A fill gets the gauge of the driver's stop within the window of it; None without one.
def test_with_gauge():
    at = datetime(2026, 10, 20, 1, 28, tzinfo=timezone.utc)
    stop = FuelStop(7, "Jacob", "0226", at + timedelta(minutes=30), 100, 525, True, "NC", 20.0, 95.0)
    fill = {"at": at.isoformat(), "gallons": 100}
    assert outcomes.with_gauge(fill, [stop], timedelta(hours=2)) == fill | {"gauge_before": 20.0, "gauge_after": 95.0}
    assert outcomes.with_gauge(fill, [stop], timedelta(minutes=10))["gauge_before"] is None


# The fills between two moments, each where the GPS was nearest its time, marked when at a stop we told.
def test_fills():
    lines = [bought("2026-10-19 10:00", "300"), bought("2026-10-19 20:28", "412")]  # 15:00 and 01:28 UTC
    track = [TrackPoint(datetime(2026, 10, 19, 15, 5, tzinfo=timezone.utc), 34.0, -79.0),
             TrackPoint(datetime(2026, 10, 20, 1, 20, tzinfo=timezone.utc), 35.0, -78.0)]
    came = {1: {"at": "2026-10-20T01:28:00+00:00", "there": True}}
    start, end, window = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc), datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc), timedelta(hours=2)
    assert outcomes.fills(lines, track, start, end, came, window) == [
        {"at": "2026-10-20T01:28:00+00:00", "lat": 35.0, "lng": -78.0, "gallons": 100, "station": "LOVES #412 TRAVEL STOP",
         "city": "Dunn", "state": "NC", "paid": 5.25, "told": True}]
    assert outcomes.fills(lines, [], start, end, came, window) == []


# What a truck did is shown from its road's start, or from its last message within the window if that came earlier.
def test_watch_from():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    road, told = now - timedelta(hours=3), replace(REC, made_at=now - timedelta(hours=5))
    assert outcomes.watch_from(road, [told], now, timedelta(hours=48)) == told.made_at
    assert outcomes.watch_from(road, [told], now, timedelta(hours=4)) == road                 # the message is too old
    assert outcomes.watch_from(None, [], now, timedelta(hours=48)) == now - timedelta(days=1)
