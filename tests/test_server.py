# Tests who may open the dashboard: this PC and office (private) networks, not the Radmin VPN or the internet.
import server


# This PC and the office network are let in; a Radmin VPN address (26.x) and a public one are not.
def test_who_may_open_the_dashboard():
    assert server.allowed("127.0.0.1") and server.allowed("10.0.40.57") and server.allowed("192.168.1.20")
    assert not server.allowed("26.179.78.200") and not server.allowed("8.8.8.8")
