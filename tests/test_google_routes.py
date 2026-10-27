# Tests reading Google's encoded route line.
from sources import google_routes


# Google's own documented example decodes to its three points.
def test_decode_polyline():
    assert google_routes.decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
