# Tests live MPG: the engine as a fuel meter, calibrated against the gauge, and the two MPGs the rules use.
from datetime import datetime, timedelta, timezone

from base.models import EngineHistory, FuelReading, Sample
from features.engine import gauge, mpg

T0 = datetime(2026, 10, 19, tzinfo=timezone.utc)


# A truck driving steadily for `hours`: load and RPM every 2 min, 60 mph on the odometer.
def driving(hours: int, load: float = 50, rpm: float = 1400) -> EngineHistory:
    times = [T0 + timedelta(minutes=2 * k) for k in range(hours * 30 + 1)]
    return EngineHistory(load=tuple(Sample(t, load) for t in times), rpm=tuple(Sample(t, rpm) for t in times),
                         miles=tuple(Sample(t, (t - T0).total_seconds() / 60) for t in times))


# The total adds up load x RPM x seconds.
def test_meter_adds_up():
    times, totals = mpg.meter(driving(1))
    assert totals[0] == 0 and round(totals[-1]) == 50 * 1400 * 3600


# With the engine off between readings, nothing is burned in the gap.
def test_engine_off_burns_nothing():
    on = driving(1)
    later = [Sample(s.at + timedelta(hours=5), s.value) for s in on.load]
    rpm = [Sample(s.at + timedelta(hours=5), s.value) for s in on.rpm]
    history = EngineHistory(load=on.load + tuple(later), rpm=on.rpm + tuple(rpm), miles=on.miles)
    assert round(mpg.meter(history)[1][-1]) == 2 * 50 * 1400 * 3600


# Gauge falling 1 point per 10 mi on a 150-gal tank: 1.5 gal per 10 mi. The factor brings the meter to that, and live MPG
# comes out at 6.67.
def test_calibration_and_live_mpg():
    history = driving(30)
    gauge = [FuelReading(T0 + timedelta(minutes=2 * k), 100 - 2 * k / 60 * 60 / 10) for k in range(30 * 30 + 1)]
    m = mpg.meter(history)
    factor, stretches = mpg.gal_per_unit(m, history, gauge, 150, 250, 8, 3)
    assert stretches >= 3
    live = mpg.live_mpg(m, factor, 180, T0 + timedelta(hours=3), T0 + timedelta(hours=6), 25, (4, 12))
    assert round(live, 1) == 6.7


# A fill-up inside a stretch makes it unusable; too few stretches give no factor.
def test_fill_ups_skipped():
    history = driving(12)
    gauge = [FuelReading(T0 + timedelta(minutes=2 * k), 50 + (40 if k % 100 == 50 else 0)) for k in range(12 * 30 + 1)]
    assert mpg.gal_per_unit(mpg.meter(history), history, gauge, 150, 250, 8, 3) is None


# Too few miles say nothing; a wild figure is held inside the range.
def test_live_mpg_limits():
    m = mpg.meter(driving(3))
    assert mpg.live_mpg(m, 1e-6, 10, T0, T0 + timedelta(hours=1), 25, (4, 12)) is None
    assert mpg.live_mpg(m, 1e-12, 100, T0, T0 + timedelta(hours=1), 25, (4, 12)) == 12


# Forecast: halfway between average and live. Cautious: the lower, made worse. Without live: the average.
def test_the_two_mpgs():
    assert mpg.forecast_mpg(7, 8) == 7.5 and mpg.forecast_mpg(7, None) == 7
    assert mpg.cautious_mpg(7, 6, 0.8) == 6 * 0.8 and mpg.cautious_mpg(7, 8, 0.8) == 7 * 0.8 and mpg.cautious_mpg(7, None, 0.8) == 7 * 0.8


# One wobble doesn't move the fuel now; a fill-up shows at once; no readings, no figure.
def test_steady_gauge():
    span, lookback = timedelta(minutes=20), timedelta(minutes=60)
    now = T0 + timedelta(minutes=20)

    def steady(readings: list[FuelReading]) -> float | None:
        return gauge.steady(readings, now, span, lookback, 5, 8)

    def at(*levels: float) -> list[FuelReading]:
        return [FuelReading(T0 + timedelta(minutes=4 * k), v) for k, v in enumerate(levels)]

    assert steady(at(29, 28, 26, 29, 28)) == 28
    assert steady(at(12, 11, 12, 90, 91)) == 90.5
    assert steady([]) is None
    assert steady([FuelReading(T0 - timedelta(hours=1), 50)]) is None


# A stopped truck's few low readings don't count alone: Tre at his pickup, 2026-11-02, read 25.5 from two of them.
def test_steady_gauge_reaches_back_when_readings_are_few():
    now = T0 + timedelta(minutes=60)
    spaced = [(0, 28), (2, 26), (10, 29), (12, 26), (50, 25), (58, 24)]
    readings = [FuelReading(T0 + timedelta(minutes=m), v) for m, v in spaced]
    assert gauge.steady(readings, now, timedelta(minutes=10), timedelta(minutes=60), 5, 8) == 26
