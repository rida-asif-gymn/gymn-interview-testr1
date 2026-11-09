import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def make(client):
    """Small helpers to create entities and assert success."""

    class Make:
        n = 0

        def member(self, country="SA", phone=None, name="Test Member"):
            Make.n += 1
            if phone is None:
                phone = {"SA": f"+96655{Make.n:07d}", "AE": f"+97155{Make.n:07d}", "BH": f"+9733{Make.n:07d}"}[country]
            r = client.post("/members", json={"name": name, "country": country, "phone": phone})
            assert r.status_code == 201, r.text
            return r.json()

        def plan(self, id, country, monthly, joining_fee=0):
            r = client.post("/plans", json={"id": id, "country": country, "monthly": monthly, "joining_fee": joining_fee})
            assert r.status_code == 201, r.text
            return r.json()

        def agreement(self, member_id, plan_id, start_date, due_day):
            r = client.post("/agreements", json={"member_id": member_id, "plan_id": plan_id,
                                                 "start_date": start_date, "due_day": due_day})
            assert r.status_code == 201, r.text
            return r.json()

    return Make()


def err(r):
    return r.json()["error"]["code"]
