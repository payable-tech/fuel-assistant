# Dashboard server: serves the web/ folder and the numbers the page reads at /api/... Other PCs on the same network
# can open it when DASHBOARD_HOST allows; nothing outside web/ is ever served, and nothing here changes data.
import ctypes
import json
import logging
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from urllib.parse import parse_qs

from features.dashboard import dashboard, settings

log = logging.getLogger(__name__)

# The JSON routes the page reads: path -> function that builds the numbers from the address's query values.
ROUTES = {
    "/api/baseline": lambda query: dashboard.baseline_payload(dashboard.today()),
    "/api/live": lambda query: dashboard.live_payload(dashboard.today()),
    "/api/drivers": lambda query: dashboard.drivers_payload(),
    "/api/fleet": lambda query: dashboard.fleet_payload(),
    "/api/recommend": lambda query: dashboard.recommend_payload(),
    "/api/recommend/truck": lambda query: dashboard.recommend_truck(query["unit"][0]),
    "/api/recommend/trip": lambda query: dashboard.recommend_driven(query["unit"][0]),
    "/api/recommend/past": lambda query: dashboard.recommend_past(query["unit"][0], int(query["order"][0])),
    "/api/accounting": lambda query: dashboard.accounting_payload(query.get("statement", [None])[0]),
    "/api/cards": lambda query: dashboard.cards_payload(),
    "/api/cards/run": lambda query: dashboard.cards_run(int(query["chat"][0]), int(query["message"][0])),
    "/api/version": lambda query: {"version": web_version()},
}


# The dashboard's server: one thread per request, and room for a page's whole burst of requests to wait while the
# program is busy (the default of 5 waiting was too few: a page opened right after a restart lost some of its numbers).
class Server(ThreadingHTTPServer):
    request_queue_size = 64


# Serves files from web/, plus the JSON routes (ROUTES) the page reads its numbers from.
class Handler(SimpleHTTPRequestHandler):
    # Windows can map .js to text/plain from the registry; browsers need the real types.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".css": "text/css",
                      ".html": "text/html", ".svg": "image/svg+xml", ".woff2": "font/woff2"}

    # Lets in only this PC and the office networks (DASHBOARD_NETWORKS); anyone else, e.g. on the Radmin VPN, gets a
    # 403 for every request.
    def parse_request(self) -> bool:
        if not super().parse_request():
            return False
        if not allowed(self.client_address[0]):
            self.send_error(403, "This dashboard is for the office network only")
            return False
        return True

    # Answers the /api/ routes with fresh numbers; any other path is a file from web/.
    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        build = ROUTES.get(path)
        if build is None:
            super().do_GET()
            return
        try:
            self._send_json(200, build(parse_qs(query)))
        except LookupError as missing:  # e.g. a truck that isn't a test truck
            self._send_json(404, {"error": str(missing)})
        except ConnectionError:  # the browser left before the answer was sent (tab closed, page reloaded): nothing to do
            log.debug("Browser left before %s was answered", path)
        except Exception as error:  # the page shows this message instead of a blank screen
            log.exception("Dashboard numbers failed")
            self._send_json(500, {"error": f"{type(error).__name__}: {error}"})

    # Writes a JSON response.
    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Makes the browser check for a newer version on every load, so page updates and fresh numbers show at once.
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    # Sends request lines to the log at debug level instead of printing every request.
    def log_message(self, format: str, *args) -> None:
        log.debug(format, *args)


# Runs the dashboard at http://127.0.0.1:<port> (and at this PC's office address from other office PCs, when
# DASHBOARD_HOST allows) until stopped with Ctrl+C. `start_jobs`: what starts the automatic jobs, called once the
# server is set up (None: only show the data).
def serve(port: int, start_jobs=None) -> None:
    server = Server((settings.DASHBOARD_HOST, port), partial(Handler, directory=str(settings.WEB_DIR)))
    _stay_awake()
    _no_click_pause()
    if start_jobs:
        start_jobs()
        log.info("Automatic refreshes are on (see the Data tab for their last runs)")
    log.info("Dashboard running at http://127.0.0.1:%d  (Ctrl+C to stop)", port)
    if settings.DASHBOARD_HOST != "127.0.0.1":  # the PC's office address: its name can resolve to the Radmin VPN first
        office = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if allowed(a) and not a.startswith("127.")]
        log.info("Other PCs on the office network: %s", ", ".join(f"http://{a}:{port}" for a in office) or "none found")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# The page's version: when its newest file in web/ (the vendored libraries aside) last changed. An open page asks
# for it every minute and reloads itself when it differs, so it never runs old code against new numbers.
def web_version() -> str:
    web = settings.WEB_DIR
    files = [p for p in web.rglob("*") if p.is_file() and "vendor" not in p.relative_to(web).parts]
    return str(max((p.stat().st_mtime_ns for p in files), default=0))


# True when a visitor's address is this PC or on one of the office networks (DASHBOARD_NETWORKS).
def allowed(address: str) -> bool:
    return any(ip_address(address) in ip_network(net) for net in settings.DASHBOARD_NETWORKS)


# Asks Windows not to put the PC to sleep while this program runs, so the data keeps refreshing overnight. The screen
# may still turn off; the request ends by itself when the program stops.
def _stay_awake() -> None:
    es_continuous, es_system_required = 0x80000000, 0x00000001  # "until I say otherwise" + "keep the system on"
    if not ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required):
        log.warning("Windows refused to keep the PC awake: it may sleep and pause the refreshes")


# Turns off click-to-select (QuickEdit) in this program's window: a click there starts a selection, and Windows
# pauses every write to the window until it ends, which froze the refreshes for hours on 2026-10-28.
def _no_click_pause() -> None:
    kernel32 = ctypes.windll.kernel32
    window_input = kernel32.GetStdHandle(-10)  # the window's keyboard and mouse input
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(window_input, ctypes.byref(mode)):
        return  # no window (started hidden or from a test): nothing to click
    quick_edit, extended_flags = 0x0040, 0x0080  # Windows only reads the quick_edit bit when extended_flags is set
    if not kernel32.SetConsoleMode(window_input, (mode.value & ~quick_edit) | extended_flags):
        log.warning("Could not turn off click-to-select: a click in this window can still pause the program")
