# Market job: copies the U.S. EIA weekly retail diesel prices into `market_prices`. EIA adds a week every Monday.
from base.fleet import mirror
from base.sources import eia
from base.store import db


# Replaces the market prices copy from EIA's file. Returns True when it was refreshed.
def run() -> bool:
    return mirror.refresh("Market diesel prices", eia.weekly_prices, db.replace_market_prices)
