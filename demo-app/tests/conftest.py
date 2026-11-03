"""Shared test fixtures: a client backed by a fresh SQLite file, a ready-made group, and a helper
to add expenses to that group."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("BUGLINE_DB", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def trip(client) -> dict:
    """A group with three members. Returns the group and a name -> member id map."""
    group = client.post("/groups", json={"name": "Weekend trip"}).json()
    ids = {
        name: client.post(f"/groups/{group['id']}/members", json={"name": name}).json()["id"]
        for name in ["Asha", "Ravi", "Meera"]
    }
    return {"group": group, "ids": ids}


@pytest.fixture
def pay(client, trip):
    """pay("Asha", 300) adds an expense paid by Asha to the trip group and returns it."""

    def add(payer: str, amount: float, **extra) -> dict:
        body = {"payer_id": trip["ids"][payer], "amount": amount, "description": "test", **extra}
        response = client.post(f"/groups/{trip['group']['id']}/expenses", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return add
