"""Non-ASCII input. Python's \\d matches every script's digits, so all patterns use [0-9]."""
import pytest

from tests.conftest import err


@pytest.mark.parametrize("phone", [
    "٠٥٥١٢٣٤٥٦٧",        # Arabic-Indic digits
    "05٥١٢٣٤٥٦٧",        # mixed: used to be stored as +9665٥١٢٣٤٥٦٧
    "۰۵۵۱۲۳۴۵۶۷",        # Persian digits
    "０５５１２３４５６７",  # full-width digits
    "+966٥٥١٢٣٤٥٦٧",
    "055–123–4567",      # en-dash is not a hyphen
    "055 123 4567",  # non-breaking space is not a space
    "055\t1234567",
])
def test_non_ascii_phone_rejected(client, phone):
    r = client.post("/members", json={"name": "x", "country": "SA", "phone": phone})
    assert r.status_code == 422 and err(r) == "INVALID_PHONE", r.text
    r = client.get("/members/lookup", params={"phone": phone, "country": "SA"})
    assert r.status_code == 422 and err(r) == "INVALID_PHONE", r.text


def test_mixed_digits_cannot_bypass_phone_taken(client):
    assert client.post("/members", json={"name": "a", "country": "SA", "phone": "0551234567"}).status_code == 201
    r = client.post("/members", json={"name": "b", "country": "SA", "phone": "05٥١٢٣٤٥٦٧"})
    assert r.status_code == 422


def test_non_ascii_dates_and_months_rejected(client, make):
    m = make.member("SA")
    make.plan("p", "SA", 100)
    for d in ["٢٠٢٦-٠٩-٢٠", "2026-09-٢٠"]:
        r = client.post("/agreements", json={"member_id": m["id"], "plan_id": "p", "start_date": d, "due_day": 1})
        assert r.status_code == 422 and err(r) == "VALIDATION"
    r = client.post("/reconciliation/runs", json={"month": "٢٠٢٦-١٠", "rows": []})
    assert r.status_code == 422 and err(r) == "VALIDATION"


def test_arabic_and_emoji_names_and_ids_are_fine(client):
    r = client.post("/members", json={"name": "  نورة الحربي  ", "country": "SA", "phone": "0551111111"})
    assert r.status_code == 201 and r.json()["name"] == "نورة الحربي"
    assert client.post("/members", json={"name": "ن" * 120, "country": "SA", "phone": "0551111112"}).status_code == 201
    assert err(client.post("/members", json={"name": "ن" * 121, "country": "SA", "phone": "0551111113"})) == "VALIDATION"
    assert client.post("/plans", json={"id": "خطة", "country": "SA", "monthly": 1, "joining_fee": 0}).status_code == 201


def test_method_not_allowed_shape(client):
    r = client.delete("/plans")
    assert r.status_code == 405 and err(r) == "METHOD_NOT_ALLOWED"
