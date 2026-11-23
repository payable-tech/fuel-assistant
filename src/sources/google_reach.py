# Google reachability (no key, no cost): can this PC reach the addresses the Routes and Places APIs are called at?
# For the heartbeat: on 2026-11-22 the office network refused them for hours, no new road could be made, nobody knew.
import httpx

from sources import google_places, google_routes

URLS = (google_routes.URL, google_places.URL)  # exactly the addresses the program calls, not Google in general
TIMEOUT_S = 10


# Tries each API's address once. Returns None when both answer, else which one didn't and why. Any answer counts, even
# "not found" (what Google says to a call with no question): the check is only whether the address can be reached, so
# a wrong key or an unpaid bill isn't seen here.
def unreachable() -> str | None:
    for url in URLS:
        host = httpx.URL(url).host
        try:
            httpx.get(f"https://{host}/", timeout=TIMEOUT_S)
        except Exception as error:  # whatever the failure, the heartbeat's other checks must still run
            return f"{host}: {type(error).__name__}: {error}"
    return None
