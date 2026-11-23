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


# One EFS weekly statement for one EFS account: page 1's figures. A row of `efs_statements`.
@dataclass(frozen=True)
class EfsStatement:
    statement_no: str
    account: str                    # the EFS customer, e.g. "ALIF UZ CORP" (its cards may belong to several companies)
    statement_day: str              # "YYYY-MM-DD", the statement date: the last day it covers
    charges: float                  # Current Charges: everything the account's cards cost in the period
    summary: tuple[tuple[str, float], ...]  # page 1's Transaction Summary as (EFS's name, dollars); adds up to charges


# One line of an EFS statement: a card purchase, a money code, a credit or an account fee. A row of `efs_lines`.
@dataclass(frozen=True)
class EfsLine:
    statement_no: str
    seq: int                        # its place on the statement
    tn: str                         # EFS transaction number, shared by the items bought in one swipe
    day: str                        # "YYYY-MM-DD"
    unit: str                       # unit or truck number keyed at the pump; "" when none
    city: str
    state: str
    description: str                # first line of EFS's text: "ULTRA LOW", "DIESEL EXHAUST", "MONEY CODE", ...
    quantity: float                 # gallons for fuel; 1 for a money code or a scale
    amount: float                   # what EFS charged for it; below zero for a credit
    fee: float                      # EFS's transaction fee on it


# What Samsara shows around one diesel fill (a Datatruck line): the gauge's biggest rise near it and where the truck
# was when the rise ended. A row of `fill_evidence`, looked up once and kept.
@dataclass(frozen=True)
class FillEvidence:
    line_id: int
    gauge_from: float | None        # the gauge (%) at the bottom of its biggest rise near the fill; None: no readings
    gauge_to: float | None          # and at its top
    risen_at: datetime | None       # when it reached the top: the real end of the fill (Datatruck's time can be hours late)
    lat: float | None               # where the truck was then (at Datatruck's time when the gauge didn't rise)
    lng: float | None
    place: str | None               # Samsara's address there, "Street, City, ST, ZIP"


# One Samsara vehicle over one statement's days: the fuel its engine used, the miles it drove, and its gauge (%) when
# the days began and ended. A row of `statement_burn`, looked up once per statement and kept.
@dataclass(frozen=True)
class TruckBurn:
    statement_no: str
    samsara_id: str
    burned_gal: float
    miles: float
    gauge_start: float | None       # None: no reading in the days before (a parked or dead gauge)
    gauge_end: float | None


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
    place: str | None = None        # Samsara's address for the point, "Street, City, ST, ZIP", when it was asked for


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


# A fuel card as eManager's Card Lookup lists it (features/cards/efs_cards). Last four digits are not unique: pick by card_id.
@dataclass(frozen=True)
class EfsCardRow:
    card_id: str                    # eManager's own id for the card
    number: str                     # as eManager shows it, masked: "556748******0806"
    policy: str
    unit: str
    driver_id: str
    driver_name: str
    xref: str
    status: str                     # "ACTIVE", "INACTIVE", "HOLD"


# A fuel card's own page in eManager: its settings, whether it is in override mode, and its prompts.
@dataclass(frozen=True)
class EfsCard:
    card_id: str
    status: str                     # "ACTIVE", "INACTIVE", "HOLD"
    hand_enter: str                 # "ALLOW", "DISALLOW", "POLICY"
    info_source: str                # where its prompts come from: "CARD", "POLICY", "BOTH"
    mobile: str                     # mobile transactions: "ALLOW", "DISALLOW", "POLICY"
    policy: str
    xref: str
    expires: str                    # as the page prints it: "Oct 1, 2029"
    last_used: str                  # as the page prints it; "" when never used
    override: bool                  # in override mode: locked until the override is removed
    prompts: tuple[tuple[str, str, str], ...]  # (prompt, validation, value): ("Unit Number", "Exact Match", "3189")


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
    way: str | None = None          # a Love's highway and exit as its own page says them, "I-70 (Exit 208)"; None when
                                    # not read yet or the page names none. Kept in `store_exits`


# A Love's store next to a route: how far along the route it is, and how far off it.
@dataclass(frozen=True)
class StoreOnRoute:
    store: Store
    miles: float                    # miles from the route's start to the route point nearest the store
    off_mi: float                   # straight-line miles from that point to the store


US = "U.S."  # the region of a MarketPrice for the whole country


# The average retail diesel price of one region in one week, from the U.S. EIA. A row of `market_prices`.
@dataclass(frozen=True)
class MarketPrice:
    day: str                        # "YYYY-MM-DD", the Monday the price was taken
    region: str                     # an EIA region such as "Midwest" or "California"; US for the whole country
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


# One Datatruck truck with what the fleet status is told from: who drives it, its Samsara link and newest readings,
# its fuel card and its newest purchase. A row of db.fleet_status; unlike `fleet`, trucks with no Samsara link are in.
@dataclass(frozen=True)
class FleetTruck:
    unit: str
    status: str                     # Datatruck's: "in_transit", "available", "shop", "yard"
    driver: str | None              # active Datatruck driver(s) of this unit, "A & B" for a team; None when nobody is
    driver_type: str | None         # the first driver's Datatruck type: "lease", "company_driver", "company_owner", "other"
    samsara_name: str | None        # the Samsara vehicle linked by VIN; None when no Samsara vehicle has this VIN
    gps_at: datetime | None         # latest Samsara GPS point
    fuel_pct: float | None          # latest Samsara gauge reading
    fuel_at: datetime | None
    has_card: bool                  # an active fuel card on a driver active on this truck, or on the truck itself
    fueled_at: str | None           # newest fuel purchase, local Central time "YYYY-MM-DD HH:MM"


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


# What Samsara showed around one diesel fill outside Love's: where the truck was and the gauge before.
@dataclass(frozen=True)
class FillLookup:
    line_id: int
    lat: float | None               # the truck's Samsara GPS at the fill; None when Samsara had no position then (and in
    lng: float | None               # older rows of Love's fills: those are placed at their store)
    gauge_before: float | None      # Samsara gauge just before, %; None when the truck had no readings then


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


# One reading of an engine signal or the odometer, from Samsara's history.
@dataclass(frozen=True)
class Sample:
    at: datetime
    value: float


# A vehicle's engine load %, RPM and odometer miles over a time, each oldest first.
@dataclass(frozen=True)
class EngineHistory:
    load: tuple[Sample, ...]
    rpm: tuple[Sample, ...]
    miles: tuple[Sample, ...]


# How many gallons one unit of a truck's engine meter burns (features/engine/burn). A row of `burn_factors`.
@dataclass(frozen=True)
class BurnFactor:
    unit: str
    gal_per_unit: float
    stretches: int                  # stretches of road it is based on


# Where a driver usually fuels: gauge levels, from their past stops.
@dataclass(frozen=True)
class UsualLevel:
    usual_pct: float                # middle level when stopping
    low_pct: float                  # the middle half of their stops lies between these two
    high_pct: float
    fill_pct: float                 # middle level after filling
    stops: int


# The recommendation's rules, taken from config.
@dataclass(frozen=True)
class FuelRules:
    reserve_pct: float              # never plan to arrive under this, at the cautious MPG
    worse: float                    # the cautious MPG is the lower of average and live, times this
    above_usual: float              # a stop reached more than this many points above the usual level is too early
    look_mi: float                  # the driver is told when the stop is this close
    part_gap: float                 # a Love's ahead this much cheaper ($/gal, and cheaper at the pump) is marked on the regions
    part_reach_mi: float            # ...when it is at most this far past the stop
    part_min_gal: float             # at a truck stop before a Love's: buy at least this
    part_margin_gal: float          # ...and at least this less than a fill-up, or it isn't worth asking
    low_penalty: float              # dollars a stop loses per point it is reached below the driver's range
    urgent_pct: float               # with no Love's in reach, the backup starts at this gauge level
    hold_min: float                 # no fuel stop is told this many minutes after a fill was seen (it may still be going on)
    near_mi: float                  # ...nor one closer than this: the driver is already there
    max_passed: int                 # ...nor after this many stops told and driven past on one tank
    last_pct: float                 # a Love's reached with less than this, at the cautious MPG, is out of reach: what the
                                    # gauge's own error can hide. Between this and the reserve: not planned on, no emergency


# A truck as the rules see it now.
@dataclass(frozen=True)
class TruckNow:
    fuel_gal: float
    mile: float                     # how far along its road
    tank_gal: float
    forecast_mpg: float
    cautious_mpg: float
    usual: UsualLevel


# A stretch of the road ahead where the truck will need fuel.
@dataclass(frozen=True)
class Region:
    from_mi: float
    to_mi: float
    stops: int                      # Love's in it
    cheapest: str
    cheaper_ahead: bool             # a Love's past it is much cheaper: a part fill may come up here
    fill_mi: float = 0.0            # where in it the forecast assumes the fill-up
    fill_pct: float | None = None   # ...and the gauge after it; None: the driver's fill level


# What the rules say now. kind: "enough", "watch", "stop" or "urgent" (features/engine/recommend.decide).
@dataclass(frozen=True)
class Decision:
    kind: str
    stop: StoreOnRoute | None = None
    arrive_pct: float | None = None
    worst_pct: float | None = None
    gallons: float | None = None    # to buy there
    then: StoreOnRoute | None = None  # a part fill: where to fill up after it
    reason: str | None = None       # "range", "hard_stop", "tight" (under the reserve, Love's left), "last" (the last one in
                                    # reach: skipping it means low fuel), "detour" (none on the road in reach, one off it is)
                                    # or "low" (none in reach)


NO_LOAD_ORDER = 0  # the order id a message to a truck with no load is kept under (Datatruck's ids start at 1)


# One thing the driver would have been told, and what became of it. A row of `recommendations`.
@dataclass(frozen=True)
class Recommendation:
    rec_id: int | None
    unit: str
    driver: str | None
    order_id: int
    load_id: str
    made_at: datetime
    kind: str
    store_no: str | None
    station: str | None
    miles_ahead: float | None
    gauge_pct: float
    arrive_pct: float | None
    worst_pct: float | None
    gallons: float | None
    then_station: str | None
    reason: str | None
    net: float | None
    retail: float | None
    price_date: str | None
    forecast_mpg: float
    cautious_mpg: float
    usual_pct: float
    text: str
    status: str                     # "open", "fueled", "passed", "replaced", "load ended", or "repeat": sent again by
                                    # mistake (an engine bug, set by hand), counted nowhere
    settled_at: datetime | None
    sent_at: datetime | None = None # when it went to the driver's own group; None: the test group only
    lat: float | None = None        # where the stop is: an urgent message's truck stop is found on the road by it
    lng: float | None = None


# One load of a pilot truck as the engine saw it, kept after the load ends so past trips can be walked through on the
# Recommend tab. A row of `trips`.
@dataclass(frozen=True)
class Trip:
    unit: str
    order_id: int
    load_id: str | None
    stops: tuple                    # the load's stops: (kind, city, state, lat, lng)
    started_at: datetime            # the engine's first look at this load
    ended_at: datetime              # its last look at it
    line: tuple | list | None = None  # the latest road planned (points MAP_STEP_MI apart); None when none was kept


# One pilot truck's latest look: its state, its road and where it is on it. A row of `truck_watch`.
@dataclass(frozen=True)
class TruckWatch:
    unit: str
    at: datetime
    state: str                      # "enough", "watch", "stop", "urgent", "told", or why it can't be looked at
    order_id: int | None = None
    load_id: str | None = None
    road_made_at: datetime | None = None
    line: tuple | list | None = None
    route_mi: float | None = None
    mile: float | None = None
    fuel_pct: float | None = None
    forecast_mpg: float | None = None
    cautious_mpg: float | None = None
    live_mpg: float | None = None
    live_used: bool = False         # False while it ran empty, or without a figure
    usual_known: bool = False
    usual: UsualLevel | None = None
    regions: tuple[Region, ...] = ()
    road_stops: tuple = ()          # the load's stops (lat, lng) the road was made through: when they change, a new road
    fueled_at: datetime | None = None  # when the gauge last rose like a fill: no new message for FUEL_HOLD_MIN after it


# A Love's on the road as the rules see it now. verdict: "passed", "early" (well above the driver's level), "range",
# "late" (under the reserve in the worst case) or "out" (out of reach in the worst case).
@dataclass(frozen=True)
class StopView:
    stop: StoreOnRoute
    arrive_pct: float
    worst_pct: float
    verdict: str


# A stretch of road where a tank of fuel runs down: from where the gauge reaches the driver's level, past where it
# crosses the reserve, to where the truck runs out. A Love's before `reserve_mi` is safe, one after it isn't.
@dataclass(frozen=True)
class Zone:
    start_mi: float
    reserve_mi: float
    end_mi: float


# Everything the rules see for a truck now, to draw: the decision, every Love's, the regions and the fuel zones.
@dataclass(frozen=True)
class Picture:
    decision: Decision
    views: tuple[StopView, ...]
    regions: tuple[Region, ...]
    zones: tuple[Zone, ...] = ()


# How a source copy's last refresh went (one row per source of `source_health`; also Google Maps, which the heartbeat
# asks itself): when it was last tried, when it last worked, and the error of the last try when that failed (None when
# it worked).
@dataclass(frozen=True)
class SourceHealth:
    name: str
    last_try_at: datetime
    last_ok_at: datetime | None
    error: str | None


# Something not working, found by the heartbeat (base/runner/health): which part, what is wrong, since when (None when that
# isn't known), and whether the alert about it went out (a row of `health_alerts` keeps it till it is fixed).
@dataclass(frozen=True)
class Problem:
    component: str
    text: str
    since: datetime | None = None
    told: bool = False


# One message of a driver group as the card agent reads it (features/cards/telegram_agent): when, who wrote it, whether it is
# the agent's own account, its text, and its photo as JPEG bytes when it has one and the photo was fetched.
@dataclass(frozen=True)
class ChatLine:
    message_id: int
    at: datetime
    sender: str
    ours: bool
    text: str
    photo: bytes | None = None
