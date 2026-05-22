"""End-to-end smoke test for MiniSuite. Exercises CLAUDE.md section 11.

Run the server (`python -m app.main`) in another terminal, then:
    python smoke.py [--base http://127.0.0.1:8000] [--token demo-token-ridgeline]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

DEFAULT_BASE = os.environ.get("MINISUITE_BASE", "http://127.0.0.1:8000")
DEFAULT_TOKEN = os.environ.get("MINISUITE_TOKEN", "demo-token-ridgeline").split(",")[0]


class Checker:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, label: str, cond: bool, extra: str = ""):
        status = "PASS" if cond else "FAIL"
        marker = "[+]" if cond else "[-]"
        print(f"  {marker} {status}  {label}" + (f"  ({extra})" if extra else ""))
        if cond:
            self.passed += 1
        else:
            self.failed += 1

    def section(self, n: int, title: str):
        print(f"\n[{n:>2}] {title}")


def main(base: str, token: str) -> int:
    c = Checker()
    auth = {"Authorization": f"Bearer {token}"}
    client = httpx.Client(base_url=base, timeout=10.0, follow_redirects=False)

    # 1. Freight Expense + Accrued Freight lookup
    c.section(1, 'GET account ?q=acctNumber EQUALS "6011"')
    r = client.get('/services/rest/record/v1/account', params={"q": 'acctNumber EQUALS "6011"'}, headers=auth)
    c.check("status 200", r.status_code == 200, f"got {r.status_code}")
    items = r.json().get("items", [])
    c.check("exactly one item for 6011", len(items) == 1)
    freight_id = items[0]["id"] if items else None

    r = client.get('/services/rest/record/v1/account', params={"q": 'acctNumber EQUALS "2011"'}, headers=auth)
    items = r.json().get("items", [])
    c.check("exactly one item for 2011", len(items) == 1)
    accrued_id = items[0]["id"] if items else None

    # 2. Apr 2026 open
    c.section(2, "GET accountingPeriod includes Apr 2026 open")
    r = client.get('/services/rest/record/v1/accountingPeriod', params={"limit": 1000}, headers=auth)
    period_ids = [it["id"] for it in r.json().get("items", [])]
    apr_2026 = None
    for pid in period_ids:
        pr = client.get(f"/services/rest/record/v1/accountingPeriod/{pid}", headers=auth).json()
        if pr.get("periodName") == "Apr 2026":
            apr_2026 = pr
            break
    c.check("Apr 2026 found", apr_2026 is not None)
    if apr_2026:
        c.check("Apr 2026 closed == false", apr_2026["closed"] is False)

    feb_2026 = None
    for pid in period_ids:
        pr = client.get(f"/services/rest/record/v1/accountingPeriod/{pid}", headers=auth).json()
        if pr.get("periodName") == "Feb 2026":
            feb_2026 = pr
            break

    # 3. Three carriers
    c.section(3, "GET vendor lists the three carriers")
    r = client.get('/services/rest/record/v1/vendor', headers=auth)
    carriers = []
    for it in r.json().get("items", []):
        vr = client.get(f"/services/rest/record/v1/vendor/{it['id']}", headers=auth).json()
        carriers.append(vr["entityId"])
    c.check("Peak Logistics present", "Peak Logistics" in carriers)
    c.check("Heartland Freight present", "Heartland Freight" in carriers)
    c.check("Coastal Express present", "Coastal Express" in carriers)

    # 4. Auth check
    c.section(4, "Missing/bad token returns 401 with error envelope")
    r = client.get('/services/rest/record/v1/account')
    c.check("no header -> 401", r.status_code == 401, f"got {r.status_code}")
    body = r.json()
    c.check("RFC-7807 envelope present", isinstance(body, dict) and "o:errorDetails" in body)

    r = client.get('/services/rest/record/v1/account', headers={"Authorization": "Bearer wrong-token"})
    c.check("wrong bearer -> 401", r.status_code == 401)

    # 5. POST a balanced accrual JE
    c.section(5, "POST balanced JE (Dr 6011 / Cr 2011)")
    je_body = {
        "tranDate": "2026-04-30",
        "reversalDate": "2026-05-01",
        "memo": "April 2026 freight accrual (smoke)",
        "line": {
            "items": [
                {"account": {"id": freight_id}, "debit": 91234.56, "memo": "Freight April"},
                {"account": {"id": accrued_id}, "credit": 91234.56, "memo": "Accrued freight"},
            ]
        },
    }
    r = client.post('/services/rest/record/v1/journalEntry', headers={**auth, "Content-Type": "application/json"}, content=json.dumps(je_body))
    c.check("status 204", r.status_code == 204, f"got {r.status_code}")
    location = r.headers.get("Location") or r.headers.get("location") or ""
    c.check("Location header present", bool(location))
    new_id = location.rstrip("/").split("/")[-1] if location else ""

    # 6. GET JE back with expanded sublist
    c.section(6, f"GET journalEntry/{new_id}?expandSubResources=true")
    r = client.get(f"/services/rest/record/v1/journalEntry/{new_id}", params={"expandSubResources": "true"}, headers=auth)
    c.check("status 200", r.status_code == 200)
    je = r.json()
    lines = je.get("line", {}).get("items", [])
    c.check("2 lines returned", len(lines) == 2)
    d_total = sum(float(li.get("debit") or 0) for li in lines)
    c_total = sum(float(li.get("credit") or 0) for li in lines)
    c.check("debits == credits", abs(d_total - c_total) < 0.01, f"{d_total} vs {c_total}")

    # 7. Unbalanced JE -> 400 USER_ERROR
    c.section(7, "POST unbalanced JE -> 400 USER_ERROR")
    bad = {
        "tranDate": "2026-04-30",
        "line": {"items": [
            {"account": {"id": freight_id}, "debit": 90000.00},
            {"account": {"id": accrued_id}, "credit": 89000.00},
        ]},
    }
    r = client.post('/services/rest/record/v1/journalEntry', headers={**auth, "Content-Type": "application/json"}, content=json.dumps(bad))
    c.check("status 400", r.status_code == 400)
    body = r.json()
    has_user_error = any(d.get("o:errorCode") == "USER_ERROR" for d in body.get("o:errorDetails", []))
    c.check("o:errorCode USER_ERROR", has_user_error)

    # 8. POST to closed period -> 409 PERIOD_CLOSED
    c.section(8, "POST JE in closed period (Feb 2026) -> 409 PERIOD_CLOSED")
    closed = {
        "tranDate": "2026-02-15",
        "line": {"items": [
            {"account": {"id": freight_id}, "debit": 1000},
            {"account": {"id": accrued_id}, "credit": 1000},
        ]},
    }
    r = client.post('/services/rest/record/v1/journalEntry', headers={**auth, "Content-Type": "application/json"}, content=json.dumps(closed))
    c.check("status 409", r.status_code == 409)
    body = r.json()
    has_pc = any(d.get("o:errorCode") == "PERIOD_CLOSED" for d in body.get("o:errorDetails", []))
    c.check("o:errorCode PERIOD_CLOSED", has_pc)

    # 9. POST referencing nonexistent account -> 400 INVALID_KEY_OR_REF
    c.section(9, "POST JE referencing nonexistent account -> 400 INVALID_KEY_OR_REF")
    badref = {
        "tranDate": "2026-04-30",
        "line": {"items": [
            {"account": {"id": "99999"}, "debit": 100},
            {"account": {"id": accrued_id}, "credit": 100},
        ]},
    }
    r = client.post('/services/rest/record/v1/journalEntry', headers={**auth, "Content-Type": "application/json"}, content=json.dumps(badref))
    c.check("status 400", r.status_code == 400)
    body = r.json()
    has_ref = any(d.get("o:errorCode") == "INVALID_KEY_OR_REF" for d in body.get("o:errorDetails", []))
    c.check("o:errorCode INVALID_KEY_OR_REF", has_ref)

    # 10. Vendor bills
    c.section(10, "GET vendorBill list + single record expense lines")
    r = client.get('/services/rest/record/v1/vendorBill', headers=auth)
    c.check("status 200", r.status_code == 200)
    items = r.json().get("items", [])
    c.check("at least 10 vendor bills seeded", len(items) >= 10, f"got {len(items)}")
    if items:
        first = items[0]["id"]
        rr = client.get(f"/services/rest/record/v1/vendorBill/{first}", headers=auth)
        exp_lines = rr.json().get("expense", {}).get("items", [])
        c.check("expense.items present and nonempty", len(exp_lines) >= 1)

    # 11. SuiteQL
    c.section(11, "SuiteQL: with and without Prefer: transient")
    r = client.post(
        '/services/rest/query/v1/suiteql',
        headers={**auth, "Content-Type": "application/json", "Prefer": "transient"},
        content=json.dumps({"q": "SELECT acctNumber, acctName FROM account ORDER BY acctNumber"}),
    )
    c.check("status 200 with Prefer: transient", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        rows = r.json().get("items", [])
        c.check("rows returned", len(rows) >= 1)

    r = client.post(
        '/services/rest/query/v1/suiteql',
        headers={**auth, "Content-Type": "application/json"},
        content=json.dumps({"q": "SELECT acctNumber FROM account"}),
    )
    c.check("missing Prefer -> 400", r.status_code == 400)

    # 12. UI loads
    c.section(12, "UI loads + lists the new JE")
    r = client.get('/ui/journalEntries')
    c.check("status 200", r.status_code == 200)
    c.check("contains 'Journal Entries'", "Journal Entries" in r.text)
    # The new JE's tranId or id should appear:
    r2 = client.get(f"/services/rest/record/v1/journalEntry/{new_id}", headers=auth)
    tran_id = r2.json().get("tranId", "")
    c.check("new JE listed in UI", tran_id in r.text)

    # Token-issuing convenience endpoint
    c.section(13, "POST /services/rest/auth/token returns the dev token (convenience)")
    r = client.post('/services/rest/auth/token')
    c.check("status 200", r.status_code == 200)
    body = r.json()
    c.check("access_token = token", body.get("access_token") == token)

    print(f"\nResult: {c.passed} passed, {c.failed} failed.")
    return 0 if c.failed == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--token", default=DEFAULT_TOKEN)
    args = p.parse_args()
    sys.exit(main(args.base, args.token))
