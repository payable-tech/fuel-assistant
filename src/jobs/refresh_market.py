# Market job: copies the U.S. EIA weekly retail diesel prices into `market_prices`. EIA adds a week every Monday.
import db
from jobs import mirror
from sources import eia


# Replaces the market prices copy from EIA's file. Returns True when it was refreshed.
def run() -> bool:
    return mirror.refresh("Market diesel prices", eia.weekly_prices, db.replace_market_prices)
