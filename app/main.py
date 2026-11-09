"""HTTP layer. Handlers parse + validate, then do all reads/writes under store.lock."""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import reconcile
from . import validate as v
from .countries import COUNTRIES
from .errors import ApiError, not_found, validation
from .phones import normalize_for_lookup, normalize_for_member
from .schedule import invoices_between
from .store import Store, new_id

MAX_RANGE_DAYS = 366
NAME_MAX = 120


def create_app() -> FastAPI:
    app = FastAPI(title="Gulf invoices")
    store = Store()
    app.state.store = store

    # ---------- error rendering ----------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse(e.body(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _req_validation(_: Request, e: RequestValidationError):
        return JSONResponse(validation(str(e.errors())).body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, e: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR")
        return JSONResponse(ApiError(e.status_code, code, str(e.detail)).body(), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception):
        return JSONResponse(ApiError(500, "INTERNAL", "Internal error").body(), status_code=500)

    async def body_of(request: Request) -> Any:
        raw = await request.body()
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise validation("Body must be valid JSON")

    # ---------- health ----------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ---------- Part 1: members ----------
    def member_json(m: dict) -> dict:
        return {"id": m["id"], "name": m["name"], "country": m["country"], "phone": m["phone"]}

    @app.post("/members", status_code=201)
    async def create_member(request: Request):
        body = v.obj(await body_of(request))
        name = v.string(body, "name", non_empty=False).strip()
        if not 1 <= len(name) <= NAME_MAX:
            raise validation(f"name must be 1 to {NAME_MAX} characters after trimming")
        country = v.one_of(body, "country", COUNTRIES)
        phone_raw = v.string(body, "phone", non_empty=False)
        phone = normalize_for_member(phone_raw, country)
        with store.lock:
            existing = store.member_by_phone.get(phone)
            if existing:
                raise ApiError(409, "PHONE_TAKEN", "Another member already has this phone",
                               {"existing_member_id": existing})
            m = {"id": new_id("mem"), "name": name, "country": country, "phone": phone}
            store.members[m["id"]] = m
            store.member_by_phone[phone] = m["id"]
        return member_json(m)

    @app.get("/members/lookup")
    def lookup_member(phone: Optional[str] = None, country: Optional[str] = None):
        if phone is None:
            raise validation("phone is required")
        if country is not None and country not in COUNTRIES:
            raise validation(f"country must be one of {sorted(COUNTRIES)}")
        e164 = normalize_for_lookup(phone, country)
        with store.lock:
            member_id = store.member_by_phone.get(e164)
            if member_id is None:
                raise not_found("No member has that phone")
            return member_json(store.members[member_id])

    # ---------- Part 2: plans, agreements, invoices ----------
    @app.post("/plans", status_code=201)
    async def create_plan(request: Request):
        body = v.obj(await body_of(request))
        plan_id = v.string(body, "id")
        country = v.one_of(body, "country", COUNTRIES)
        monthly = v.integer(body, "monthly", min_value=1)
        joining_fee = v.integer(body, "joining_fee", min_value=0)
        plan = {"id": plan_id, "country": country, "currency": COUNTRIES[country].currency,
                "monthly": monthly, "joining_fee": joining_fee}
        with store.lock:
            if plan_id in store.plans:
                raise ApiError(409, "PLAN_EXISTS", f"Plan {plan_id} already exists")
            store.plans[plan_id] = plan
        return plan

    def agreement_json(a: dict) -> dict:
        return {"id": a["id"], "member_id": a["member_id"], "plan_id": a["plan_id"],
                "start_date": a["start_date"].isoformat(), "due_day": a["due_day"]}

    @app.post("/agreements", status_code=201)
    async def create_agreement(request: Request):
        body = v.obj(await body_of(request))
        member_id = v.string(body, "member_id", non_empty=False)
        plan_id = v.string(body, "plan_id", non_empty=False)
        start_date = v.date_field(body, "start_date")
        due_day = v.integer(body, "due_day", min_value=1, max_value=31)
        with store.lock:
            member = store.members.get(member_id)
            if member is None:
                raise ApiError(422, "UNKNOWN_MEMBER", f"Unknown member {member_id}")
            plan = store.plans.get(plan_id)
            if plan is None:
                raise ApiError(422, "UNKNOWN_PLAN", f"Unknown plan {plan_id}")
            if plan["country"] != member["country"]:
                raise ApiError(422, "PLAN_COUNTRY_MISMATCH",
                               f"Plan is {plan['country']} but member is {member['country']}")
            a = {"id": new_id("agr"), "member_id": member_id, "plan_id": plan_id,
                 "start_date": start_date, "due_day": due_day}
            store.agreements[a["id"]] = a
        return agreement_json(a)

    @app.get("/agreements/{agreement_id}/invoices")
    def list_invoices(agreement_id: str, request: Request):
        with store.lock:
            a = store.agreements.get(agreement_id)
            if a is None:
                raise not_found(f"Unknown agreement {agreement_id}")
            plan = store.plans[a["plan_id"]]
        q = request.query_params
        frm = v.date_field(dict(q), "from")
        to = v.date_field(dict(q), "to")
        if to < frm or (to - frm).days > MAX_RANGE_DAYS:
            raise ApiError(422, "INVALID_RANGE", f"to must be on/after from and at most {MAX_RANGE_DAYS} days later")
        return [i.to_json() for i in invoices_between(a, plan, frm, to)]

    # ---------- Part 3: reconciliation ----------
    @app.post("/reconciliation/runs", status_code=201)
    async def create_run(request: Request):
        month_str, (year, month), rows = reconcile.parse_request(await body_of(request))
        with store.lock:
            reconcile.check_rows(rows, year, month, store.agreements, store.plans)
            result = {"id": new_id("run"),
                      **reconcile.run(month_str, year, month, rows, store.agreements, store.plans)}
            store.runs[result["id"]] = result
        return result

    @app.get("/reconciliation/runs/{run_id}")
    def get_run(run_id: str):
        with store.lock:
            r = store.runs.get(run_id)
        if r is None:
            raise not_found(f"Unknown run {run_id}")
        return r

    return app


app = create_app()
