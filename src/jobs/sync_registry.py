# Sync job: refreshes the Samsara, Datatruck and Telegram copies, then rebuilds the linked `trucks` table.
import db
from core import linking
from jobs import mirror
from models import SyncedTruck
from sources import datatruck_web, samsara, telegram


# Refreshes every source copy it can, then relinks from whatever copies the DB holds. Returns linked count.
def run() -> int:
    mirror.refresh("Samsara vehicles", samsara.vehicles, db.replace_samsara_vehicles)
    mirror.refresh("Datatruck trucks", datatruck_web.trucks, db.replace_dt_trucks)
    mirror.refresh("Datatruck drivers", datatruck_web.drivers, db.replace_dt_drivers)
    mirror.refresh("Telegram groups", telegram.groups, db.replace_tg_groups)
    return relink()


# Rebuilds `trucks` from the source copies: VIN pairs plus each truck's auto-matched Telegram group.
def relink() -> int:
    with db.connect() as conn:
        dt_trucks = db.dt_trucks(conn)
        pairs = linking.link_by_vin(db.samsara_vehicles(conn), dt_trucks)
        chats = linking.match_chats([t.unit for t in dt_trucks], db.tg_groups(conn), db.dt_drivers(conn))
        db.replace_trucks(conn, [
            SyncedTruck(unit=t.unit, samsara_id=v.samsara_id, vin=t.vin, name=v.name, mpg=v.mpg,
                        auto_chat_id=chats[t.unit].chat_id, chat_note=chats[t.unit].note)
            for v, t in pairs
        ])
    return len(pairs)
