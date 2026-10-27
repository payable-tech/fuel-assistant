# Plain data objects passed between layers: no logic, no I/O.
from dataclasses import dataclass
from datetime import datetime


# A vehicle in Samsara. A row of `samsara_vehicles`.
@dataclass(frozen=True)
class SamsaraVehicle:
    samsara_id: str
    name: str
    vin: str                        # trimmed, upper-case; "" when Samsara has none
    mpg: float | None               # 30-day average as Samsara reports it; None when there is no data
    last_gps_at: datetime | None    # last GPS point: tells active trucks from parked or retired ones


# A vehicle's latest GPS point and fuel gauge reading in Samsara. A row of `samsara_live`.
@dataclass(frozen=True)
class SamsaraLive:
    samsara_id: str
    lat: float | None
    lng: float | None
    place: str | None               # Samsara's address for the point, e.g. "Toano, VA, 23163"
    gps_at: datetime | None
    fuel_pct: float | None          # fuel gauge, 0-100
    fuel_at: datetime | None        # time of the gauge reading; some gauges stopped reporting long ago


# One point of a vehicle's GPS track, from Samsara's history.
@dataclass(frozen=True)
class TrackPoint:
    at: datetime
    lat: float
    lng: float


# One reading of a vehicle's fuel gauge, from Samsara's history.
@dataclass(frozen=True)
class FuelReading:
    at: datetime
    pct: float


# The tank helper's estimate for one truck. A row of `tank_estimates`.
@dataclass(frozen=True)
class TankEstimate:
    unit: str
    tank_gal: float                 # gallons from an empty to a full gauge
    fills: int                      # fill-ups the estimate is based on


# A truck in Datatruck. A row of `dt_trucks`.
@dataclass(frozen=True)
class DatatruckTruck:
    dt_id: int
    unit: str                       # unit number exactly as typed in Datatruck, e.g. "0140"
    vin: str                        # trimmed, upper-case
    status: str                     # e.g. "available", "in_transit"
    ownership: str | None           # "company", "rental", "lease", "owner_operator", ...


# A driver in Datatruck, active or not. A row of `dt_drivers`.
@dataclass(frozen=True)
class DatatruckDriver:
    driver_id: int
    full_name: str
    driver_type: str | None         # "lease", "company_driver", "company_owner", "other"
    employee_status: str | None     # "active", "inactive", "applicant"
    company: str                    # MC company name
    unit: str | None                # assigned truck's unit number


# One fuel-card purchase line from Datatruck (diesel, DEF, scale...). A row of `fuel_lines`.
@dataclass(frozen=True)
class FuelLine:
    line_id: int
    fueled_at: str                  # local Central time "YYYY-MM-DD HH:MM" (Datatruck writes it as if UTC)
    transaction_type: str           # "fuel", "scale", "cash_advance"
    product: str                    # "ULSD" = diesel, "DEFD" = DEF, ...
    gallons: float
    pump_total: float               # what the gallons cost at the posted pump price ("total")
    billed: float                   # what EFS billed the company after discounts ("amount")
    fee: float
    billable: bool                  # goes on the driver's fuel balance
    location: str                   # station name, e.g. "LOVES #220 TRAVEL STOP"
    city: str
    state: str
    company: str                    # MC company name
    unit: str | None
    truck_ownership: str | None
    driver_id: int | None
    driver_name: str | None
    driver_type: str | None
    card_id: int | None             # Datatruck's card id; the card number itself is never stored


# A fuel card in Datatruck. A row of `fuel_cards`; the card number itself is never stored.
@dataclass(frozen=True)
class FuelCard:
    card_id: int
    company: str
    assigned_to: str | None         # "driver" or "truck"
    driver_id: int | None
    unit: str | None
    billable: bool                  # purchases go on the driver's balance
    deduction_policy: str | None    # "retail_plus_fee", "retail_amount", "invoice_amount"
    active: bool


# A group Bob's Telegram account is in. A row of `tg_groups`.
@dataclass(frozen=True)
class TelegramGroup:
    chat_id: int
    title: str


# One stop of a Datatruck order. A row of `dt_stops`.
@dataclass(frozen=True)
class Stop:
    stop_id: int
    order_id: int
    seq: int                        # position in the route, 1 = first
    kind: str                       # "pickup" or "delivery"
    lat: float | None
    lng: float | None
    city: str
    state: str


# An active Datatruck order with its stops in route order. A row of `dt_orders` plus its `dt_stops`.
@dataclass(frozen=True)
class Order:
    order_id: int
    load_id: str
    status: str                     # "assigned", "dispatched" or "in_transit"
    unit: str | None                # truck on the order's trip; None when no truck is assigned
    pickup_at: datetime | None      # pickup appointment
    stops: tuple[Stop, ...]


# A Love's store with its latest prices. A row of `stores`.
@dataclass(frozen=True)
class Store:
    store_no: str
    city: str
    state: str
    lat: float
    lng: float
    retail: float
    net: float                      # "Best Discounted Price": what we actually pay
    price_date: str                 # "YYYY-MM-DD", from the sheet
    name: str = ""                  # a station that isn't a Love's (Google Places id as store_no): its name, e.g.
                                    # "Cenex Zip Trip"; its price is the pump price, or none known when price_date is ""


# A Love's store next to a route: how far along the route it is, and how far off it.
@dataclass(frozen=True)
class StoreOnRoute:
    store: Store
    miles: float                    # miles from the route's start to the route point nearest the store
    off_mi: float                   # straight-line miles from that point to the store


# The planner's rules, taken from config.
@dataclass(frozen=True)
class PlanRules:
    reserve_pct: float              # never plan the tank below this
    min_buy_gal: float              # a stop buys at least this much
    stop_cost: float                # dollars one more stop costs
    step_gal: float                 # fill-up amounts are planned in these steps
    default_mpg: float              # used when the truck's MPG is missing or odd
    mpg_range: tuple[float, float]  # MPG outside this is treated as odd
    end_min_gal: float = 0.0        # aim to reach the last stop with at least this (else at least the reserve)
    detour_factor: float = 0.0      # road miles to a store and back per straight-line mile off the route; 0: not counted
    switch_cost: float = 0.0        # on a re-plan, dollars a Love's costs more when the driver wasn't told about it


# One planned fuel stop.
@dataclass(frozen=True)
class PlanStop:
    store: Store
    miles: float                    # miles from the start of the route
    arrive_gal: float               # fuel in the tank when the truck gets there
    gallons: float                  # gallons to buy
    cost: float                     # gallons × the store's discounted price


# A point a planned load drives through: one of its planned fuel stops, pickups or deliveries.
@dataclass(frozen=True)
class Waypoint:
    kind: str                       # "fuel", "pickup" or "delivery"
    label: str                      # "Love's #614 Westfield, MA" or "Ayer, MA"
    lat: float
    lng: float
    miles: float                    # miles from the plan's start along its road


# Where to buy fuel on one trip and what it costs. No stops means the fuel on board is enough.
@dataclass(frozen=True)
class FuelPlan:
    stops: tuple[PlanStop, ...]
    end_gal: float                  # fuel left when the truck reaches the last stop of its load
    fuel_cost: float                # dollars for the gallons bought


# The average retail diesel price of one region in one week, from the U.S. EIA. A row of `market_prices`.
@dataclass(frozen=True)
class MarketPrice:
    day: str                        # "YYYY-MM-DD", the Monday the price was taken
    region: str                     # an EIA region such as "Midwest" or "California"; "U.S." for the whole country
    price: float                    # dollars per gallon at the pump, taxes included


# The result of matching one unit to a Telegram group: a chat, or a note saying why there is none.
@dataclass(frozen=True)
class ChatMatch:
    chat_id: int | None
    note: str | None


# One linked truck as built by sync from the source copies. A row of `trucks`.
@dataclass(frozen=True)
class SyncedTruck:
    unit: str                       # Datatruck unit number, the one truck key everywhere
    samsara_id: str
    vin: str
    name: str                       # Samsara display name, for humans
    mpg: float | None
    auto_chat_id: int | None        # Telegram group found by the unit number and driver name in its title
    chat_note: str | None           # why there is no auto chat; or, with one, that only its title names the driver


# One truck with everything known about it: synced, live, helper and your values, yours winning. A row of `fleet`.
@dataclass(frozen=True)
class Truck:
    unit: str
    samsara_id: str
    vin: str
    name: str
    driver: str | None              # active Datatruck driver(s) of this unit, "A & B" for a team
    mpg: float | None
    fuel_pct: float | None          # latest Samsara gauge reading
    fuel_at: datetime | None
    lat: float | None
    lng: float | None
    place: str | None               # address of the latest GPS point
    gps_at: datetime | None
    tank_gal: float | None          # yours if set, else the tank helper's estimate
    tank_source: str | None         # "manual", "auto", or None when there is neither
    tank_fills: int | None          # fill-ups behind the helper's estimate
    chat_id: int | None             # yours if set, else the auto-matched group
    chat_source: str | None         # "manual", "auto", or None when the truck has no group
    chat_note: str | None           # why auto-match found nothing
    pilot: bool                     # one of the trucks you picked for the pilot


# One diesel stop of a driver (purchases at one place grouped), with the truck's gauge around it. A row of `fuel_stops`.
@dataclass(frozen=True)
class FuelStop:
    driver_id: int
    driver_name: str
    unit: str | None
    at: datetime                    # last purchase of the stop (UTC)
    gallons: float
    billed: float                   # what EFS billed the company
    loves: bool                     # bought at a Love's
    state: str
    gauge_before: float | None      # Samsara gauge just before, %; None when the truck has no readings then
    gauge_after: float | None       # Samsara gauge just after, %


# How one driver usually fuels, worked out from their recent stops.
@dataclass(frozen=True)
class DriverHabit:
    driver_id: int
    name: str
    unit: str | None                # truck of their latest stop
    stops: int
    gallons: float
    gauged: int                     # stops with gauge readings before and after
    stop_at_pct: float | None       # middle gauge level when they stop (None without gauge readings)
    ran_low_share: float | None     # share of gauged stops that began below the low mark (10%)
    fill_to_pct: float | None       # middle gauge level after filling
    gal_per_stop: float             # middle gallons per stop
    top_off_share: float            # share of stops buying less than a top-off (50 gal)
    loves_share: float              # share of gallons bought at Love's
    paid_per_gal: float             # what was billed per gallon, all their diesel
    outside_premium: float | None   # $/gal more paid outside Love's than at Love's; None when they only used one


# One way of fueling a trip in figures that compare: the plan, the driver's habit, or what really happened.
@dataclass(frozen=True)
class Outcome:
    stops: int
    gallons: float                  # bought
    bought: float                   # dollars bought: what the company is billed, after Love's discount
    end_gal: float | None           # fuel left at the end of the trip; None while it isn't over
    pump: float = 0.0               # the same gallons at the pump price
    driver_paid: float | None = None  # what the drivers' cards charged them (real purchases only)


# One fill-up the truck really made after its plan. Fuel lines carry no position, so it is placed where the
# truck's GPS was when it paid (None when the track has a gap there).
@dataclass(frozen=True)
class Fill:
    at: datetime                    # time of the last purchase at this stop (UTC)
    lat: float | None
    lng: float | None
    gallons: float
    billed: float                   # what EFS billed the company
    station: str                    # e.g. "LOVES #614 TRAVEL STOP"
    city: str
    state: str
    plan_stop: int | None           # number of the planned stop it was made at (1, 2, ...); None when elsewhere
    first_at: datetime | None = None  # time of the first purchase at this stop (lines minutes apart are one stop)
    pump: float = 0.0               # the gallons at the pump price
    fee: float = 0.0                # card fees
    driver_paid: float = 0.0        # what the driver's card charged them (core/fuel.driver_paid)


# What the truck really did after its plan was made, up to the load's last stop (or now).
@dataclass(frozen=True)
class Trip:
    track: tuple[tuple[float, float], ...]  # the road it drove, (lat, lng) points
    fills: tuple[Fill, ...]
    finished_at: datetime | None    # when it reached the load's last stop; None while it hasn't


# Everything about one planned load, kept so the plan can be redrawn exactly as it was made: the truck as it was,
# its load, the road, the Love's along it, and the plan (None when no plan keeps the reserve).
@dataclass(frozen=True)
class LoadPlan:
    made_at: datetime
    truck: Truck
    order: Order
    stops_ahead: tuple[Stop, ...]   # the load's stops the truck still had to drive to
    line: tuple[tuple[float, float], ...]  # the road from the truck through those stops, (lat, lng) points
    route_mi: float
    candidates: tuple[StoreOnRoute, ...]   # the Love's along the road it could choose from
    mpg: float                      # the MPG the plan used
    price_date: str                 # date of the Love's price sheet
    end_price: float                # what a gallon left at the end is worth: the Love's price nearest the destination
    plan: FuelPlan | None
    end_pump: float | None = None   # that Love's pump price (plans before 2026-10-22 lack it)
    via: tuple[tuple[float, float], ...] = ()  # (lat, lng) the road goes through: the driver's own route, where it
                                    # isn't Google's (e.g. I-84 through Ontario, OR); re-plans keep those still ahead


# One thing that happened on a followed plan, as its messages tell it.
@dataclass(frozen=True)
class Event:
    kind: str                       # "pickup", "delivery", "bought", "missed", "dropped" or "replanned"
    label: str                      # the place: "Fort Worth, TX", "Love's #227 Sweetwater, TX", "Pilot #452 Abilene, TX"
    at: datetime
    stop_no: int | None = None      # the planned stop's number ("bought" there, "missed", "dropped"); None elsewhere
    gallons: float | None = None    # "bought": the gallons, what EFS billed, and the same at the pump price
    billed: float | None = None
    pump: float | None = None


# How far a sent plan has got: the road in force (the plan, or its latest re-plan from where the truck was), how many
# of that road's waypoints the truck has passed, every Love's planned for the load so far (planned stop n is
# planned[n - 1]), and everything told so far, in order.
@dataclass(frozen=True)
class Progress:
    road: LoadPlan
    passed: int
    planned: tuple[Waypoint, ...]
    events: tuple[Event, ...]
