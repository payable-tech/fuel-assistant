# Love's website (read-only): a store's own page, for the highway and exit it sits at. The price sheets have no exits.
import html
import re

import httpx

URL = "https://www.loves.com/locations/{store_no}"  # redirects to the store's page


# Returns a store's highway and exit as its page says them, "I-70 (Exit 208)"; None when the page names no exit.
# Raises when the page can't be read or isn't that store's.
def exit_of(store_no: str) -> str | None:
    response = httpx.get(URL.format(store_no=store_no), headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
                         follow_redirects=True)
    response.raise_for_status()
    return way(response.text, store_no)


# The highway and exit in a store page: its heading reads "#563 ... Belmont, OH | Exit 208/OH-149 on I-70", which becomes
# "I-70 (Exit 208)" (the exit's number only, as on the sign). None when the heading names no numbered exit; LookupError
# when the page has no heading for this store (not its page).
def way(page: str, store_no: str) -> str | None:
    text = html.unescape(re.sub(r"<!--.*?-->", "", page))  # the page splits its words with empty comments
    heading = re.search(rf"#{re.escape(store_no)}</h1><h2>([^<]*)<", text)
    if not heading:
        raise LookupError(f"No heading for store {store_no} on its Love's page")
    # "37/Griffith Rd": the number only. A numbered exit only: off the interstates the page names a cross road instead
    # ("Exit FM 1960 on Hwy 290", "Exit 2nd St on US Hwy-36"), which is no exit sign to look for
    found = re.search(r"\|\s*Exit (\d+[A-Z]?)(?![A-Za-z0-9]).* on (\S.*)$", heading.group(1).strip())
    return f"{found.group(2).strip()} (Exit {found.group(1)})" if found else None
