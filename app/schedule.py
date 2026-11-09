"""Invoice schedule (Part 2). Pure functions: nothing is stored, everything is computed on request.

All money is integer minor units. Rounding is half-up, done exactly twice per invoice:
once for the prorated amount and once for VAT.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from .countries import COUNTRIES

GREGORIAN_CYCLE_YEARS = 400
GREGORIAN_CYCLE_DAYS = 146097


def round_half_up_div(numerator: int, denominator: int) -> int:
    """round(numerator / denominator) with .5 going up, in exact integer arithmetic (non-negative inputs)."""
    return (2 * numerator + denominator) // (2 * denominator)


def vat_for(net: int, vat_percent: int) -> int:
    return round_half_up_div(net * vat_percent, 100)


def add_months(year: int, month: int, k: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + k
    return idx // 12, idx % 12 + 1


def due_day_in(year: int, month: int, due_day: int) -> int:
    """The anchor stays e.g. 31; only the date clamps to the month's length."""
    return min(due_day, calendar.monthrange(year, month)[1])


def _ordinal(year: int, month: int, day: int) -> int:
    """Day number that also works for year 0 / 10000 (edges of Python's date range)."""
    shift = 0
    while year < 1:
        year += GREGORIAN_CYCLE_YEARS
        shift -= GREGORIAN_CYCLE_DAYS
    while year > 9999:
        year -= GREGORIAN_CYCLE_YEARS
        shift += GREGORIAN_CYCLE_DAYS
    return date(year, month, day).toordinal() + shift


@dataclass(frozen=True)
class Invoice:
    agreement_id: str
    invoice_no: int
    due_date: date
    kind: str  # FIRST | MONTHLY
    proration: Optional[dict[str, int]]
    net: int
    vat: int
    total: int
    currency: str

    def to_json(self) -> dict[str, Any]:
        return {
            "invoice_no": self.invoice_no,
            "due_date": self.due_date.isoformat(),
            "kind": self.kind,
            "proration": self.proration,
            "net": self.net,
            "vat": self.vat,
            "total": self.total,
            "currency": self.currency,
        }


def invoices_between(agreement: dict, plan: dict, frm: date, to: date) -> list[Invoice]:
    """Every invoice of the agreement with frm <= due_date <= to, in schedule order."""
    start: date = agreement["start_date"]
    due_day: int = agreement["due_day"]
    country = COUNTRIES[plan["country"]]
    monthly: int = plan["monthly"]

    def make(no: int, due: date, kind: str, proration: Optional[dict], net: int) -> Invoice:
        vat = vat_for(net, country.vat_percent)
        return Invoice(agreement["id"], no, due, kind, proration, net, vat, net + vat, country.currency)

    # N = first due date strictly after start; P = due date one month before N.
    if due_day_in(start.year, start.month, due_day) > start.day:
        ny, nm = start.year, start.month
    else:
        ny, nm = add_months(start.year, start.month, 1)
    py, pm = add_months(ny, nm, -1)
    n_ord = _ordinal(ny, nm, due_day_in(ny, nm, due_day))
    p_ord = _ordinal(py, pm, due_day_in(py, pm, due_day))
    days, cycle_days = n_ord - start.toordinal(), n_ord - p_ord

    out: list[Invoice] = []
    if frm <= start <= to:
        prorated = round_half_up_div(monthly * days, cycle_days)
        out.append(make(1, start, "FIRST", {"days": days, "cycle_days": cycle_days},
                        prorated + plan["joining_fee"]))

    # Invoice k >= 2 is due in month (N's month + k - 2). Jump straight to the month before `frm`.
    offset = max(0, (frm.year * 12 + frm.month) - (ny * 12 + nm) - 1)
    while True:
        y, m = add_months(ny, nm, offset)
        if y > 9999:
            break
        due = date(y, m, due_day_in(y, m, due_day))
        if due > to:
            break
        if due >= frm:
            out.append(make(offset + 2, due, "MONTHLY", None, monthly))
        offset += 1
    return out
