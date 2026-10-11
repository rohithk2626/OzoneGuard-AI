"""India outline tests: land points in, sea and neighbouring countries out."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.geospatial_service import boundary_available, is_within_india_bounds
from ml import config

client = TestClient(app)

INSIDE = {
    "Port Blair (Andaman)": (11.62, 92.73), "Kavaratti (Lakshadweep)": (10.57, 72.64), "Kanyakumari": (8.08, 77.55),
    "Dwarka": (22.24, 68.97), "Kibithu": (28.28, 97.02), "Mumbai seafront": (18.94, 72.82), "Rameswaram": (9.29, 79.31),
    "Gangtok": (27.33, 88.61), "Moreh": (24.25, 94.30), "Indira Point": (6.78, 93.83),
}
OUTSIDE = {
    "Karachi": (24.86, 67.01), "Lahore": (31.55, 74.34), "Kathmandu": (27.72, 85.32), "Thimphu": (27.47, 89.64),
    "Dhaka": (23.81, 90.41), "Colombo": (6.93, 79.86), "Lhasa": (29.65, 91.12), "Yangon": (16.87, 96.20),
    "Arabian Sea": (15.0, 68.5), "Bay of Bengal": (15.0, 88.0), "north of India": (40.0, 78.0),
}


def test_outline_file_is_present():
    assert boundary_available()


def test_every_model_location_is_inside():
    assert [l[1] for l in config.LOCATIONS if not is_within_india_bounds(l[3], l[4])] == []


@pytest.mark.parametrize("name", INSIDE)
def test_inside(name):
    assert is_within_india_bounds(*INSIDE[name])


@pytest.mark.parametrize("name", OUTSIDE)
def test_outside(name):
    assert not is_within_india_bounds(*OUTSIDE[name])


def test_routes_reject_sea_and_neighbours():
    assert client.get("/api/v1/location/validate?lat=15&lon=88").json()["valid"] is False
    assert client.get("/api/v1/location/overview?lat=27.72&lon=85.32").status_code == 400
    assert client.get("/api/v1/predictions/24h?lat=15&lon=68.5").status_code == 400


def test_presets_list():
    rows = client.get("/api/v1/location/presets").json()
    assert len(rows) == 38 and {"name", "latitude", "longitude", "region"} <= set(rows[0])
