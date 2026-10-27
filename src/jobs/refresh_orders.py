# Orders job: copies all active Datatruck orders and their stops into `dt_orders` / `dt_stops`.
import db
from jobs import mirror
from sources import datatruck


# Replaces the orders copy with the current active orders. Returns True when it was refreshed.
def run() -> bool:
    return mirror.refresh("Datatruck orders", datatruck.active_orders, db.replace_orders)
