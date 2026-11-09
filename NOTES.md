# NOTES

## Run

```bash
docker build -t app . && docker run -p 8080:8080 app   # API on :8080, GET /health
docker build --target test .                          # runs pytest
```

Local, without Docker: `python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt`,
then `.venv/bin/pytest` or `.venv/bin/uvicorn app.main:app --port 8080`.

## Layout

| File | What |
|---|---|
| `app/countries.py` | Country table: dial code, currency, VAT %, phone shapes |
| `app/phones.py` | Part 1 phone cleaning / normalisation to E.164 |
| `app/schedule.py` | Part 2 invoice schedule (pure functions, integer money) |
| `app/reconcile.py` | Part 3 validation, matching, verdicts |
| `app/validate.py` | Strict input checks → `422 VALIDATION` |
| `app/store.py` | In-memory dicts + one lock |
| `app/main.py` | FastAPI routes and error rendering |

## Design

- Python 3.12 + FastAPI, one uvicorn worker, state in memory. Every check-then-write runs under one
  `threading.Lock`, so `PHONE_TAKEN` and `PLAN_EXISTS` hold under concurrent requests.
- Phones are stored as E.164 only; lookups normalise the query the same way, so every spelling hits one key.
- Money is never a float: proration is `(2·monthly·days + cycle) // (2·cycle)` (round half up, exact), VAT
  is `(2·net·pct + 100) // 200`.
- Invoices are computed on request; the range query jumps straight to the right month rather than walking
  from the start date.
- Reconciliation links each settled row to its own earliest candidate independently of other rows, then counts
  links per invoice. That is what makes the result independent of row order.

## Skipped

- Persistence (spec says each run starts empty), auth, pagination, list endpoints (`GET /members`, `GET /plans`).

## Assumptions

- JSON numbers must be real integers: `1.0`, `"1"` and `true` are `422 VALIDATION` for integer fields.
- A body that is not valid JSON or not an object is `422 VALIDATION`.
- When a request has several problems, structural `VALIDATION` errors win over business errors (`INVALID_PHONE`, `INVALID_ROWS`, `UNKNOWN_*`).
- `name` that is not a string is `VALIDATION`; a string that is empty after trimming is also `VALIDATION`.
- `phone` must be a JSON string (else `VALIDATION`); an empty or all-space phone is `INVALID_PHONE`.
- Only space, `-`, `(`, `)` are stripped; anything else (dots, slashes, letters) is `INVALID_PHONE`.
- `+` followed by a national number (e.g. `+0551234567`) is `INVALID_PHONE`; a `+` form must carry a dial code.
- `+966 05...` (trunk zero after the dial code) is `INVALID_PHONE`.
- Lookup: `country` must be AE/SA/BH if given (else `VALIDATION`); a national number that fits some country but not the given one is `INVALID_PHONE`.
- Lookup: a national number with no country is `PHONE_NEEDS_COUNTRY` (checked before the number is looked up).
- `country` codes are case-sensitive (`sa` is `VALIDATION`).
- Plan `id` is any non-empty string, used exactly as given (no trimming); case-sensitive.
- `member_id` / `plan_id` that are strings but unknown are `UNKNOWN_MEMBER` / `UNKNOWN_PLAN`; member is checked before plan.
- On `GET /agreements/{id}/invoices`, an unknown agreement is `404` even if `from`/`to` are also bad.
- `to − from` of exactly 366 days is allowed; 367 is `INVALID_RANGE`.
- Dates are strictly `YYYY-MM-DD` (no `20260101`, no time part); months strictly `YYYY-MM`.
- Invoices whose due date would fall after 9999-12-31 are not produced.
- Reconciliation `currency` must be AED, SAR or BHD (else `VALIDATION`); `status` must be SETTLED or DECLINED.
- `gateway_txn_id` and `agreement_id` must be strings; an empty `gateway_txn_id` is `VALIDATION`.
- `rows: []` is valid and lists every expected invoice as unmatched.
- `DUPLICATE_TXN` is reported once per occurring row (two rows with the same id → two entries).
- `CURRENCY_MISMATCH` is checked for DECLINED rows too.
- Expected invoices include every agreement in the store, not only those referenced by rows.
- A run's result is frozen when created; later agreements do not change `GET /reconciliation/runs/{id}`.
- Unknown routes return `404 NOT_FOUND` in the standard error shape; unexpected exceptions return `500 INTERNAL`.
