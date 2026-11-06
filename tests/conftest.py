import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="mckpxe-test-"))
ADMIN_PASSWORD = "first-admin-pass"
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp / 'test.db'}",
    "DATA_DIR": str(_tmp / "data"),
    "SERVER_IP": "10.0.0.5",
    "INITIAL_ADMIN_PASSWORD": ADMIN_PASSWORD,
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


@pytest.fixture(scope="session")
def client():
    """Signed in to the admin console as the first admin."""
    from fastapi.testclient import TestClient

    from mckpxe.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
def anon(client):
    """A second browser, not signed in."""
    from fastapi.testclient import TestClient

    from mckpxe.main import app

    return TestClient(app)


def console_headers(client, mac, username="admin", password=ADMIN_PASSWORD):
    """Sign in at a machine's imaging environment, as the agent does."""
    r = client.post("/api/agent/login", json={"mac": mac, "username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def data_dir():
    return _tmp / "data"
