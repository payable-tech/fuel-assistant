# Tests the market yardstick: reading the EIA file, states to regions, and pricing a purchase between two Mondays.
import pytest

from base.models import FuelLine, MarketPrice
from base.sources import eia
from features.dashboard import market

MONDAY_OCT_12 = 46307.0  # how Excel stores 2026-10-12 (days since 1899-12-30)


# One fuel line in a state at a local time; the rest are fixed test values.
def line(state: str, fueled_at: str) -> FuelLine:
    return FuelLine(1, fueled_at, "fuel", "ULSD", 100.0, 600.0, 550.0, 0.0, True, "LOVES #1", "", state, "TTL",
                    "340", "company", 7, "", "lease", None)


# A sheet laid out like EIA's: title row, series keys, series names, then dates with prices.
def eia_sheet(names_start: str, *rows) -> list[list]:
    keys = list(eia.SERIES)
    return [["Back to Contents", "Data"], ["Sourcekey", *keys], ["Date", *[f"{names_start} {k}" for k in keys]], *rows]


# The weekly sheet is picked over the monthly one with the same series, and blank cells are skipped.
def test_read_picks_weekly_sheet():
    monthly = eia_sheet("Monthly", [MONDAY_OCT_12, *[9.0] * len(eia.SERIES)])
    weekly = eia_sheet("Weekly", [MONDAY_OCT_12, 6.179, *[""] * (len(eia.SERIES) - 1)], ["Note: prices include taxes"])
    assert eia.read([monthly, weekly], datemode=0) == [MarketPrice("2026-10-12", "U.S.", 6.179)]


# A file without the weekly sheet fails loudly instead of loading nothing.
def test_read_without_weekly_sheet():
    with pytest.raises(ValueError):
        eia.read([eia_sheet("Monthly")], datemode=0)


# The source's regions and the state map name the same regions, so every state finds its price.
def test_region_names_match():
    assert set(eia.SERIES.values()) == set(market.REGIONS) | {market.US}


# States map to their EIA region; anything unknown uses the national price.
def test_region_of():
    assert market.region_of("TX") == "Gulf Coast" and market.region_of("ca") == "California"
    assert market.region_of("AZ") == "West Coast except California" and market.region_of("OH") == "Midwest"
    assert market.region_of("ON") == market.region_of("") == "U.S."


# A purchase halfway between two Mondays gets the price halfway between theirs.
def test_price_between_mondays():
    price_of = market.pricer([MarketPrice("2026-10-12", "Gulf Coast", 6.00), MarketPrice("2026-10-19", "Gulf Coast", 6.70)])
    assert price_of(line("TX", "2026-10-12 00:00")) == 6.00
    assert round(price_of(line("TX", "2026-10-15 12:00")), 6) == 6.35


# A region with no price uses the national one; past the newest Monday the newest price holds; before any, none.
def test_price_fallbacks():
    price_of = market.pricer([MarketPrice("2026-10-12", "U.S.", 6.18)])
    assert price_of(line("TX", "2026-10-14 08:00")) == 6.18
    assert price_of(line("TX", "2026-10-05 08:00")) is None
