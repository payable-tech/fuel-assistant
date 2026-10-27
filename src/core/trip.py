# What a truck really did after its plan was made (pure): the road it drove, where it bought diesel, and when it
# reached the load's last stop. Fuel lines carry no position, so each purchase is placed where the truck's GPS was
# when it paid, and counts as made at a planned stop when that place is within `reached_mi` of it.
from datetime import datetime, timedelta

from core import geo
from core.fuel import driver_paid, purchase_stops, utc
from models import Fill, FuelLine, TrackPoint, Trip


# The trip from `made_at` until the truck reaches `end` (the load's last stop) or until now when it hasn't yet. With
# no `end`, until now: the caller decides when the load ended (core/follow does, in road order). `policies` maps a
# card id to its deduction policy, for what each fill-up cost the driver.
def trip(made_at: datetime, track: list[TrackPoint], lines: list[FuelLine], plan_stops: list[geo.Point],
         end: geo.Point | None, reached_mi: float, window: timedelta, thin_mi: float,
         policies: dict[int, str | None] | None = None) -> Trip:
    after = [p for p in track if p.at >= made_at]
    finished_at = next((p.at for p in after if end and geo.miles((p.lat, p.lng), end) <= reached_mi), None)
    driven = [p for p in after if finished_at is None or p.at <= finished_at]
    stops = [s for s in purchase_stops(lines, window)
             if made_at <= utc(s[-1].fueled_at) and (finished_at is None or utc(s[0].fueled_at) <= finished_at)]
    return Trip(track=tuple(geo.thin([(p.lat, p.lng) for p in driven], thin_mi)),
                fills=tuple(_fill(s, driven, plan_stops, reached_mi, window, policies or {}) for s in stops),
                finished_at=finished_at)


# One stop's purchases as a fill-up, placed at the truck's GPS point nearest in time (none when the nearest is more
# than `window` away) and numbered by the planned stop it was made at.
def _fill(lines: list[FuelLine], driven: list[TrackPoint], plan_stops: list[geo.Point], reached_mi: float,
          window: timedelta, policies: dict[int, str | None]) -> Fill:
    at = utc(lines[-1].fueled_at)
    nearest = min(driven, key=lambda p: abs(p.at - at), default=None)
    where = (nearest.lat, nearest.lng) if nearest and abs(nearest.at - at) <= window else None
    stop = next((n for n, s in enumerate(plan_stops, start=1) if where and geo.miles(where, s) <= reached_mi), None)
    return Fill(at=at, lat=where[0] if where else None, lng=where[1] if where else None,
                gallons=sum(l.gallons for l in lines),
                billed=sum(l.billed for l in lines), station=lines[0].location, city=lines[0].city,
                state=lines[0].state, plan_stop=stop, first_at=utc(lines[0].fueled_at),
                pump=sum(l.pump_total for l in lines), fee=sum(l.fee for l in lines),
                driver_paid=sum(driver_paid(l, policies.get(l.card_id)) for l in lines))
