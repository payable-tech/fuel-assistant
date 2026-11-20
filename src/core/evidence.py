# Evidence from Samsara for an EFS statement's diesel: per fill, did the gauge rise with the gallons and was the truck at
# the station; per truck, the diesel bought against the fuel its engine used. Thresholds measured on Nov 9-15, 2026.
import re
from datetime import datetime
from statistics import median

from core import fuel, geo
from core.accounting import row_of
from models import EfsLine, FillEvidence, FuelLine, FuelReading, TruckBurn

AT_STATION_MI = 5.0    # a truck this close to its Love's store when filled was at the station: the sheet's store points
                       # are up to ~2 mi off (#980 Avery OH, #969 West Jefferson OH: 1.2 mi for every truck, Nov 2026)
MIN_RISE_PTS = 3       # a gauge rise smaller than this is noise: the gauge didn't move
JUDGED_FROM_GAL = 20   # smaller fills barely move the gauge: they aren't judged on it
MAX_TANK_GAL = 300     # gallons ÷ rise above this: more fuel bought than the gauge saw go in (tanks work out at 127-199)
TANK_FROM_PTS = 25     # rises at least this big size a truck's tank (gallons ÷ rise); smaller ones are too noisy
FILLED_SHARE = 0.9     # a fill is done when the gauge reaches this share of its rise
# A fill's verdicts, in the order they are shown.
PROVEN = "Gauge rose, truck at the station"
SHORT = "Gauge rose less than the gallons"
NO_RISE = "Gauge didn't rise"
ELSEWHERE = "Truck elsewhere at the fill"
NO_GAUGE = "No gauge readings"
NOT_IN_SAMSARA = "Truck not in Samsara"
WAITING = "Not looked up yet"
VERDICTS = (PROVEN, SHORT, NO_RISE, ELSEWHERE, NO_GAUGE, NOT_IN_SAMSARA, WAITING)
DOUBTFUL = (ELSEWHERE, NO_RISE, SHORT)


# The gauge's biggest rise between two times, as (bottom %, top %, when it was filled); None with under two readings.
# The gauge reads only while the engine runs, so the last reading before `start` counts too: the level the truck was
# parked at. "Filled" is the first reading at 90% of the rise: the gauge creeps up a little more as the truck drives off.
def biggest_rise(readings: list[FuelReading], start: datetime, end: datetime) -> tuple[float, float, datetime] | None:
    ordered = sorted(readings, key=lambda r: r.at)
    inside = [r for r in ordered if r.at < start][-1:] + [r for r in ordered if start <= r.at <= end]
    if len(inside) < 2:
        return None
    low, best = inside[0], None  # best: (bottom reading, top reading)
    for r in inside[1:]:
        if best is None or r.pct - low.pct > best[1].pct - best[0].pct:
            best = (low, r)
        low = min(low, r, key=lambda x: x.pct)  # the lowest reading so far: a rise is measured from it
    bottom, top = best
    near_top = bottom.pct + FILLED_SHARE * (top.pct - bottom.pct)
    filled = next((r for r in inside if bottom.at < r.at <= top.at and r.pct >= near_top), top)  # top: a gauge that fell
    return bottom.pct, top.pct, filled.at


# Every diesel fill on the statement with its verdict, the count per verdict, the doubtful fills (biggest first), and how
# many fills had a unit keyed at the pump other than the Datatruck truck. `evidence` is {Datatruck line id: what Samsara
# showed}, `linked` the units in Samsara, `stores` {Love's store no: (lat, lng)}.
def fills(lines: list[EfsLine], found: dict[int, FuelLine], evidence: dict[int, FillEvidence], linked: set[str],
          stores: dict[str, tuple[float, float]]) -> dict:
    diesel = [(l, found[l.seq]) for l in lines if l.seq in found and row_of(l) == "DIESEL TOTAL"]
    judged = [_fill(l, twin, evidence.get(twin.line_id), twin.unit in linked, stores) for l, twin in diesel]
    groups = [{"verdict": v, "fills": sum(1 for f in judged if f["verdict"] == v),
               "gallons": round(sum(f["gallons"] for f in judged if f["verdict"] == v), 1)} for v in VERDICTS]
    doubtful = sorted((f for f in judged if f["verdict"] in DOUBTFUL), key=lambda f: -f["gallons"])
    keyed_off = sum(1 for l, twin in diesel if _unit(l.unit) and _unit(twin.unit) and _unit(l.unit) != _unit(twin.unit))
    return {"groups": groups, "doubtful": doubtful, "unit_differs": keyed_off, "fills": len(judged)}


# One fill: where and who, its gallons, the gauge's rise around it, the tank that rise implies, where the truck was, and
# its verdict.
def _fill(line: EfsLine, twin: FuelLine, ev: FillEvidence | None, linked: bool, stores: dict[str, tuple[float, float]]) -> dict:
    seen = {"day": line.day, "station": twin.location, "efs_place": f"{line.city}, {line.state}", "unit": twin.unit,
            "keyed": line.unit, "driver": twin.driver_name, "gallons": round(line.quantity, 1)}
    if not linked:
        return seen | {"verdict": NOT_IN_SAMSARA}
    if ev is None:
        return seen | {"verdict": WAITING}
    rise = None if ev.gauge_from is None else ev.gauge_to - ev.gauge_from
    risen = rise is not None and rise >= MIN_RISE_PTS
    tank = line.quantity / (rise / 100) if risen else None
    there, miles_off = _there(line, twin, ev, stores) if risen else (None, None)  # without a rise, no moment to place it
    seen |= {"gauge_from": ev.gauge_from, "gauge_to": ev.gauge_to, "tank": None if tank is None else round(tank),
             "truck_place": ev.place, "miles_off": miles_off}
    return seen | {"verdict": _verdict(line.quantity, rise, tank, there)}


# The verdict from the gauge's rise, the tank it implies and whether the truck was at the station (worst first).
def _verdict(gallons: float, rise: float | None, tank: float | None, there: bool | None) -> str:
    if there is False:
        return ELSEWHERE
    if rise is None:
        return NO_GAUGE
    if gallons >= JUDGED_FROM_GAL and rise < MIN_RISE_PTS:
        return NO_RISE
    if tank is not None and tank > MAX_TANK_GAL:
        return SHORT
    return PROVEN


# Whether the truck was at the station when the gauge topped out, and how many miles off: from the store for a Love's
# (within AT_STATION_MI); for any other station, by the state in Samsara's address against the statement's (the city
# isn't compared: a truck stop's address and EFS's merchant city often differ; no miles then). (None, None): not known.
def _there(line: EfsLine, twin: FuelLine, ev: FillEvidence, stores: dict[str, tuple[float, float]]) -> tuple[bool | None, float | None]:
    store = stores.get(fuel.store_no(twin.location) or "") if fuel.is_loves(twin) else None
    if store and ev.lat is not None:
        off = geo.miles((ev.lat, ev.lng), store)
        return off <= AT_STATION_MI, round(off, 1)
    state = _state(ev.place)
    if state is None or not line.state:
        return None, None
    return state == line.state, None


# The state in Samsara's address, "Street, City, ST, ZIP" -> "ST"; None when there is none.
def _state(place: str | None) -> str | None:
    parts = [p.strip() for p in (place or "").split(",")]
    return next((p for p in reversed(parts) if re.fullmatch(r"[A-Z]{2}", p)), None)


# A unit number as digits only, without leading zeros, so "0226", "226" and "226." compare equal.
def _unit(text: str | None) -> str:
    return re.sub(r"\D", "", text or "").lstrip("0")


# Per truck on the statement: diesel bought, the fuel its engine used and the miles it drove over the statement's days,
# its gauge at the start and end, its tank (gallons ÷ rise of its own fills) and the gallons that leaves unexplained:
# bought minus burned minus what went into the tank. Biggest unexplained first. `burns` is {Samsara id: TruckBurn},
# empty until looked up; `samsara_ids` is {unit: Samsara id}.
def bought_vs_burned(lines: list[EfsLine], found: dict[int, FuelLine], burns: dict[str, TruckBurn], samsara_ids: dict[str, str],
                     evidence: dict[int, FillEvidence]) -> dict:
    by_unit: dict[str, list[tuple[EfsLine, FuelLine]]] = {}
    for l in lines:
        if l.seq in found and row_of(l) == "DIESEL TOTAL" and found[l.seq].unit:
            by_unit.setdefault(found[l.seq].unit, []).append((l, found[l.seq]))
    rows = [_truck(unit, mine, burns.get(samsara_ids.get(unit, "")), evidence) for unit, mine in by_unit.items()]
    rows.sort(key=lambda r: (r["unexplained"] is None, -(r["unexplained"] or 0), -r["bought"]))
    return {"looked_up": bool(burns), "trucks": rows}


# One truck's row of bought vs burned.
def _truck(unit: str, fills: list[tuple[EfsLine, FuelLine]], burn: TruckBurn | None, evidence: dict[int, FillEvidence]) -> dict:
    bought = sum(l.quantity for l, _ in fills)
    tank = _tank(fills, evidence)
    row = {"unit": unit, "drivers": sorted({twin.driver_name for _, twin in fills if twin.driver_name}), "fills": len(fills),
           "bought": round(bought, 1), "burned": None, "miles": None, "gauge_start": None, "gauge_end": None,
           "tank": None if tank is None else round(tank), "into_tank": None, "unexplained": None}
    if burn is None:
        return row
    row |= {"burned": round(burn.burned_gal, 1), "miles": round(burn.miles), "gauge_start": burn.gauge_start,
            "gauge_end": burn.gauge_end}
    if tank is not None and burn.gauge_start is not None and burn.gauge_end is not None:
        into_tank = (burn.gauge_end - burn.gauge_start) / 100 * tank
        row |= {"into_tank": round(into_tank, 1), "unexplained": round(bought - burn.burned_gal - into_tank, 1)}
    return row


# A truck's tank in gallons: the middle of gallons ÷ gauge rise over its fills with a big enough rise; None without one.
def _tank(fills: list[tuple[EfsLine, FuelLine]], evidence: dict[int, FillEvidence]) -> float | None:
    sizes = []
    for line, twin in fills:
        ev = evidence.get(twin.line_id)
        if ev and ev.gauge_from is not None and ev.gauge_to - ev.gauge_from >= TANK_FROM_PTS:
            sizes.append(line.quantity / ((ev.gauge_to - ev.gauge_from) / 100))
    return median(sizes) if sizes else None
