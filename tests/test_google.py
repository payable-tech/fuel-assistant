# Tests which Google places count as truck stops for the low-fuel backup, on real results along 540201's and 0530's
# roads (2026-11-05): tagged truck stop and gas station, or a big chain's travel center; never a gas station in town.
from base.sources.google import is_truck_stop

BOTH = ["truck_stop", "gas_station", "point_of_interest"]


# Real truck stops, however Google tags them (TA as car repair, Petro as a rest stop).
def test_real_truck_stops():
    assert is_truck_stop("Pilot Travel Center", BOTH) and is_truck_stop("Public Diesel", BOTH)
    assert is_truck_stop("TA Travel Center", ["car_repair"]) and is_truck_stop("TA Express Travel Center", ["rest_stop"])
    assert is_truck_stop("Petro Travel Center", ["rest_stop"]) and is_truck_stop("Petro truckstop", ["truck_stop"])
    assert is_truck_stop("Flying J Travel Center", BOTH)


# Gas stations in town, truck parking and repair shops: not where a truck fuels.
def test_not_truck_stops():
    assert not is_truck_stop("Quick Fuel", ["gas_station", "service"])                    # 540201, Indianapolis
    assert not is_truck_stop("Speedway", ["gas_station"]) and not is_truck_stop("Marathon", ["gas_station"])
    assert not is_truck_stop("Tipp City Truck Parking/M&I Development", ["parking_lot", "truck_stop"])
    assert not is_truck_stop("Casey's", ["pizza_restaurant", "truck_stop"])
    assert not is_truck_stop("TA Truck Service", ["car_repair"]) and not is_truck_stop("Tacos Stop", ["restaurant"])
