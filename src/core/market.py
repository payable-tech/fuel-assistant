# Market yardstick (pure): prices each fuel line at the EIA average retail diesel price of its region and week.
# Those prices don't depend on where our drivers fuel, so comparing them with what we paid judges our decisions.
from datetime import datetime, timedelta

from core.fuel import shift_days, week_of
from models import FuelLine, MarketPrice, US

REGIONS = {  # EIA region -> its states (the petroleum regions, "PADDs", EIA reports diesel prices for)
    "New England": "CT ME MA NH RI VT",
    "Central Atlantic": "DE DC MD NJ NY PA",
    "Lower Atlantic": "FL GA NC SC VA WV",
    "Midwest": "IL IN IA KS KY MI MN MO NE ND OH OK SD TN WI",
    "Gulf Coast": "AL AR LA MS NM TX",
    "Rocky Mountain": "CO ID MT UT WY",
    "California": "CA",
    "West Coast except California": "AK AZ HI NV OR WA",
}
REGION_OF_STATE = {state: region for region, states in REGIONS.items() for state in states.split()}


# The EIA region of a state code; the whole country for anything else (a blank, or a Canadian province).
def region_of(state: str) -> str:
    return REGION_OF_STATE.get(state.strip().upper(), US)


# Returns a function giving a fuel line's market price per gallon in its region (else the national one): between two
# Mondays' prices in proportion to the time, so a fast week isn't judged by Monday alone (core/market).
def pricer(prices: list[MarketPrice]):
    table = {(week_of(p.day), p.region): p.price for p in prices}

    # The price of a region on a Monday, else the national one, else None.
    def on(monday: str, region: str) -> float | None:
        return table.get((monday, region)) or table.get((monday, US))

    # The market price per gallon for one fuel line.
    def price_of(line: FuelLine) -> float | None:
        monday = week_of(line.fueled_at)
        region = region_of(line.state)
        start, end = on(monday, region), on(shift_days(monday, 7), region)
        if start is None or end is None:  # past the newest Monday its price holds; before any price, none
            return start
        into_week = (datetime.fromisoformat(line.fueled_at) - datetime.fromisoformat(monday)) / timedelta(days=7)
        return start + into_week * (end - start)

    return price_of
