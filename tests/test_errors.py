"""User-facing wording for failed calls to outside data services (backend/core/errors.py)."""
import requests

from backend.core.errors import describe_failure


def _http_error(code: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = code
    return requests.HTTPError(response=resp)


def test_network_errors_become_plain_reasons():
    raw = requests.ConnectionError("HTTPSConnectionPool(host='api.open-meteo.com', port=443): Max retries exceeded")
    msg = describe_failure(raw)
    assert "could not be reached" in msg and "Pool" not in msg and "443" not in msg
    assert "did not respond in time" in describe_failure(requests.Timeout("read timeout=20"))
    assert describe_failure(_http_error(502)) == "the service returned an error (HTTP 502)"


def test_written_messages_pass_through():
    msg = "NASA rejected the Earthdata token (HTTP 401). Generate a new token."
    assert describe_failure(RuntimeError(msg)) == msg


def test_low_level_text_is_hidden():
    assert describe_failure(RuntimeError("<urllib3.connection.HTTPSConnection object at 0x7f>")) == \
        "the service returned an unexpected response"
    assert describe_failure(RuntimeError("")) == "the service returned an unexpected response"


def test_prediction_endpoint_hides_raw_error(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.services import prediction_service as ps

    def boom(*a, **k):
        raise requests.ConnectionError("HTTPSConnectionPool(host='air-quality-api.open-meteo.com', port=443)")

    monkeypatch.setattr(ps, "_fetch", boom)
    ps._cache.clear()
    r = TestClient(app).get("/api/v1/predictions/24h", params={"lat": 17.39, "lon": 78.49})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["status"] == "provider_unavailable"
    assert "Open-Meteo" in detail["message"] and "could not be reached" in detail["message"]
    assert "Pool" not in detail["message"]
