from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.conftest import err


def test_health(client):
    assert client.get("/health").status_code == 200


def test_create_and_lookup_all_spellings(client):
    r = client.post("/members", json={"name": "  Noura Al Harbi ", "country": "SA", "phone": "055 123 4567"})
    assert r.status_code == 201
    m = r.json()
    assert m["name"] == "Noura Al Harbi" and m["phone"] == "+966551234567" and m["country"] == "SA"
    for params in [{"phone": "966551234567"}, {"phone": "+966551234567"},
                   {"phone": "055 123 4567", "country": "SA"}, {"phone": "(055)-123-4567", "country": "SA"}]:
        r = client.get("/members/lookup", params=params)
        assert r.status_code == 200, (params, r.text)
        assert r.json() == m
    # raw %2B form from the spec
    assert client.get("/members/lookup?phone=%2B966551234567").json() == m


@pytest.mark.parametrize("country,phone,expected", [
    ("AE", "050 123 4567", "+971501234567"),
    ("AE", "+971501234567", "+971501234567"),
    ("BH", "3600 1234", "+97336001234"),
    ("BH", "97336001234", "+97336001234"),
    ("SA", "+97336001234", "+97336001234"),   # foreign SIM allowed
    ("BH", "+971501234567", "+971501234567"),
])
def test_create_normalises(client, country, phone, expected):
    r = client.post("/members", json={"name": "x", "country": country, "phone": phone})
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == expected


@pytest.mark.parametrize("country,phone", [
    ("SA", "00966551234567"),      # 00 prefix
    ("SA", "0551234567x"),          # junk char
    ("SA", "055.123.4567"),          # dot not stripped
    ("SA", "++966551234567"),
    ("SA", "966+551234567"),
    ("SA", "0112345678"),          # landline
    ("SA", "055123456"),           # short
    ("SA", "05512345678"),         # long
    ("BH", "0551234567"),          # SA/AE national read as BH
    ("SA", "36001234"),            # BH national read as SA
    ("BH", "036001234"),           # BH has no trunk zero
    ("SA", "+0551234567"),         # + then national
    ("SA", "+551234567"),
    ("SA", "+966051234567"),       # trunk zero after dial code
    ("SA", ""),
    ("SA", "   "),
    ("AE", "+97346001234"),        # BH landline
])
def test_create_invalid_phone(client, country, phone):
    r = client.post("/members", json={"name": "x", "country": country, "phone": phone})
    assert r.status_code == 422 and err(r) == "INVALID_PHONE", (phone, r.text)


@pytest.mark.parametrize("body", [
    {"country": "SA", "phone": "0551234567"},
    {"name": "", "country": "SA", "phone": "0551234567"},
    {"name": "   ", "country": "SA", "phone": "0551234567"},
    {"name": "x" * 121, "country": "SA", "phone": "0551234567"},
    {"name": 5, "country": "SA", "phone": "0551234567"},
    {"name": "x", "country": "KW", "phone": "0551234567"},
    {"name": "x", "country": "sa", "phone": "0551234567"},
    {"name": "x", "phone": "0551234567"},
    {"name": "x", "country": "SA"},
    {"name": "x", "country": "SA", "phone": 551234567},
    [],
])
def test_create_validation(client, body):
    r = client.post("/members", json=body)
    assert r.status_code == 422 and err(r) == "VALIDATION", r.text


def test_name_limits(client):
    assert client.post("/members", json={"name": " " + "x" * 120 + " ", "country": "SA", "phone": "0551111111"}).status_code == 201


def test_malformed_json(client):
    r = client.post("/members", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422 and err(r) == "VALIDATION"


def test_phone_taken_across_spellings(client):
    first = client.post("/members", json={"name": "a", "country": "SA", "phone": "0551234567"}).json()
    r = client.post("/members", json={"name": "b", "country": "AE", "phone": "966-55-123-4567"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PHONE_TAKEN"
    assert r.json()["error"]["existing_member_id"] == first["id"]


def test_phone_taken_concurrently(client):
    spellings = ["0551234567", "+966551234567", "966551234567", "055 123 4567", "(055) 123-4567"] * 4

    def post(p):
        return client.post("/members", json={"name": "x", "country": "SA", "phone": p})

    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(post, spellings))
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and codes.count(409) == len(spellings) - 1
    winner = next(r.json()["id"] for r in results if r.status_code == 201)
    assert all(r.json()["error"]["existing_member_id"] == winner for r in results if r.status_code == 409)


def test_lookup_rules(client):
    client.post("/members", json={"name": "a", "country": "BH", "phone": "36001234"})
    ok = lambda **p: client.get("/members/lookup", params=p)
    assert ok(phone="36001234", country="BH").status_code == 200
    assert err(ok(phone="36001234")) == "PHONE_NEEDS_COUNTRY"
    assert err(ok(phone="0551234567")) == "PHONE_NEEDS_COUNTRY"
    assert err(ok(phone="36001234", country="SA")) == "INVALID_PHONE"
    assert err(ok(phone="0551234567", country="BH")) == "INVALID_PHONE"
    assert err(ok(phone="+97336001234", country="SA")) == "PHONE_COUNTRY_MISMATCH"
    assert ok(phone="+97336001234", country="BH").status_code == 200
    assert err(ok(phone="0012345")) == "INVALID_PHONE"
    assert err(ok(phone="abc", country="SA")) == "INVALID_PHONE"
    assert err(ok(phone="0551234567", country="XX")) == "VALIDATION"
    assert err(client.get("/members/lookup")) == "VALIDATION"
    r = ok(phone="0559999999", country="SA")
    assert r.status_code == 404 and err(r) == "NOT_FOUND"


def test_unknown_route_is_error_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404 and err(r) == "NOT_FOUND"
