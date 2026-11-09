#!/usr/bin/env bash
# Walks through every endpoint against a running server and prints each response.
# Safe to run many times on the same server: each run uses its own random phones and plan ids.
# Usage:  docker run -p 8080:8080 app      (in one terminal)
#         ./scripts/try-it.sh              (in another; or BASE=http://localhost:9000 ./scripts/try-it.sh)
set -u
BASE="${BASE:-http://localhost:8080}"

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
call() { # METHOD PATH [JSON]
  if [ $# -ge 3 ]; then
    curl -s -w '   <- HTTP %{http_code}\n' -X "$1" "$BASE$2" -H 'content-type: application/json' -d "$3"
  else
    curl -s -w '   <- HTTP %{http_code}\n' -X "$1" "$BASE$2"
  fi
}
id_of() { python3 -c 'import sys,json
try: print(json.loads(sys.stdin.read().rsplit("   <-",1)[0]).get("id",""))
except Exception: print("")'; }
need() { if [ -z "$2" ]; then echo "!! $1 was not created, so the remaining steps cannot run."; exit 1; fi; }

if ! curl -sf -m 3 "$BASE/health" >/dev/null; then
  echo "No server answering at $BASE."
  echo "Start it first in another terminal:  docker build -t app . && docker run -p 8080:8080 app"
  exit 1
fi

# Random 7 digits per run, so phones and plan ids never collide with an earlier run.
N=$(python3 -c 'import random; print(random.randint(1000000, 9999999))')   # Saudi member: 055 + N
R=$(python3 -c 'import random; print(random.randint(1000000, 9999999))')   # race test:    050 + R
PSA="anytime-sa-$N"; PAE="anytime-ae-$N"
echo "This run: Saudi phone 055${N} (+96655${N}), plans $PSA / $PAE"

step "Health (expect 200)"
call GET /health

step "Part 1: create a Saudi member with a messy national number (expect 201, phone +96655${N})"
M=$(call POST /members "{\"name\":\"  Noura Al Harbi \",\"country\":\"SA\",\"phone\":\"055 ${N:0:3} ${N:3:4}\"}"); echo "$M"
MID=$(echo "$M" | id_of); need "The member" "$MID"

step "Lookup in three spellings (expect the same member, 200, each time)"
call GET "/members/lookup?phone=96655${N}"
call GET "/members/lookup?phone=%2B96655${N}"
call GET "/members/lookup?phone=055%20${N:0:3}%20${N:3:4}&country=SA"

step "Lookup errors"
call GET "/members/lookup?phone=055${N}"                     # 422 PHONE_NEEDS_COUNTRY
call GET "/members/lookup?phone=%2B96655${N}&country=AE"     # 422 PHONE_COUNTRY_MISMATCH
call GET "/members/lookup?phone=00966551234567"              # 422 INVALID_PHONE
call GET "/members/lookup?phone=0530000000&country=SA"       # 404 NOT_FOUND

step "Same phone, different spelling (expect 409 PHONE_TAKEN with existing_member_id = $MID)"
call POST /members "{\"name\":\"Someone Else\",\"country\":\"SA\",\"phone\":\"+966 55-${N:0:3}-${N:3:4}\"}"

step "Bad input (expect 422 VALIDATION)"
call POST /members '{"name":"","country":"SA","phone":"0551234567"}'

step "Part 2: plans (expect 201, then 409 PLAN_EXISTS, then 201)"
call POST /plans "{\"id\":\"$PSA\",\"country\":\"SA\",\"monthly\":29900,\"joining_fee\":0}"
call POST /plans "{\"id\":\"$PSA\",\"country\":\"SA\",\"monthly\":29900,\"joining_fee\":0}"
call POST /plans "{\"id\":\"$PAE\",\"country\":\"AE\",\"monthly\":24900,\"joining_fee\":9900}"

step "Agreement: start 20 Sep 2026, due day 1 (expect 201)"
A=$(call POST /agreements "{\"member_id\":\"$MID\",\"plan_id\":\"$PSA\",\"start_date\":\"2026-09-20\",\"due_day\":1}"); echo "$A"
AID=$(echo "$A" | id_of); need "The agreement" "$AID"

step "Agreement with a plan from another country (expect 422 PLAN_COUNTRY_MISMATCH)"
call POST /agreements "{\"member_id\":\"$MID\",\"plan_id\":\"$PAE\",\"start_date\":\"2026-09-20\",\"due_day\":1}"

step "Invoices Sep-Dec (expect #1 FIRST 11/30 net 10963 vat 1644 total 12607, then 34385 monthly)"
call GET "/agreements/$AID/invoices?from=2026-09-01&to=2026-12-31"

step "Invoices: range too long (expect 422 INVALID_RANGE), unknown agreement (expect 404)"
call GET "/agreements/$AID/invoices?from=2026-01-01&to=2027-06-01"
call GET "/agreements/nope/invoices?from=2026-01-01&to=2026-02-01"

step "Part 3: reconcile October (expect T-1,T-2 DOUBLE_CHARGE_RISK on invoice 2, T-3 MISSING_FROM_LEDGER, T-4 DECLINED)"
echo "   (unmatched_invoices also lists October invoices from agreements made by earlier runs on this server)"
RUN=$(call POST /reconciliation/runs "{\"month\":\"2026-10\",\"rows\":[
  {\"gateway_txn_id\":\"T-1\",\"agreement_id\":\"$AID\",\"amount\":34385,\"currency\":\"SAR\",\"status\":\"SETTLED\",\"attempted_on\":\"2026-10-01\"},
  {\"gateway_txn_id\":\"T-2\",\"agreement_id\":\"$AID\",\"amount\":34386,\"currency\":\"SAR\",\"status\":\"SETTLED\",\"attempted_on\":\"2026-10-04\"},
  {\"gateway_txn_id\":\"T-3\",\"agreement_id\":\"ghost\",\"amount\":100,\"currency\":\"SAR\",\"status\":\"SETTLED\",\"attempted_on\":\"2026-10-05\"},
  {\"gateway_txn_id\":\"T-4\",\"agreement_id\":\"$AID\",\"amount\":34385,\"currency\":\"SAR\",\"status\":\"DECLINED\",\"attempted_on\":\"2026-10-01\"}]}"); echo "$RUN"
RID=$(echo "$RUN" | id_of); need "The reconciliation run" "$RID"

step "Read the run back (expect the same body)"
call GET "/reconciliation/runs/$RID"

step "Bad file (expect 422 INVALID_ROWS listing DUPLICATE_TXN x2, ROW_OUTSIDE_MONTH, CURRENCY_MISMATCH)"
call POST /reconciliation/runs "{\"month\":\"2026-10\",\"rows\":[
  {\"gateway_txn_id\":\"D\",\"agreement_id\":\"$AID\",\"amount\":1,\"currency\":\"SAR\",\"status\":\"SETTLED\",\"attempted_on\":\"2026-10-01\"},
  {\"gateway_txn_id\":\"D\",\"agreement_id\":\"$AID\",\"amount\":1,\"currency\":\"SAR\",\"status\":\"SETTLED\",\"attempted_on\":\"2026-11-01\"},
  {\"gateway_txn_id\":\"C\",\"agreement_id\":\"$AID\",\"amount\":1,\"currency\":\"AED\",\"status\":\"SETTLED\",\"attempted_on\":\"2026-10-01\"}]}"

step "Race: 10 parallel creates of one new phone (050${R}) in different spellings (expect 1x 201, 9x 409)"
for p in "050${R}" "+97150${R}" "97150${R}" "050 ${R:0:3} ${R:3:4}" "(050) ${R:0:3}-${R:3:4}" \
         "050${R}" "+971 50 ${R}" "971-50-${R}" "050-${R:0:3}-${R:3:4}" "050${R}"; do
  curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BASE/members" -H 'content-type: application/json' \
    -d "{\"name\":\"Racer\",\"country\":\"AE\",\"phone\":\"$p\"}" &
done | sort | uniq -c
wait
