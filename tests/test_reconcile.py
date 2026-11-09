import random

import pytest

from tests.conftest import err


@pytest.fixture
def world(client, make):
    """SA agreement due on the 1st (Oct invoice #2 = 34385) and a BH one (Oct invoice #2 = 29645)."""
    make.plan("sa", "SA", 29900)
    make.plan("bh", "BH", 26950)
    sa = make.agreement(make.member("SA")["id"], "sa", "2026-09-20", 1)
    bh = make.agreement(make.member("BH")["id"], "bh", "2026-09-01", 1)
    return {"sa": sa["id"], "bh": bh["id"]}


def row(txn, agreement_id, amount, currency, attempted_on, status="SETTLED"):
    return {"gateway_txn_id": txn, "agreement_id": agreement_id, "amount": amount,
            "currency": currency, "status": status, "attempted_on": attempted_on}


def post_run(client, rows, month="2026-10"):
    return client.post("/reconciliation/runs", json={"month": month, "rows": rows})


def test_spec_example(client, world):
    r = post_run(client, [row("T-88121", world["sa"], 34385, "SAR", "2026-10-01"),
                          row("T-88122", world["bh"], 29645, "BHD", "2026-10-02", "DECLINED")])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["summary"] == {"MATCHED": 1, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                               "MISSING_FROM_LEDGER": 0, "DECLINED": 1}
    assert body["rows"] == [
        {"gateway_txn_id": "T-88121", "verdict": "MATCHED", "invoice": {"agreement_id": world["sa"], "invoice_no": 2}},
        {"gateway_txn_id": "T-88122", "verdict": "DECLINED", "invoice": None},
    ]
    assert body["unmatched_invoices"] == [
        {"agreement_id": world["bh"], "invoice_no": 2, "due_date": "2026-10-01", "total": 29645, "currency": "BHD"}]
    got = client.get(f"/reconciliation/runs/{body['id']}")
    assert got.status_code == 200 and got.json() == body


def test_verdicts(client, world):
    rows = [
        row("drift", world["sa"], 34386, "SAR", "2026-10-03"),   # within 1 minor unit, other day
        row("missing-amt", world["bh"], 1, "BHD", "2026-10-01"),
        row("missing-agr", "ghost", 34385, "SAR", "2026-10-01"),
    ]
    body = post_run(client, rows).json()
    assert [x["verdict"] for x in body["rows"]] == ["DUE_DAY_DRIFT", "MISSING_FROM_LEDGER", "MISSING_FROM_LEDGER"]
    assert body["rows"][1]["invoice"] is None
    assert body["summary"]["DUE_DAY_DRIFT"] == 1 and body["summary"]["MISSING_FROM_LEDGER"] == 2
    assert [u["agreement_id"] for u in body["unmatched_invoices"]] == [world["bh"]]


def test_tolerance_is_one_minor_unit(client, world):
    body = post_run(client, [row("a", world["sa"], 34383, "SAR", "2026-10-01")]).json()
    assert body["rows"][0]["verdict"] == "MISSING_FROM_LEDGER"


def test_double_charge_all_rows_flagged(client, world):
    rows = [row("a", world["sa"], 34385, "SAR", "2026-10-01"),
            row("b", world["sa"], 34384, "SAR", "2026-10-05"),
            row("c", world["sa"], 34385, "SAR", "2026-10-01", "DECLINED")]
    body = post_run(client, rows).json()
    assert [x["verdict"] for x in body["rows"]] == ["DOUBLE_CHARGE_RISK", "DOUBLE_CHARGE_RISK", "DECLINED"]
    assert all(x["invoice"] == {"agreement_id": world["sa"], "invoice_no": 2} for x in body["rows"][:2])


def test_earliest_due_date_wins(client, make):
    # Start 1 Oct, due day 31: N = 31 Oct, P = 30 Sep -> 30/31 -> 24097 prorated. A joining fee of 803
    # brings FIRST (1 Oct) to 24900 net, the same total (26145) as #2 on 31 Oct.
    make.plan("ae", "AE", 24900, 803)
    a = make.agreement(make.member("AE")["id"], "ae", "2026-10-01", 31)
    body = post_run(client, [row("x", a["id"], 26145, "AED", "2026-10-31")]).json()
    assert body["rows"][0]["invoice"] == {"agreement_id": a["id"], "invoice_no": 1}
    assert body["rows"][0]["verdict"] == "DUE_DAY_DRIFT"
    assert [u["invoice_no"] for u in body["unmatched_invoices"]] == [2]
    # A second payment also links to #1 (already-linked invoices still count) -> both at risk.
    body = post_run(client, [row("x", a["id"], 26145, "AED", "2026-10-31"),
                             row("y", a["id"], 26145, "AED", "2026-10-01")]).json()
    assert [x["verdict"] for x in body["rows"]] == ["DOUBLE_CHARGE_RISK", "DOUBLE_CHARGE_RISK"]


def test_unmatched_sort_order(client, make):
    make.plan("ae", "AE", 24900, 0)
    ids = [make.agreement(make.member("AE")["id"], "ae", "2026-10-05", 20)["id"] for _ in range(3)]
    keys = [(u["due_date"], u["agreement_id"], u["invoice_no"]) for u in post_run(client, []).json()["unmatched_invoices"]]
    assert keys == sorted(keys) and len(keys) == 6
    assert [k[0] for k in keys] == ["2026-10-05"] * 3 + ["2026-10-20"] * 3


def test_order_independent(client, world, make):
    rows = [row("a", world["sa"], 34385, "SAR", "2026-10-01"),
            row("b", world["sa"], 34385, "SAR", "2026-10-02"),
            row("c", world["bh"], 29645, "BHD", "2026-10-09"),
            row("d", world["bh"], 29645, "BHD", "2026-10-01", "DECLINED"),
            row("e", "ghost", 5, "AED", "2026-10-31")]
    base = post_run(client, rows).json()
    by_txn = {x["gateway_txn_id"]: x for x in base["rows"]}
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        body = post_run(client, shuffled).json()
        assert [x["gateway_txn_id"] for x in body["rows"]] == [x["gateway_txn_id"] for x in shuffled]
        assert {x["gateway_txn_id"]: x for x in body["rows"]} == by_txn
        assert body["summary"] == base["summary"] and body["unmatched_invoices"] == base["unmatched_invoices"]


def test_invalid_rows(client, world):
    rows = [row("dup", world["sa"], 34385, "SAR", "2026-10-01"),
            row("dup", world["sa"], 34385, "SAR", "2026-11-01"),
            row("cur", world["sa"], 34385, "BHD", "2026-10-01", "DECLINED"),
            row("ghost-ok", "ghost", 1, "AED", "2026-10-01")]
    r = post_run(client, rows)
    assert r.status_code == 422 and err(r) == "INVALID_ROWS"
    got = sorted((e["gateway_txn_id"], e["code"]) for e in r.json()["error"]["errors"])
    assert got == sorted([("dup", "DUPLICATE_TXN"), ("dup", "DUPLICATE_TXN"),
                          ("dup", "ROW_OUTSIDE_MONTH"), ("cur", "CURRENCY_MISMATCH")])


@pytest.mark.parametrize("body", [
    {"month": "2026-13", "rows": []},
    {"month": "2026-10-01", "rows": []},
    {"month": "2026-10"},
    {"month": "2026-10", "rows": [{"gateway_txn_id": "a"}]},
    {"month": "2026-10", "rows": [row("a", "x", 0, "SAR", "2026-10-01")]},
    {"month": "2026-10", "rows": [row("a", "x", 1.0, "SAR", "2026-10-01")]},
    {"month": "2026-10", "rows": [row("a", "x", 1, "SAR", "2026-10-01", "PENDING")]},
    {"month": "2026-10", "rows": [row("a", "x", 1, "SAR", "2026-10-32")]},
    {"month": "2026-10", "rows": ["nope"]},
])
def test_run_validation(client, body):
    r = client.post("/reconciliation/runs", json=body)
    assert r.status_code == 422 and err(r) == "VALIDATION", r.text


def test_empty_rows_lists_all_expected(client, world):
    body = post_run(client, []).json()
    assert body["summary"] == {k: 0 for k in body["summary"]} and len(body["summary"]) == 5
    assert len(body["unmatched_invoices"]) == 2


def test_unknown_run(client):
    r = client.get("/reconciliation/runs/nope")
    assert r.status_code == 404 and err(r) == "NOT_FOUND"
