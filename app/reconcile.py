"""Gateway reconciliation (Part 3)."""
from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from . import validate as v
from .countries import COUNTRIES, CURRENCIES
from .errors import ApiError, validation
from .schedule import Invoice, invoices_between

VERDICTS = ["MATCHED", "DUE_DAY_DRIFT", "DOUBLE_CHARGE_RISK", "MISSING_FROM_LEDGER", "DECLINED"]
AMOUNT_TOLERANCE = 1  # minor units


def parse_request(body: Any) -> tuple[str, tuple[int, int], list[dict]]:
    """Structural validation only (422 VALIDATION)."""
    body = v.obj(body)
    year, month = v.month_field(body, "month")
    rows_raw = body.get("rows")
    if not isinstance(rows_raw, list):
        raise validation("rows must be an array")
    rows = []
    for i, r in enumerate(rows_raw):
        if not isinstance(r, dict):
            raise validation(f"rows[{i}] must be an object")
        try:
            rows.append({
                "gateway_txn_id": v.string(r, "gateway_txn_id"),
                "agreement_id": v.string(r, "agreement_id"),
                "amount": v.integer(r, "amount", min_value=1),
                "currency": v.one_of(r, "currency", CURRENCIES),
                "status": v.one_of(r, "status", ["SETTLED", "DECLINED"]),
                "attempted_on": v.date_field(r, "attempted_on"),
            })
        except ApiError as e:
            raise validation(f"rows[{i}]: {e.message}")
    return body["month"], (year, month), rows


def check_rows(rows: list[dict], year: int, month: int, agreements: dict, plans: dict) -> None:
    """Business validation of the file as a whole (422 INVALID_ROWS)."""
    errors = []
    counts = Counter(r["gateway_txn_id"] for r in rows)
    for r in rows:
        txn = r["gateway_txn_id"]
        if counts[txn] > 1:
            errors.append({"gateway_txn_id": txn, "code": "DUPLICATE_TXN"})
        if (r["attempted_on"].year, r["attempted_on"].month) != (year, month):
            errors.append({"gateway_txn_id": txn, "code": "ROW_OUTSIDE_MONTH"})
        agreement = agreements.get(r["agreement_id"])
        if agreement is not None:
            currency = COUNTRIES[plans[agreement["plan_id"]]["country"]].currency
            if currency != r["currency"]:
                errors.append({"gateway_txn_id": txn, "code": "CURRENCY_MISMATCH"})
    if errors:
        raise ApiError(422, "INVALID_ROWS", f"{len(errors)} row problem(s)", {"errors": errors})


def run(month_str: str, year: int, month: int, rows: list[dict], agreements: dict, plans: dict) -> dict:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])

    expected: dict[str, list[Invoice]] = {
        a_id: invoices_between(a, plans[a["plan_id"]], first, last) for a_id, a in agreements.items()
    }

    # Link each settled row to one invoice. Independent of row order: a row's choice depends only
    # on its own fields, and already-linked invoices still count as candidates.
    links: list = []
    for r in rows:
        if r["status"] != "SETTLED":
            links.append(None)
            continue
        candidates = [i for i in expected.get(r["agreement_id"], [])
                      if abs(i.total - r["amount"]) <= AMOUNT_TOLERANCE]
        links.append(min(candidates, key=lambda i: (i.due_date, i.invoice_no)) if candidates else None)

    linked_count: dict[tuple[str, int], int] = defaultdict(int)
    for inv in links:
        if inv is not None:
            linked_count[(inv.agreement_id, inv.invoice_no)] += 1

    summary = {k: 0 for k in VERDICTS}
    out_rows = []
    for r, inv in zip(rows, links):
        if r["status"] == "DECLINED":
            verdict = "DECLINED"
        elif inv is None:
            verdict = "MISSING_FROM_LEDGER"
        elif linked_count[(inv.agreement_id, inv.invoice_no)] > 1:
            verdict = "DOUBLE_CHARGE_RISK"
        elif r["attempted_on"] == inv.due_date:
            verdict = "MATCHED"
        else:
            verdict = "DUE_DAY_DRIFT"
        summary[verdict] += 1
        out_rows.append({
            "gateway_txn_id": r["gateway_txn_id"],
            "verdict": verdict,
            "invoice": None if inv is None else {"agreement_id": inv.agreement_id, "invoice_no": inv.invoice_no},
        })

    unmatched = sorted(
        (i for invs in expected.values() for i in invs if (i.agreement_id, i.invoice_no) not in linked_count),
        key=lambda i: (i.due_date, i.agreement_id, i.invoice_no),
    )
    return {
        "month": month_str,
        "summary": summary,
        "rows": out_rows,
        "unmatched_invoices": [
            {"agreement_id": i.agreement_id, "invoice_no": i.invoice_no, "due_date": i.due_date.isoformat(),
             "total": i.total, "currency": i.currency}
            for i in unmatched
        ],
    }
