# PROMPTS

Full AI conversation used to build this project: Claude Code (Claude Opus 5.5) in the Claude desktop app.

Exported from the app and converted to Markdown. Kept: every message I sent and every reply. Tool calls (files written, commands run) are shown as one-line notes; tool output, the model's hidden reasoning and the app's internal system text are left out.


---

## Me

Can you help me complete the iterview task here, and help me understand what they are asking and help build the project for it?



<details><summary>Pasted: the task brief</summary>

Build a small HTTP API that generates gym membership invoices across the Gulf and reconciles them against what the card gateway collected.

Use any language, any framework and any AI assistant you like. An assistant will write most of this quickly. What we measure is whether the result is exactly right, and in the interview, whether you can change it.
How this works
	
Attempts 	One application per email address, so submit when you are done. A container that fails to build or start gets one 48-hour retry (see Contract).
Scoring 	Automated. We build your container and replay a few hundred requests you have not seen. Each part is scored on its own.
Repo 	Repo size limit is 200 MB. Ensure you're using main branch for your repo - we'll check only this branch
Next step 	If Parts 1 and 2 pass our bar, a 45-minute interview on your own laptop with your own AI tools. You will add a feature to this code while we watch, then we re-run our checks.

In the repo root:

    NOTES.md: how to run it, what you skipped, and one line per assumption.
    PROMPTS.md: your AI conversations, exported or pasted. We read them; heavy AI use is expected and fine.

Contract

If this does not hold, nothing else can be scored. If your container fails to build or start, you will see that fix required by checking ticket status, and you get 48 hours to push a fix to the same branch.

    A Dockerfile at the repo root. We run docker build -t app . and docker run -p 8080:8080 app. The API listens on 0.0.0.0:8080, and GET /health returns 200 within 60 seconds of start.
    The same Dockerfile has a stage named test that runs your tests: docker build --target test . must succeed.
    No network at runtime. Keep state in memory or in an embedded store such as SQLite. Each run starts empty.
    JSON in and out. Dates are YYYY-MM-DD with no time or timezone.
    Money is always an integer in minor units (fils, halalas). Every invoice carries its currency.
    IDs you generate are unique strings in any format.
    Errors always look like {"error": {"code": "...", "message": "..."}}.
        Malformed input (a missing field, a wrong type, an unparseable date, a value outside its allowed range) is 422 VALIDATION.
        An unknown id in the URL is 404 NOT_FOUND.
        Business errors use the status and code given in each part.
    Requests can arrive concurrently. Every rule that says something "may not" happen must still hold when two requests race.

Countries
Country 	Code 	Dial 	Currency 	Minor units 	VAT 	National mobile 	E.164 mobile
United Arab Emirates 	AE 	971 	AED 	100 fils = 1 AED 	5% 	05X XXX XXXX 	+9715XXXXXXXX
Saudi Arabia 	SA 	966 	SAR 	100 halalas = 1 SAR 	15% 	05X XXX XXXX 	+9665XXXXXXXX
Bahrain 	BH 	973 	BHD 	1000 fils = 1 BHD 	10% 	3XXX XXXX 	+9733XXXXXXX

UAE and Saudi national mobiles are 10 digits starting 05. Bahrain national mobiles are 8 digits starting 3, with no trunk zero. Nothing else is a valid phone.
Part 1. Members and phones

Our member table stores the same phone as +966551234567, 966551234567 or 0551234567, depending on which app wrote it, so exact-match lookups miss people. Fix that at the boundary.

POST /members
{ "name": "Noura Al Harbi", "country": "SA", "phone": "055 123 4567" }
→ 201 { "id": "…", "name": "Noura Al Harbi", "country": "SA", "phone": "+966551234567" }

GET /members/lookup?phone=966551234567
GET /members/lookup?phone=%2B966551234567
GET /members/lookup?phone=055%20123%204567&country=SA
→ 200 the same member each time. 404 NOT_FOUND if nobody has that number.

name is trimmed, then must be 1 to 120 characters, and is returned trimmed. country is AE, SA or BH.

    Clean. Remove spaces, hyphens and round brackets. If anything other than digits and one leading + remains, it is 422 INVALID_PHONE.
    Three spellings. What remains must be + then dial code then mobile, or dial code then mobile without the +, or a national mobile. A 00 prefix, a landline, a wrong length, or anything else is 422 INVALID_PHONE.
    National numbers need a country.
        On POST /members, a national number is read in the member's own country and must fit that country's shape.
        On lookup, a number that fits any country's national shape with no country parameter is 422 PHONE_NEEDS_COUNTRY. With a country, it must fit that country's shape.
    International numbers.
        On lookup, a country parameter that disagrees with the dial code is 422 PHONE_COUNTRY_MISMATCH.
        On POST /members, the number may be from any of the three countries, since members carry foreign SIMs.
    One member per phone. Two members may not share a phone in any spelling. The second write gets 409 PHONE_TAKEN, with existing_member_id inside error. This must hold when both writes arrive at the same moment.

Part 2. Plans and the invoice schedule

We create plans through the API; do not seed any.

POST /plans
{ "id": "anytime-sa", "country": "SA", "monthly": 29900, "joining_fee": 0 }
→ 201 { "id": "anytime-sa", "country": "SA", "currency": "SAR", "monthly": 29900, "joining_fee": 0 }

id is chosen by the caller, and a duplicate is 409 PLAN_EXISTS. monthly is an integer above 0 and joining_fee is an integer of 0 or more, both before VAT, in minor units. Currency and VAT rate come from the country.

POST /agreements
{ "member_id": "…", "plan_id": "anytime-sa", "start_date": "2026-09-20", "due_day": 1 }
→ 201 { "id": "…", "member_id": "…", "plan_id": "anytime-sa", "start_date": "2026-09-20", "due_day": 1 }

    due_day is 1 to 31. A member may hold several agreements.
    An unknown member is 422 UNKNOWN_MEMBER, and an unknown plan is 422 UNKNOWN_PLAN.
    A plan from a different country than the member is 422 PLAN_COUNTRY_MISMATCH.

GET /agreements/{id}/invoices?from=2026-09-01&to=2026-12-31
→ 200 [
  { "invoice_no": 1, "due_date": "2026-09-20", "kind": "FIRST",
    "proration": { "days": 11, "cycle_days": 30 },
    "net": 10963, "vat": 1644, "total": 12607, "currency": "SAR" },
  { "invoice_no": 2, "due_date": "2026-10-01", "kind": "MONTHLY", "proration": null,
    "net": 29900, "vat": 4485, "total": 34385, "currency": "SAR" },
  …
]

    Agreements never end. Invoices are computed on request, so there is nothing to store.
    from and to are required and inclusive, and filter on due_date.
    to before from, or more than 366 days after it, is 422 INVALID_RANGE.
    invoice_no is the invoice's position in the agreement's whole schedule. It does not restart inside the range.

Rules

    Due dates. An agreement's due date in a month is min(due_day, days in that month). Due on the 31st means 30 April, 28 February (29th in a leap year) and 31 March. The anchor stays 31; only the date clamps.

    First invoice. Invoice 1 has kind FIRST and is due on the start date. Let N be the first due date strictly after the start date, and P the due date one month before N.
        Its net is monthly × (N − start) / (N − P), rounded, plus joining_fee.
        Its proration is {days: N − start, cycle_days: N − P}.
        A start date that is itself a due date gives days = cycle_days, which is the full price.

    Later invoices. Invoice 2 has kind MONTHLY, the full monthly price, and is due on N. Invoice 3 is due on the next month's due date, and so on. proration is null.

    Rounding. Round half up to a whole minor unit, exactly twice per invoice and never in between:
        once for the prorated amount;
        once for vat = net × VAT rate.

    total = net + vat. The joining fee sits inside the VAT base.

    Minor units only. Never round in major units. A BHD VAT of 579 fils is 0.579 BHD; rounding it to 0.58 is wrong.

Worked examples.

    Start 20 Sep 2026, due day 1, SA plan above. N = 1 Oct and P = 1 Sep, so 11/30.
        29900 × 11 / 30 = 10963.33, which rounds to a net of 10963.
        VAT is 1644.45, which rounds to 1644. The total is 12607.
    Start 5 Sep 2026, due day 20, AE plan with monthly 24900 and joining fee 9900. N = 20 Sep and P = 20 Aug, so 15/31.
        24900 × 15 / 31 = 12048.39, which rounds to 12048. Adding the joining fee gives a net of 21948.
        VAT is 1097.4, which rounds to 1097. The total is 23045.
        Invoice 2 is due 20 Sep, so September has two invoices.

Part 3. Reconciling the gateway file

Take one month of gateway rows, compare them with the invoices the schedule expects that month, and give each row a verdict.

POST /reconciliation/runs
{ "month": "2026-10",
  "rows": [
    { "gateway_txn_id": "T-88121", "agreement_id": "…", "amount": 34385,
      "currency": "SAR", "status": "SETTLED", "attempted_on": "2026-10-01" },
    { "gateway_txn_id": "T-88122", "agreement_id": "…", "amount": 26950,
      "currency": "BHD", "status": "DECLINED", "attempted_on": "2026-10-02" } ] }
→ 201 { "id": "…", "month": "2026-10",
        "summary": { "MATCHED": 1, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                     "MISSING_FROM_LEDGER": 0, "DECLINED": 1 },
        "rows": [ { "gateway_txn_id": "T-88121", "verdict": "MATCHED",
                    "invoice": { "agreement_id": "…", "invoice_no": 2 } },
                  { "gateway_txn_id": "T-88122", "verdict": "DECLINED", "invoice": null } ],
        "unmatched_invoices": [ { "agreement_id": "…", "invoice_no": 2,
                                  "due_date": "2026-10-01", "total": 26950, "currency": "BHD" } ] }

GET /reconciliation/runs/{id} → 200 the same body

Rows

    amount is a positive integer in minor units and is compared with the invoice total, VAT included.
    status is SETTLED or DECLINED.
    agreement_id is always present but may not exist in your store.

Validation

The whole request fails with 422 INVALID_ROWS when any row breaks one of these rules. Add "errors": [{"gateway_txn_id": "…", "code": "…"}] inside error, with one entry per offending row and code, in any order.

    DUPLICATE_TXN: added for every row whose gateway_txn_id appears more than once.
    ROW_OUTSIDE_MONTH: attempted_on is not in month.
    CURRENCY_MISMATCH: the row's agreement exists and its plan's currency differs from the row's. Rows with an unknown agreement skip this check.

Matching

    Expected invoices are every invoice, from every agreement, whose due_date falls in month.
    Only SETTLED rows are matched. A row's candidates are its agreement's expected invoices whose total is within 1 minor unit of amount.
    Picking a candidate. With several candidates, take the earliest due date. Invoices already linked to another row still count.
    No candidate. An unknown agreement, or no candidate, makes the row MISSING_FROM_LEDGER.
    Order. The result must not depend on the order of rows in the request.

Verdict 	When
MATCHED 	The only settled row linked to its invoice, and attempted_on equals the invoice's due_date.
DUE_DAY_DRIFT 	The only settled row linked to its invoice, and attempted_on is a different day.
DOUBLE_CHARGE_RISK 	Two or more settled rows are linked to the same invoice. Every one of them gets this verdict.
MISSING_FROM_LEDGER 	No candidate, as above.
DECLINED 	The row's status is DECLINED. It takes no part in matching.
Response

    summary has a key for every verdict, including zeros.
    rows come back in request order, with invoice set to {agreement_id, invoice_no} or null.
    unmatched_invoices lists expected invoices that no settled row is linked to. Sort by due_date, then agreement_id, then invoice_no. An invoice whose only rows were declined belongs here.
    A run is stored and can be read back by id. It never changes members or agreements.

</details>



---

## Claude

I'll start by checking which tools this machine has, then build it.

> 🔧 Ran: Check Python, Docker and FastAPI availability

Docker works, so I'll build in Python with FastAPI and run the tests inside the container. First, the phone rules:

> 🔧 Ran: Create project folders and a local virtualenv

> 🔧 Write `app/countries.py`

> 🔧 Write `app/errors.py`

> 🔧 Write `app/phones.py`

Next, input validation helpers and the invoice schedule:

> 🔧 Write `app/validate.py`

> 🔧 Write `app/schedule.py`

Now reconciliation, the in-memory store and the HTTP routes:

> 🔧 Write `app/reconcile.py`

> 🔧 Write `app/store.py`

> 🔧 Write `app/main.py`

Now the tests, covering the spec's worked examples and the edge cases:

> 🔧 Write `tests/conftest.py`

> 🔧 Write `tests/test_members.py`

> 🔧 Write `tests/test_schedule.py`

> 🔧 Write `tests/test_reconcile.py`

A couple of test cases I wrote don't actually exercise the rule they're named for. Fixing those:

> 🔧 Edit `tests/test_reconcile.py`

> 🔧 Edit `tests/test_reconcile.py`

> 🔧 Ran: Run the test suite locally

71 of 73 passed. The range failure is a counting mistake in my test (12 invoices is correct). The other one needs a closer look:

> 🔧 Ran: Print October invoices for the failing case

The code is right and my test was wrong: 30 Sep to 31 Oct is a 31-day cycle. I'll add a joining fee so the first invoice comes to exactly one month's price:

> 🔧 Ran: Fix the two test expectations and rerun tests

All 73 tests pass. Next, the Dockerfile and docs:

> 🔧 Ran: Write requirements, ignore files and Dockerfile

> 🔧 Write `NOTES.md`

> 🔧 Ran: Write PROMPTS.md and build the Docker test stage

The test stage builds. Now the runtime image, plus a smoke test against the running container:

> 🔧 Ran: Build runtime image, run it, and call every endpoint

The project is built. All 73 tests pass, both Docker builds the brief asks for succeed, and I ran the running container through every endpoint. It returned the brief's example numbers exactly: 10963 / 1644 / 12607, then 34385, and the reconciliation row came back MATCHED.

### What they're asking for

It's a small backend for gym billing across three countries, in three parts:

1. **Members and phones.** Each country writes the same phone number in different ways. You clean every number into one standard form (`+966551234567`) when it comes in, so a lookup finds the member however the number is typed. Two members can never share a number, even when both requests arrive at the same moment.
2. **Plans and invoices.** A member signs an agreement on a plan. You calculate their invoices when asked, and nothing is stored. The first invoice only charges for the days until the first payment date. Money is always whole fils or halalas, rounded at exactly two points per invoice, and dates like the 31st move back to 30 April or 28 February.
3. **Reconciliation.** You take a month of card-gateway payments and match each one to the invoice it was meant to pay. Each payment gets a verdict: matched, paid on the wrong day, paid twice, no matching invoice, or declined. You also list the invoices nobody paid.

They grade automatically with a few hundred hidden requests, so edge cases decide your score. In the 45-minute interview you'll add a feature while they watch, so the code is split so each rule lives in one obvious place.

### What's in the folder

| File | What it does |
|---|---|
| [app/countries.py](app/countries.py) | Country table: dial codes, currencies, VAT rates, phone formats |
| [app/phones.py](app/phones.py) | Part 1: cleaning phone numbers |
| [app/schedule.py](app/schedule.py) | Part 2: invoice dates and amounts, using whole numbers only |
| [app/reconcile.py](app/reconcile.py) | Part 3: checking the rows and matching payments to invoices |
| [app/main.py](app/main.py) | The API routes and error responses |
| [tests/](tests/) | 73 tests, including every worked example in the brief |
| [Dockerfile](Dockerfile), [NOTES.md](NOTES.md), [PROMPTS.md](PROMPTS.md) | What the brief asks for at the repo root |

It's Python with FastAPI. Everything is kept in memory, and one lock covers every check-then-save, which is how the "may not" rules hold when requests race.

### Before you submit

- **Read the Assumptions list in [NOTES.md](NOTES.md).** The brief is unclear in places. For example, I chose to reject a gateway currency like `USD` as invalid input, and to reject `1.0` where a whole number is required. Change any choice you disagree with; each one is a line or two of code.
- **Fill in PROMPTS.md.** Export this conversation from the app and paste it in. They expect heavy AI use.
- **Push it yourself.** It goes to the `main` branch of your repo; nothing is committed yet.
- **Read [app/schedule.py](app/schedule.py) and [app/reconcile.py](app/reconcile.py) closely.** The interview tests whether you can change this code, so you'll need to explain two things: how the first payment date and its prorated share are worked out, and why the matching result doesn't depend on the order of the rows.

If you want to keep this work, I can move this session to a folder you choose.


---

## Me

please push it to this folder, but can I get an understanding, of what this small test task might be trying to guage out of me, and hoe exactly am I supposed to test this personally if everything is working fine


---

## Claude

> 🔧 Write `scripts/try-it.sh`

I left a muddled heading in the reconciliation step. Fixing it, then running the script against a fresh container:

> 🔧 Edit `scripts/try-it.sh`

> 🔧 Ran: Rebuild image and run the walkthrough script against it

Every step printed what it expected. Now pick the folder you want the project in:

> 🔧 request_directory

You picked Desktop/Personal, which may already hold other things, so I'll put the project in its own new folder there called `gulf-invoices-api`:

> 🔧 Ran: Create the project folder inside Personal

> 🔧 change_directory

The project is moving to a new folder, **Desktop/Personal/gulf-invoices-api**. The app copies the files over when this turn ends, and it will tell you what it copied. "Push" there just means files on your Mac. Nothing is in git or on GitHub yet; you'll do that when you submit.

### What this task is testing

The brief says it outright: an AI can write this code quickly, so the code itself isn't what they're grading. They're looking for three things.

1. **Getting every detail exactly right.** The grader sends a few hundred hidden requests, and a result that's off by one fils counts as wrong. The rules are full of small traps that check whether you, or your AI, read the brief closely:
   - rounding exactly twice per invoice, never in between
   - the 31st becoming 28 February
   - Bahrain having 1000 fils to the dinar
   - `00966…` being an invalid phone number
   - "strictly after" in the first-invoice rule
   - "invoices already linked still count" in the matching rule

   This is how payments work in real life: an invoice that's slightly wrong is wrong.
2. **Thinking about problems real systems hit.** One-member-per-phone has to hold when two requests arrive at the same moment, and the reconciliation result can't depend on the order of the rows. Those are the bugs that cause double charges in production, and they're asking whether you thought about them.
3. **Owning code that AI wrote.** This is the interview. You add a feature live while they watch, then they re-run their checks. If the AI did all the work and you don't understand it, it shows quickly. They expect heavy AI use; what they're checking is whether you can steer it and spot when it's wrong. You saw an example earlier: the code was right, two of my first test expectations were wrong, and I had to work out which side had the bug.

So, to prepare, make sure you can explain in your own words:
- how the first invoice's days and cycle length (N and P) are worked out
- why matching ignores row order
- where the lock is and why it's needed
- what each assumption in NOTES.md means

### How to test it yourself

**1. The automated tests.** This is the same command the graders run:
```bash
docker build --target test .
```
If it finishes without errors, all 73 tests passed.

**2. Use the API by hand.** Run the server in one terminal:
```bash
docker build -t app . && docker run -p 8080:8080 app
```
Then run this in a second terminal:
```bash
./scripts/try-it.sh
```
It walks through every endpoint, and each step's heading says what you should see. I just ran it on a fresh container and every step matched: the 10963 / 1644 / 12607 first invoice, each error code, the double-charge case, and 10 simultaneous sign-ups with the same phone ending as one 201 and nine 409s.

**3. Try to break it.** This is the best practice for the interview. Pick a rule in the brief, guess what should happen, and check it with `curl`. For example, start an agreement on 31 January with due day 31, or send a gateway row for an agreement that doesn't exist. If the response surprises you, either you've found a bug or you've found a rule you can now explain. Either way, it's exactly what they'll probe.

### Before you submit

- **Put it on GitHub.** Create a repo, push this folder to its `main` branch, and leave out `.venv` (the `.gitignore` already does).
- **Fill in PROMPTS.md.** Export this conversation and paste it in.
- **Read the Assumptions list in NOTES.md** and change anything you'd decide differently.


---

## Me

Also here is the the whole interview page description:



<details><summary>Pasted: the full application page (same brief plus the form)</summary>

Language
Job offer: full stack developer
Website
How to apply

To apply, complete a short test task (brief below) and record a video explaining your code and how you used your tools.

    It's for evaluation only. The task isn't connected to any production system, and your code won't be used for anything else.
    Use any tools you like. We value your time, so use whatever LLM, coding assistant or other tool you want. There are no limits.
    It's small. In our own testing, the task took 14 minutes to write and the video another 5 to record.

Full name
Email *
Phone *
Currently based in the UAE *
Yes
No
Need visa sponsorship *
Yes
No
Notice period *
Expected salary *
Test task brief

Build a small HTTP API that generates gym membership invoices across the Gulf and reconciles them against what the card gateway collected.

Use any language, any framework and any AI assistant you like. An assistant will write most of this quickly. What we measure is whether the result is exactly right, and in the interview, whether you can change it.
How this works
	
Attempts 	One application per email address, so submit when you are done. A container that fails to build or start gets one 48-hour retry (see Contract).
Scoring 	Automated. We build your container and replay a few hundred requests you have not seen. Each part is scored on its own.
Repo 	Repo size limit is 200 MB. Ensure you're using main branch for your repo - we'll check only this branch
Next step 	If Parts 1 and 2 pass our bar, a 45-minute interview on your own laptop with your own AI tools. You will add a feature to this code while we watch, then we re-run our checks.

In the repo root:

    NOTES.md: how to run it, what you skipped, and one line per assumption.
    PROMPTS.md: your AI conversations, exported or pasted. We read them; heavy AI use is expected and fine.

Contract

If this does not hold, nothing else can be scored. If your container fails to build or start, you will see that fix required by checking ticket status, and you get 48 hours to push a fix to the same branch.

    A Dockerfile at the repo root. We run docker build -t app . and docker run -p 8080:8080 app. The API listens on 0.0.0.0:8080, and GET /health returns 200 within 60 seconds of start.
    The same Dockerfile has a stage named test that runs your tests: docker build --target test . must succeed.
    No network at runtime. Keep state in memory or in an embedded store such as SQLite. Each run starts empty.
    JSON in and out. Dates are YYYY-MM-DD with no time or timezone.
    Money is always an integer in minor units (fils, halalas). Every invoice carries its currency.
    IDs you generate are unique strings in any format.
    Errors always look like {"error": {"code": "...", "message": "..."}}.
        Malformed input (a missing field, a wrong type, an unparseable date, a value outside its allowed range) is 422 VALIDATION.
        An unknown id in the URL is 404 NOT_FOUND.
        Business errors use the status and code given in each part.
    Requests can arrive concurrently. Every rule that says something "may not" happen must still hold when two requests race.

Countries
Country 	Code 	Dial 	Currency 	Minor units 	VAT 	National mobile 	E.164 mobile
United Arab Emirates 	AE 	971 	AED 	100 fils = 1 AED 	5% 	05X XXX XXXX 	+9715XXXXXXXX
Saudi Arabia 	SA 	966 	SAR 	100 halalas = 1 SAR 	15% 	05X XXX XXXX 	+9665XXXXXXXX
Bahrain 	BH 	973 	BHD 	1000 fils = 1 BHD 	10% 	3XXX XXXX 	+9733XXXXXXX

UAE and Saudi national mobiles are 10 digits starting 05. Bahrain national mobiles are 8 digits starting 3, with no trunk zero. Nothing else is a valid phone.
Part 1. Members and phones

Our member table stores the same phone as +966551234567, 966551234567 or 0551234567, depending on which app wrote it, so exact-match lookups miss people. Fix that at the boundary.

POST /members
{ "name": "Noura Al Harbi", "country": "SA", "phone": "055 123 4567" }
→ 201 { "id": "…", "name": "Noura Al Harbi", "country": "SA", "phone": "+966551234567" }

GET /members/lookup?phone=966551234567
GET /members/lookup?phone=%2B966551234567
GET /members/lookup?phone=055%20123%204567&country=SA
→ 200 the same member each time. 404 NOT_FOUND if nobody has that number.

name is trimmed, then must be 1 to 120 characters, and is returned trimmed. country is AE, SA or BH.

    Clean. Remove spaces, hyphens and round brackets. If anything other than digits and one leading + remains, it is 422 INVALID_PHONE.
    Three spellings. What remains must be + then dial code then mobile, or dial code then mobile without the +, or a national mobile. A 00 prefix, a landline, a wrong length, or anything else is 422 INVALID_PHONE.
    National numbers need a country.
        On POST /members, a national number is read in the member's own country and must fit that country's shape.
        On lookup, a number that fits any country's national shape with no country parameter is 422 PHONE_NEEDS_COUNTRY. With a country, it must fit that country's shape.
    International numbers.
        On lookup, a country parameter that disagrees with the dial code is 422 PHONE_COUNTRY_MISMATCH.
        On POST /members, the number may be from any of the three countries, since members carry foreign SIMs.
    One member per phone. Two members may not share a phone in any spelling. The second write gets 409 PHONE_TAKEN, with existing_member_id inside error. This must hold when both writes arrive at the same moment.

Part 2. Plans and the invoice schedule

We create plans through the API; do not seed any.

POST /plans
{ "id": "anytime-sa", "country": "SA", "monthly": 29900, "joining_fee": 0 }
→ 201 { "id": "anytime-sa", "country": "SA", "currency": "SAR", "monthly": 29900, "joining_fee": 0 }

id is chosen by the caller, and a duplicate is 409 PLAN_EXISTS. monthly is an integer above 0 and joining_fee is an integer of 0 or more, both before VAT, in minor units. Currency and VAT rate come from the country.

POST /agreements
{ "member_id": "…", "plan_id": "anytime-sa", "start_date": "2026-09-20", "due_day": 1 }
→ 201 { "id": "…", "member_id": "…", "plan_id": "anytime-sa", "start_date": "2026-09-20", "due_day": 1 }

    due_day is 1 to 31. A member may hold several agreements.
    An unknown member is 422 UNKNOWN_MEMBER, and an unknown plan is 422 UNKNOWN_PLAN.
    A plan from a different country than the member is 422 PLAN_COUNTRY_MISMATCH.

GET /agreements/{id}/invoices?from=2026-09-01&to=2026-12-31
→ 200 [
  { "invoice_no": 1, "due_date": "2026-09-20", "kind": "FIRST",
    "proration": { "days": 11, "cycle_days": 30 },
    "net": 10963, "vat": 1644, "total": 12607, "currency": "SAR" },
  { "invoice_no": 2, "due_date": "2026-10-01", "kind": "MONTHLY", "proration": null,
    "net": 29900, "vat": 4485, "total": 34385, "currency": "SAR" },
  …
]

    Agreements never end. Invoices are computed on request, so there is nothing to store.
    from and to are required and inclusive, and filter on due_date.
    to before from, or more than 366 days after it, is 422 INVALID_RANGE.
    invoice_no is the invoice's position in the agreement's whole schedule. It does not restart inside the range.

Rules

    Due dates. An agreement's due date in a month is min(due_day, days in that month). Due on the 31st means 30 April, 28 February (29th in a leap year) and 31 March. The anchor stays 31; only the date clamps.

    First invoice. Invoice 1 has kind FIRST and is due on the start date. Let N be the first due date strictly after the start date, and P the due date one month before N.
        Its net is monthly × (N − start) / (N − P), rounded, plus joining_fee.
        Its proration is {days: N − start, cycle_days: N − P}.
        A start date that is itself a due date gives days = cycle_days, which is the full price.

    Later invoices. Invoice 2 has kind MONTHLY, the full monthly price, and is due on N. Invoice 3 is due on the next month's due date, and so on. proration is null.

    Rounding. Round half up to a whole minor unit, exactly twice per invoice and never in between:
        once for the prorated amount;
        once for vat = net × VAT rate.

    total = net + vat. The joining fee sits inside the VAT base.

    Minor units only. Never round in major units. A BHD VAT of 579 fils is 0.579 BHD; rounding it to 0.58 is wrong.

Worked examples.

    Start 20 Sep 2026, due day 1, SA plan above. N = 1 Oct and P = 1 Sep, so 11/30.
        29900 × 11 / 30 = 10963.33, which rounds to a net of 10963.
        VAT is 1644.45, which rounds to 1644. The total is 12607.
    Start 5 Sep 2026, due day 20, AE plan with monthly 24900 and joining fee 9900. N = 20 Sep and P = 20 Aug, so 15/31.
        24900 × 15 / 31 = 12048.39, which rounds to 12048. Adding the joining fee gives a net of 21948.
        VAT is 1097.4, which rounds to 1097. The total is 23045.
        Invoice 2 is due 20 Sep, so September has two invoices.

Part 3. Reconciling the gateway file

Take one month of gateway rows, compare them with the invoices the schedule expects that month, and give each row a verdict.

POST /reconciliation/runs
{ "month": "2026-10",
  "rows": [
    { "gateway_txn_id": "T-88121", "agreement_id": "…", "amount": 34385,
      "currency": "SAR", "status": "SETTLED", "attempted_on": "2026-10-01" },
    { "gateway_txn_id": "T-88122", "agreement_id": "…", "amount": 26950,
      "currency": "BHD", "status": "DECLINED", "attempted_on": "2026-10-02" } ] }
→ 201 { "id": "…", "month": "2026-10",
        "summary": { "MATCHED": 1, "DUE_DAY_DRIFT": 0, "DOUBLE_CHARGE_RISK": 0,
                     "MISSING_FROM_LEDGER": 0, "DECLINED": 1 },
        "rows": [ { "gateway_txn_id": "T-88121", "verdict": "MATCHED",
                    "invoice": { "agreement_id": "…", "invoice_no": 2 } },
                  { "gateway_txn_id": "T-88122", "verdict": "DECLINED", "invoice": null } ],
        "unmatched_invoices": [ { "agreement_id": "…", "invoice_no": 2,
                                  "due_date": "2026-10-01", "total": 26950, "currency": "BHD" } ] }

GET /reconciliation/runs/{id} → 200 the same body

Rows

    amount is a positive integer in minor units and is compared with the invoice total, VAT included.
    status is SETTLED or DECLINED.
    agreement_id is always present but may not exist in your store.

Validation

The whole request fails with 422 INVALID_ROWS when any row breaks one of these rules. Add "errors": [{"gateway_txn_id": "…", "code": "…"}] inside error, with one entry per offending row and code, in any order.

    DUPLICATE_TXN: added for every row whose gateway_txn_id appears more than once.
    ROW_OUTSIDE_MONTH: attempted_on is not in month.
    CURRENCY_MISMATCH: the row's agreement exists and its plan's currency differs from the row's. Rows with an unknown agreement skip this check.

Matching

    Expected invoices are every invoice, from every agreement, whose due_date falls in month.
    Only SETTLED rows are matched. A row's candidates are its agreement's expected invoices whose total is within 1 minor unit of amount.
    Picking a candidate. With several candidates, take the earliest due date. Invoices already linked to another row still count.
    No candidate. An unknown agreement, or no candidate, makes the row MISSING_FROM_LEDGER.
    Order. The result must not depend on the order of rows in the request.

Verdict 	When
MATCHED 	The only settled row linked to its invoice, and attempted_on equals the invoice's due_date.
DUE_DAY_DRIFT 	The only settled row linked to its invoice, and attempted_on is a different day.
DOUBLE_CHARGE_RISK 	Two or more settled rows are linked to the same invoice. Every one of them gets this verdict.
MISSING_FROM_LEDGER 	No candidate, as above.
DECLINED 	The row's status is DECLINED. It takes no part in matching.
Response

    summary has a key for every verdict, including zeros.
    rows come back in request order, with invoice set to {agreement_id, invoice_no} or null.
    unmatched_invoices lists expected invoices that no settled row is linked to. Sort by due_date, then agreement_id, then invoice_no. An invoice whose only rows were declined belongs here.
    A run is stored and can be read back by id. It never changes members or agreements.

Repository URL *
Walkthrough video URL (5 minutes explaining your code, including prompts if any) *
LinkedIn or GitHub profile *
GymNation will store this application and run your code in an isolated environment to score it *
Verified

Protected by ALTCHA
Submit

</details>



---

## Claude

> 🔧 Ran: Check the project landed and whether GitHub CLI is set up

> 🔧 Ran: Check whether files were copied to the new folder

The brief on this page is word-for-word the one you pasted before, so the code doesn't need any changes. The page does add two things you still have to produce: **a 5-minute walkthrough video** and **a public repo URL**. The rest of the form (salary, visa, notice period) is yours to fill in.

**One problem:** Desktop/Personal/gulf-invoices-api is still empty. The app was meant to copy the project there when my last turn ended, but it hasn't, and the session is still running in the temporary folder. I can copy it over myself; just say so.

### What the page tells you about how they judge it

- **"14 minutes to write, 5 to record."** They expect you to lean hard on AI. Speed and polish aren't what's graded. Correctness is, and it's scored automatically.
- **The video is a filter before the interview.** "Explaining your code and how you used your tools" means they want to hear that you understand the code and checked the AI's work. A tour of the files isn't enough.
- **The interview has two gates.** Parts 1 and 2 have to pass for you to get an interview at all. Part 3 still counts, but the phone and invoice rules decide whether you get through.

### A 5-minute video outline

| Time | What to show | What to say |
|---|---|---|
| 0:00–0:30 | The folder layout | Python + FastAPI, state kept in memory, one file per part, one lock for every check-then-save. |
| 0:30–1:30 | `app/phones.py` | Clean the number, try the international form, then the national one, and always store `+9665…`. Lookups clean the number the same way, so every spelling finds the same member. The lock stops two people taking the same phone at the same moment. |
| 1:30–2:45 | `app/schedule.py` | Walk through N and P on the 20 Sep example. Money stays in whole fils with the formula `(2·a + b) // (2·b)`, never a decimal number. Show that the 31st becomes 28 February. |
| 2:45–3:45 | `app/reconcile.py` | Check the rows, link each payment to its own earliest matching invoice, then count links per invoice to pick the verdicts. Explain why the row order can't change the result. |
| 3:45–4:30 | `PROMPTS.md`, `NOTES.md` | How you used AI: you pasted the brief, let it write the code, then checked it. Mention that when tests failed, the tests were wrong, not the code (30 Sep to 31 Oct is a 31-day cycle). Name the assumptions you reviewed. |
| 4:30–5:00 | A terminal running `docker build --target test .` and `./scripts/try-it.sh` | How you checked it works, and the double-payment race ending as one 201 and nine 409s. |

A good extra point for the video: the brief's Part 3 example uses 26950 as a Bahraini invoice total. That figure looks like the price before VAT, since 26950 plus 10% is 29645. Spotting it shows you read closely, and the code compares against the total with VAT included, as the rules say.

### Before you press Submit

1. **Rehearse.** Run `./scripts/try-it.sh` yourself so you can explain every line it prints.
2. **Fill in PROMPTS.md.** Export this conversation and paste it in, as the page asks.
3. **Push to GitHub.** It needs a public repo on the `main` branch. Your GitHub command-line tool is signed in as `rida-asif-gymn`, so I can create the repo and push it for you, but only once you say yes, since that publishes the code.
4. **Use one email.** You only get one application per email address, so submit once, when everything is ready.


---

## Me

*(ran in terminal)* `docker build --target test .`

> unable to prepare context: unable to evaluate symlinks in Dockerfile path: lstat /Users/rida/Dockerfile: no such file or directory


---

## Claude

That error means Docker was run from your home folder (`/Users/rida`), not the project folder, so it couldn't find the `Dockerfile`. I'll check the copied files and run it from the right place:

> 🔧 Ran: List project files and run the Docker test stage there

Nothing is wrong with the project. Your command ran in your home folder (`/Users/rida`), and Docker looks for the `Dockerfile` in whatever folder you're in. The project is in **Desktop/Personal/gulf-invoices-api**, and I just ran the same build from there: it succeeded and all tests passed.

Move into the project folder first:
```bash
cd ~/Desktop/Personal/gulf-invoices-api
```
Then run the tests:
```bash
docker build --target test .
```
If it finishes with a line starting `sha256:` and no `FAILED` lines, every test passed. You can ignore the "legacy builder is deprecated" warning.

To try the API by hand, start the server from that same folder:
```bash
docker build -t app . && docker run -p 8080:8080 app
```
Then open a second terminal, `cd` into the folder again, and run the walkthrough:
```bash
./scripts/try-it.sh
```
Leave the first terminal running, because it's the server. Stop it with Ctrl+C when you're done.

The local `.venv` folder wasn't copied over, but you don't need it, since Docker handles everything.


---

## Me

*(ran in terminal)* `docker build -t app . && docker run -p 8080:8080 app`

> unable to prepare context: unable to evaluate symlinks in Dockerfile path: lstat /Users/rida/Dockerfile: no such file or directory


---

## Claude

Same cause as before. The `!` commands you type here seem to start in your home folder every time, so a separate `cd` doesn't carry over to the next command. Put the `cd` in the same line as the command:

```bash
cd ~/Desktop/Personal/gulf-invoices-api && docker build -t app . && docker run -p 8080:8080 app
```

That starts the server and keeps it running. Since it doesn't stop on its own, it's better to run it in a normal Terminal window than through `!`. Then, in a second Terminal window:

```bash
cd ~/Desktop/Personal/gulf-invoices-api && ./scripts/try-it.sh
```

If you'd like, I can start the server in the background here and run the walkthrough for you.


---

## Me

*(ran in terminal)* `./scripts/try-it.sh`

> zsh: no such file or directory: ./scripts/try-it.sh


---

## Claude

> 🔧 Ran: Check whether the API server is running on port 8080

Same cause again: the `!` command ran in your home folder, so `./scripts/...` pointed at nothing. Also, the server isn't running yet. I'll start it in the background so you only need one command:

> 🔧 Ran: Build the image and start the API container on port 8080

The server is running now on `localhost:8080`, and its health check returns 200. It runs in Docker as a container named `gulf-api`.

Run the walkthrough with the folder path included, so it works from anywhere:

```bash
~/Desktop/Personal/gulf-invoices-api/scripts/try-it.sh
```

Each step prints a heading saying what to expect, followed by the actual response, so you can check them against each other.

You can also call the API yourself, for example:

```bash
curl -s "localhost:8080/members/lookup?phone=0551234567"
```

That one should return a `PHONE_NEEDS_COUNTRY` error. If you run it after the walkthrough, add `&country=SA` and you'll get Noura back.

Each time the server starts, it starts empty. To stop it:

```bash
docker rm -f gulf-api
```


---

## Me

*(ran in terminal)* `cd ~/Desktop/Personal/gulf-invoices-api`

> [No output was captured. The command ran in the terminal pane (tab 0); if it should have printed something, use read_terminal with tab_id "0" to check.]


---

## Claude

You're in the project folder now, and the terminal tab will stay there. The server is still running, so you can run the walkthrough:

```bash
./scripts/try-it.sh
```

Run any other project command from that same tab, like `docker build --target test .`.


---

## Me

*(ran in terminal)* `docker build -t app . && docker run -p 8080:8080 app`

> Run 'docker run --help' for more information


---

## Claude

The build worked. The run failed only because the server I started in the background is already using port 8080, and only one program can use a port at a time. You have two options.

**Option 1 (simplest):** keep using the server that's already running and go straight to the walkthrough:
```bash
./scripts/try-it.sh
```

**Option 2:** stop my background server, then run your own in this tab so you can watch its logs as requests come in:
```bash
docker rm -f gulf-api
```
```bash
docker run -p 8080:8080 app
```
With option 2, this tab stays busy running the server. Run `./scripts/try-it.sh` from a second terminal tab after you `cd ~/Desktop/Personal/gulf-invoices-api` there, and press Ctrl+C in this tab to stop the server.


---

## Me

How can I import this chat for the Prompts.md? or can u adddurself in it, and then pushed into the repo 'https://github.com/rida-asif-gymn/gymn-interview-testr1'


---

## Claude

> 🔧 Ran: Inspect local git state and the target GitHub repo
