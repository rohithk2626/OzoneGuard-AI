from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_india_coordinate():
    response = client.get("/api/v1/location/validate?lat=17.385&lon=78.487")
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_outside_india_bounds():
    response = client.get("/api/v1/location/validate?lat=40&lon=78")
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_website_is_served_by_the_backend():
    """One command runs everything: the backend also serves the frontend pages."""
    home = client.get("/")
    assert home.status_code == 200 and "OzoneGuard" in home.text and "text/html" in home.headers["content-type"]
    assert client.get("/analytics.html").status_code == 200
    assert client.get("/js/api.js").status_code == 200
    assert client.get("/api").json()["docs"] == "/docs"
    assert client.get("/api/v1/health").json()["status"] == "healthy"       # API routes still win over the website


def test_website_files_are_revalidated_by_browsers():
    """Pages, scripts and icons must not be reused from the browser cache without checking for a newer version."""
    for path in ("/", "/locations.html", "/js/main.js", "/css/style.css", "/favicon.svg"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers.get("cache-control") == "no-cache", path
    assert "no-cache" not in client.get("/api/v1/health").headers.get("cache-control", "")
