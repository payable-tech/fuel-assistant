# Tests what a truck really did after its plan: the road it drove, its fill-ups placed and matched to planned
# stops, and when it reached the load's last stop.
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from core.trip import trip
from models import FuelLine, TrackPoint

MADE = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)  # plan made at noon UTC (07:00 Central)
LOVES, OTHER, END = (35.0, -99.5), (35.0, -98.5), (35.0, -98.0)


# The truck at a place, `minutes` after the plan was made.
def at(place, minutes: int) -> TrackPoint:
    return TrackPoint(MADE + timedelta(minutes=minutes), *place)


# A diesel purchase at a Central clock time.
def bought(central: str, gallons: float, station: str = "LOVES #1 TRAVEL STOP") -> FuelLine:
    return FuelLine(1, central, "fuel", "ULSD", gallons, gallons * 6, gallons * 5.5, 0.0, True, station, "Town", "OK",
                    "TTL", "340", "company", 7, "", "lease", None)


# Runs the trip with the planned stop at LOVES and the load ending at END.
def run(track, lines):
    return trip(MADE, track, lines, [LOVES], END, 1.0, timedelta(hours=2), 0.2)


# A fill-up where the truck was at the planned Love's counts as that stop; one elsewhere counts as no stop.
def test_fills_placed_and_matched():
    track = [at((35.0, -100.0), 0), at(LOVES, 60), at(OTHER, 180), at((35.0, -98.2), 240)]
    result = run(track, [bought("2026-10-20 08:00", 150), bought("2026-10-20 10:00", 40, "PILOT #9")])
    assert [(f.gallons, f.plan_stop, f.station) for f in result.fills] == [(150, 1, "LOVES #1 TRAVEL STOP"), (40, None, "PILOT #9")]
    assert (result.fills[0].lat, result.fills[0].lng) == LOVES and result.finished_at is None


# Reaching the load's last stop ends the trip: later driving and purchases (the next load) are left out, and so
# are purchases made before the plan.
def test_trip_ends_at_last_stop():
    track = [at(LOVES, 30), at(END, 120), at((36.0, -97.0), 300)]
    result = run(track, [bought("2026-10-20 04:00", 50), bought("2026-10-20 07:30", 100), bought("2026-10-20 11:00", 80)])
    assert result.finished_at == MADE + timedelta(minutes=120)
    assert [f.gallons for f in result.fills] == [100] and result.track[-1] == END


# A fill-up keeps its pump total, its fees and what the driver's card charged them: by the card's policy, the pump
# price plus the fee (a card whose policy isn't known counts so too), the pump price, or the billed amount.
def test_fill_money():
    line = replace(bought("2026-10-20 08:00", 100), fee=2.0, card_id=7)  # $600 at the pump, $550 billed, $2 fee

    def fill(policy):
        return trip(MADE, [at(LOVES, 60)], [line], [LOVES], END, 1.0, timedelta(hours=2), 0.2, {7: policy}).fills[0]

    assert (fill("invoice_amount").pump, fill("invoice_amount").fee, fill("invoice_amount").driver_paid) == (600, 2, 550)
    assert fill("retail_amount").driver_paid == 600 and fill("retail_plus_fee").driver_paid == 602
    assert run([at(LOVES, 60)], [line]).fills[0].driver_paid == 602  # no policy known: pump + fee
    assert trip(MADE, [at(LOVES, 60)], [replace(line, billable=False)], [LOVES], END, 1.0, timedelta(hours=2),
                0.2).fills[0].driver_paid == 0  # a company-paid card: the driver pays nothing


# A purchase where the GPS track has a gap gets no place and no planned stop.
def test_fill_without_track_nearby():
    result = run([at(LOVES, 0)], [bought("2026-10-20 13:00", 60)])
    assert (result.fills[0].lat, result.fills[0].plan_stop) == (None, None)
