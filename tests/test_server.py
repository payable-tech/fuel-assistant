# Tests who may open the dashboard (this PC and office networks, not the Radmin VPN or the internet) and the
# page's version that tells an open page to reload itself.
import os

import config
import server


# This PC and the office network are let in; a Radmin VPN address (26.x) and a public one are not.
def test_who_may_open_the_dashboard():
    assert server.allowed("127.0.0.1") and server.allowed("10.0.40.57") and server.allowed("192.168.1.20")
    assert not server.allowed("26.179.78.200") and not server.allowed("8.8.8.8")


# The page's version is its newest file's change time, the vendored libraries left out, so an open page reloads
# itself after an update of the page but not of a library.
def test_web_version(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WEB_DIR", tmp_path)
    page, lib = tmp_path / "js" / "app.js", tmp_path / "vendor" / "lib.js"
    for f in (page, lib):
        f.parent.mkdir()
        f.write_text("x")
    os.utime(page, ns=(10**18, 10**18))
    os.utime(lib, ns=(2 * 10**18, 2 * 10**18))
    assert server.web_version() == str(10**18)
    os.utime(page, ns=(3 * 10**18, 3 * 10**18))
    assert server.web_version() == str(3 * 10**18)
