import pytest

from app.schedule import round_half_up_div, vat_for
from tests.conftest import err


def invoices(client, agreement_id, frm, to):
    r = client.get(f"/agreements/{agreement_id}/invoices", params={"from": frm, "to": to})
    assert r.status_code == 200, r.text
    return r.json()


def test_rounding_helpers():
    assert round_half_up_div(29900 * 11, 30) == 10963
    assert round_half_up_div(5, 2) == 3
    assert round_half_up_div(7, 2) == 4
    assert vat_for(10963, 15) == 1644
    assert vat_for(21948, 5) == 1097
    assert vat_for(10, 5) == 1  # 0.5 -> 1
    assert vat_for(5790, 10) == 579  # BHD stays in fils


def test_plan_create_and_validation(client):
    r = client.post("/plans", json={"id": "anytime-sa", "country": "SA", "monthly": 29900, "joining_fee": 0})
    assert r.status_code == 201
    assert r.json() == {"id": "anytime-sa", "country": "SA", "currency": "SAR", "monthly": 29900, "joining_fee": 0}
    r = client.post("/plans", json={"id": "anytime-sa", "country": "SA", "monthly": 1, "joining_fee": 0})
    assert r.status_code == 409 and err(r) == "PLAN_EXISTS"
    for bad in [
        {"id": "p", "country": "SA", "monthly": 0, "joining_fee": 0},
        {"id": "p", "country": "SA", "monthly": 1, "joining_fee": -1},
        {"id": "p", "country": "SA", "monthly": 1.5, "joining_fee": 0},
        {"id": "p", "country": "SA", "monthly": "100", "joining_fee": 0},
        {"id": "p", "country": "SA", "monthly": True, "joining_fee": 0},
        {"id": "p", "country": "QA", "monthly": 1, "joining_fee": 0},
        {"id": "", "country": "SA", "monthly": 1, "joining_fee": 0},
        {"id": 3, "country": "SA", "monthly": 1, "joining_fee": 0},
        {"country": "SA", "monthly": 1, "joining_fee": 0},
        {"id": "p", "country": "SA", "monthly": 1},
    ]:
        r = client.post("/plans", json=bad)
        assert r.status_code == 422 and err(r) == "VALIDATION", bad


def test_agreement_errors(client, make):
    sa = make.member("SA")
    make.plan("sa", "SA", 100)
    make.plan("ae", "AE", 100)
    post = lambda **b: client.post("/agreements", json={"member_id": sa["id"], "plan_id": "sa",
                                                        "start_date": "2026-01-01", "due_day": 1, **b})
    assert post().status_code == 201
    assert err(post(member_id="nope")) == "UNKNOWN_MEMBER"
    assert err(post(plan_id="nope")) == "UNKNOWN_PLAN"
    assert err(post(plan_id="ae")) == "PLAN_COUNTRY_MISMATCH"
    for bad in [{"due_day": 0}, {"due_day": 32}, {"due_day": "1"}, {"start_date": "2026-02-30"},
                {"start_date": "2026-1-01"}, {"start_date": "20260101"}, {"start_date": "2026-01-01T00:00:00"},
                {"start_date": None}]:
        r = post(**bad)
        assert r.status_code == 422 and err(r) == "VALIDATION", bad


def test_spec_example_sa(client, make):
    m = make.member("SA")
    make.plan("anytime-sa", "SA", 29900)
    a = make.agreement(m["id"], "anytime-sa", "2026-09-20", 1)
    inv = invoices(client, a["id"], "2026-09-01", "2026-12-31")
    assert inv[0] == {"invoice_no": 1, "due_date": "2026-09-20", "kind": "FIRST",
                      "proration": {"days": 11, "cycle_days": 30},
                      "net": 10963, "vat": 1644, "total": 12607, "currency": "SAR"}
    assert inv[1] == {"invoice_no": 2, "due_date": "2026-10-01", "kind": "MONTHLY", "proration": None,
                      "net": 29900, "vat": 4485, "total": 34385, "currency": "SAR"}
    assert [i["due_date"] for i in inv] == ["2026-09-20", "2026-10-01", "2026-11-01", "2026-12-01"]
    assert [i["invoice_no"] for i in inv] == [1, 2, 3, 4]


def test_spec_example_ae_two_in_september(client, make):
    m = make.member("AE")
    make.plan("ae", "AE", 24900, 9900)
    a = make.agreement(m["id"], "ae", "2026-09-05", 20)
    inv = invoices(client, a["id"], "2026-09-01", "2026-09-30")
    assert inv[0]["proration"] == {"days": 15, "cycle_days": 31}
    assert (inv[0]["net"], inv[0]["vat"], inv[0]["total"]) == (21948, 1097, 23045)
    assert inv[1]["due_date"] == "2026-09-20" and inv[1]["invoice_no"] == 2 and inv[1]["net"] == 24900


def test_due_day_31_clamps(client, make):
    m = make.member("SA")
    make.plan("p", "SA", 1000)
    a = make.agreement(m["id"], "p", "2027-12-31", 31)  # start is a due date -> full price
    inv = invoices(client, a["id"], "2027-12-01", "2028-07-31")
    assert inv[0]["proration"] == {"days": 31, "cycle_days": 31} and inv[0]["net"] == 1000
    assert [i["due_date"] for i in inv] == ["2027-12-31", "2028-01-31", "2028-02-29", "2028-03-31",
                                           "2028-04-30", "2028-05-31", "2028-06-30", "2028-07-31"]


def test_start_on_clamped_due_date(client, make):
    m = make.member("SA")
    make.plan("p", "SA", 1000)
    a = make.agreement(m["id"], "p", "2026-02-28", 31)  # 28 Feb 2026 IS the due date
    inv = invoices(client, a["id"], "2026-02-01", "2026-03-31")
    assert inv[0]["proration"] == {"days": 31, "cycle_days": 31}
    assert inv[1]["due_date"] == "2026-03-31"
    a = make.agreement(m["id"], "p", "2026-02-27", 31)  # one day before -> N = 28 Feb, P = 31 Jan
    inv = invoices(client, a["id"], "2026-02-01", "2026-03-31")
    assert inv[0]["proration"] == {"days": 1, "cycle_days": 28}
    assert inv[1]["due_date"] == "2026-02-28"


def test_bhd_minor_units(client, make):
    m = make.member("BH")
    make.plan("bh", "BH", 26950, 0)
    a = make.agreement(m["id"], "bh", "2026-10-01", 1)
    inv = invoices(client, a["id"], "2026-10-01", "2026-10-31")
    assert inv[0]["net"] == 26950 and inv[0]["vat"] == 2695 and inv[0]["currency"] == "BHD"


def test_range_rules(client, make):
    m = make.member("SA")
    make.plan("p", "SA", 1000)
    a = make.agreement(m["id"], "p", "2026-01-15", 10)
    inv = invoices(client, a["id"], "2027-01-01", "2027-03-31")
    assert [(i["invoice_no"], i["due_date"]) for i in inv] == [(13, "2027-01-10"), (14, "2027-02-10"), (15, "2027-03-10")]
    assert invoices(client, a["id"], "2025-01-01", "2025-12-31") == []
    assert len(invoices(client, a["id"], "2026-01-01", "2027-01-02")) == 12  # exactly 366 days ok
    g = lambda f, t: client.get(f"/agreements/{a['id']}/invoices", params={"from": f, "to": t})
    assert err(g("2026-01-01", "2027-01-03")) == "INVALID_RANGE"
    assert err(g("2026-02-01", "2026-01-31")) == "INVALID_RANGE"
    assert err(g("2026-02-30", "2026-03-01")) == "VALIDATION"
    assert err(client.get(f"/agreements/{a['id']}/invoices", params={"from": "2026-01-01"})) == "VALIDATION"
    r = client.get("/agreements/nope/invoices", params={"from": "2026-01-01", "to": "2026-02-01"})
    assert r.status_code == 404 and err(r) == "NOT_FOUND"


@pytest.mark.parametrize("start,due_day", [("0001-01-15", 20), ("9999-12-31", 31), ("9999-12-15", 20)])
def test_extreme_dates_do_not_crash(client, make, start, due_day):
    m = make.member("SA")
    make.plan(f"p{start}", "SA", 1000)
    a = make.agreement(m["id"], f"p{start}", start, due_day)
    y = start[:4]
    assert client.get(f"/agreements/{a['id']}/invoices", params={"from": f"{y}-01-01", "to": f"{y}-12-31"}).status_code == 200
