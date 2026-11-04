import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="mckpxe-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp / 'test.db'}",
    "DATA_DIR": str(_tmp / "data"),
    "SERVER_IP": "10.0.0.5",
    "DEV_USER": "tester@example.com",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from mckpxe.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def data_dir():
    return _tmp / "data"
