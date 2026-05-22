# MiniSuite — Mock NetSuite REST API for Ridgeline Foods

A minimal but faithful mock of Oracle NetSuite's REST Record API and SuiteQL endpoint,
built for the Finance Engineer Cup freight-accrual scenario. Same base paths and payload
shapes as real NetSuite, so a client written against this mock can be repointed at a real
NetSuite account by changing only the host and the auth token.

Stack: Python 3.11+ · FastAPI · SQLite · Jinja2.

---

## Quick start

```bash
pip install -r requirements.txt
python -m app.seed        # idempotent; creates the SQLite file and loads the scenario
python -m app.main        # starts the server on http://127.0.0.1:8000
```

On startup the server prints the base URL, the `/docs` URL, and the dev Bearer token.

| Resource | URL |
|---|---|
| UI (home) | http://127.0.0.1:8000/ |
| Swagger | http://127.0.0.1:8000/docs |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json |
| Records | `http://127.0.0.1:8000/services/rest/record/v1/{recordType}` |
| SuiteQL | `http://127.0.0.1:8000/services/rest/query/v1/suiteql` |

Dev Bearer token: **`demo-token-ridgeline`** (override with `MINISUITE_TOKEN`, comma-separated for multiple).

---

## Commands

```bash
python -m app.seed              # idempotent seed (safe to re-run)
python -m app.seed --reset      # drop tables, re-create, re-seed (handy before a demo)
python -m app.main              # run the server
python smoke.py                 # end-to-end smoke test against a running server
```

Or with `make`: `make install`, `make seed`, `make run`, `make reset`, `make smoke`.

---

## Authentication

Every `/services/**` request needs an `Authorization` header. Three modes accepted:

```
Authorization: Bearer demo-token-ridgeline
Authorization: OAuth realm="...", oauth_consumer_key="...", ...   # accepted as-is, not verified
Authorization: NLAuth nlauth_account=..., nlauth_email=...        # accepted as-is, not verified
```

Missing or unknown Bearer token → `401` with an RFC-7807 envelope. The OAuth/NLAuth pass-through
is a **mock-only shortcut** so a real-NetSuite-configured client doesn't need code changes
to hit the mock.

Convenience OAuth2 client-credentials stub:

```bash
curl -X POST http://127.0.0.1:8000/services/rest/auth/token
# → { "access_token": "demo-token-ridgeline", "token_type": "Bearer", "expires_in": 3600 }
```

---

## Records implemented

| Record type | Path | Notes |
|---|---|---|
| `journalEntry` | `/services/rest/record/v1/journalEntry` | Header + `line.items` sublist; full balance/period/ref validation |
| `account` | `/services/rest/record/v1/account` | Chart of accounts |
| `vendor` | `/services/rest/record/v1/vendor` | The three carriers |
| `vendorBill` | `/services/rest/record/v1/vendorBill` | Historical actuals + `expense.items` sublist |
| `accountingPeriod` | `/services/rest/record/v1/accountingPeriod` | Toggle open/closed |
| `currency` | `/services/rest/record/v1/currency` | USD only |
| `subsidiary` | `/services/rest/record/v1/subsidiary` | Ridgeline Foods |
| `department`, `classification`, `location` | `/services/rest/record/v1/{type}` | Segments |

Each supports `GET /` (list), `GET /{id}` (single), `POST /` (create → `204` + `Location`),
`PATCH /{id}` (partial update), `DELETE /{id}`.

### Query filtering (`?q=`)

A subset of NetSuite's expression syntax, joinable by `AND`:
- `acctNumber EQUALS "6011"`
- `entity EQUALS "3"`
- `tranDate ON_OR_AFTER "2026-04-01"`
- `acctName START_WITH "Freight"`
- `companyName CONTAINS "Peak"`

Operators: `EQUALS`, `NOT_EQUALS`, `START_WITH`, `CONTAINS`, `ON_OR_AFTER`,
`ON_OR_BEFORE`, `AFTER`, `BEFORE`, and shorthand `=` `!=` `>=` `<=` `>` `<`.

Plain `?field=value` is also accepted as a fallback.

Pagination: `?limit=` (max 1000, default 1000) and `?offset=` (default 0).

### Sublists

`GET /{id}?expandSubResources=true` inlines sublists (`line.items`, `expense.items`).
This mock always inlines sublists on single-record reads regardless of the flag.

---

## Example: POST a balanced freight accrual JE

```bash
TOKEN=demo-token-ridgeline
BASE=http://127.0.0.1:8000

# Resolve account ids
FREIGHT=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/services/rest/record/v1/account?q=acctNumber%20EQUALS%20%226011%22" \
  | python -c "import sys,json;print(json.load(sys.stdin)['items'][0]['id'])")
ACCRUED=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/services/rest/record/v1/account?q=acctNumber%20EQUALS%20%222011%22" \
  | python -c "import sys,json;print(json.load(sys.stdin)['items'][0]['id'])")

# Post the JE (Dr 6011 / Cr 2011, dated 2026-04-30 with a May 1 reversal)
curl -i -X POST "$BASE/services/rest/record/v1/journalEntry" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "tranDate": "2026-04-30",
  "reversalDate": "2026-05-01",
  "memo": "April 2026 freight accrual",
  "line": {
    "items": [
      { "account": { "id": "$FREIGHT" }, "debit":  91234.56, "memo": "Freight April" },
      { "account": { "id": "$ACCRUED" }, "credit": 91234.56, "memo": "Accrued freight" }
    ]
  }
}
EOF
# → HTTP/1.1 204 No Content
# → Location: /services/rest/record/v1/journalEntry/{newId}

# Read it back with sublist
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/services/rest/record/v1/journalEntry/{newId}?expandSubResources=true" | python -m json.tool
```

### Validation errors you can demonstrate

| Scenario | Status | `o:errorCode` |
|---|---|---|
| Debits ≠ credits | 400 | `USER_ERROR` |
| Account/vendor/department id doesn't exist | 400 | `INVALID_KEY_OR_REF` |
| `tranDate` falls in a closed period | 409 | `PERIOD_CLOSED` |
| `< 2` lines, or a line with both debit and credit | 400 | `USER_ERROR` |
| Missing/bad Bearer token | 401 | `INSUFFICIENT_PERMISSION` |
| Unknown record type | 404 | `INVALID_RECORD_TYPE` |
| Record not found | 404 | `RCRD_DSNT_EXIST` |

---

## SuiteQL

```bash
curl -X POST "$BASE/services/rest/query/v1/suiteql" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Prefer: transient" \
  -d '{"q": "SELECT acctNumber, acctName FROM account ORDER BY acctNumber"}'
```

Documented subset:
- `SELECT` only (no INSERT/UPDATE/DELETE/DDL).
- `Prefer: transient` header is required (missing → 400, matches real NetSuite).
- Tables: any record type's underlying table (camelCase, same names as the record types),
  plus a virtual `transaction` view that unions `journalEntry` + `vendorBill` headers.
- Pagination via `?limit=&offset=`. Response is the same collection envelope as the REST API.

---

## Seed data

Loaded by `python -m app.seed` (idempotent — safe to re-run):

- **Currency:** USD (id `"1"`)
- **Subsidiary:** Ridgeline Foods (id `"1"`)
- **Segments:** Operations (department), Logistics (classification), Denver HQ (location)
- **Chart of accounts:** 1000 Operating Bank · 2000 AP · 2010 Accrued Liab · **2011 Accrued Freight** · 4000 Revenue · 5000 COGS · **6011 Freight & Delivery Expense** · 6610 Other Op Expense
- **Vendors:** Peak Logistics · Heartland Freight · Coastal Express
- **Accounting periods:** monthly Oct 2025 → May 2026. **Oct 2025–Mar 2026 closed**; **Apr 2026 & May 2026 open.**
- **Vendor bills:** historical carrier invoices Oct 2025–Mar 2026 (sourced from `data/freight_invoices_oct2025_mar2026_v2.csv` if you drop it in `./data/`; otherwise a representative hardcoded set).
- **Journal entries:** historical Oct 2025–Mar 2026 freight accruals (Dr 6011 / Cr 2011). The April accrual is **not** pre-seeded — that's the one your engine will POST.

### Using real challenge numbers

If you have the Finance Engineer Cup CSVs:
```bash
mkdir data
cp /path/to/freight_invoices_oct2025_mar2026_v2.csv data/
python -m app.seed --reset
```
The seed aggregates the invoice CSV to one bill per (carrier × service month).

---

## Acceptance criteria (CLAUDE.md §11)

Run `python smoke.py` against a running server — it exercises:

1. `account ?q=acctNumber EQUALS "6011"` returns Freight Expense
2. Apr 2026 period present and `closed == false`
3. Vendors include the three carriers
4. Missing/bad token → 401 with envelope
5. POST balanced JE → 204 + Location
6. GET JE back with `?expandSubResources=true` shows both lines and equal totals
7. POST unbalanced JE → 400 USER_ERROR
8. POST JE to closed period → 409 PERIOD_CLOSED
9. POST JE referencing nonexistent account → 400 INVALID_KEY_OR_REF
10. Vendor bills list + single record expense lines
11. SuiteQL with/without `Prefer: transient`
12. UI loads, lists the new JE
13. `POST /services/rest/auth/token` returns the dev token

Expected: `13/13 PASS`.

---

## Deploying for free + Cloudflare subdomain

See [DEPLOY.md](DEPLOY.md) for the full guide. Short version:

1. Create a Fly.io account (free), install `flyctl`.
2. From this folder: `fly launch --no-deploy --copy-config` (keep the `fly.toml` here),
   then `fly volumes create minisuite_data --size 1`, then `fly deploy`.
3. Note the `*.fly.dev` hostname.
4. In Cloudflare DNS for your domain, add a **CNAME** `minisuite` → `your-app.fly.dev`, proxied.
5. In Fly: `fly certs add minisuite.yourdomain.com`.
6. Hit `https://minisuite.yourdomain.com/` for the UI, `https://minisuite.yourdomain.com/docs` for Swagger.
7. Point any NetSuite-shaped client at `https://minisuite.yourdomain.com` with the same Bearer token.

---

## Non-goals

This is **not** a real ERP. No GL engine, consolidation, tax, SuiteScript, real OAuth crypto,
production-grade RBAC, or full SuiteQL coverage. The whole point is interface fidelity so an
accrual engine has somewhere realistic to post — barebones internals, NetSuite-shaped surface.
