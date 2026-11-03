"""Reverse geocoding: answers are cached and requests to Nominatim are spaced out (its usage policy)."""
import pytest
import requests

from backend.services import geocoding_service as geo


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self.payload


HYD = {"display_name": "Hyderabad, Telangana, India",
       "address": {"city": "Hyderabad", "state": "Telangana", "country": "India", "country_code": "in"}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    geo._cache.clear()
    monkeypatch.setattr(geo, "_last_request", 0.0)
    monkeypatch.setattr(geo, "MIN_INTERVAL_S", 0.0)
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        return FakeResponse(HYD)
    monkeypatch.setattr(geo.requests, "get", fake_get)
    return calls


def test_place_fields(fresh):
    p = geo.reverse_geocode(17.385, 78.4867)
    assert p["city"] == "Hyderabad" and p["state"] == "Telangana" and p["source"] == "OpenStreetMap Nominatim"
    assert "OzoneGuard" in geo.USER_AGENT


def test_repeat_lookups_use_the_cache(fresh):
    geo.reverse_geocode(17.385, 78.4867)
    geo.reverse_geocode(17.385, 78.4867)
    geo.reverse_geocode(17.3851, 78.48671)          # same point to ~10 m
    assert len(fresh) == 1
    geo.reverse_geocode(13.08, 80.27)               # a different place is looked up
    assert len(fresh) == 2


def test_cached_answer_cannot_be_changed_by_caller(fresh):
    geo.reverse_geocode(17.385, 78.4867)["city"] = "changed"
    assert geo.reverse_geocode(17.385, 78.4867)["city"] == "Hyderabad"


def test_failures_are_not_cached(monkeypatch, fresh):
    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: FakeResponse({}, status=503))
    with pytest.raises(requests.HTTPError):
        geo.reverse_geocode(17.385, 78.4867)
    assert geo._cache == {}


def test_requests_are_spaced_out(monkeypatch, fresh):
    monkeypatch.setattr(geo, "MIN_INTERVAL_S", 1.0)
    slept = []
    monkeypatch.setattr(geo.time, "sleep", slept.append)
    geo.reverse_geocode(17.385, 78.4867)
    geo.reverse_geocode(13.08, 80.27)
    assert len(slept) == 1 and 0.9 < slept[0] <= 1.0
