"""SuiteQL stub.

Documented subset: simple `SELECT` statements against the safe-listed tables below.
No INSERT/UPDATE/DELETE, no PRAGMA, no semicolons, no comments. Pagination via
?limit and ?offset. Requires `Prefer: transient` header (matches real NetSuite).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import require_token
from ..db import get_db
from ..errors import NSError

router = APIRouter(
    prefix="/services/rest/query/v1/suiteql",
    tags=["suiteql"],
    dependencies=[Depends(require_token)],
)

SAFE_TABLES = {
    "account",
    "vendor",
    "vendorBill",
    "vendorBillExpenseLine",
    "accountingPeriod",
    "journalEntry",
    "journalEntryLine",
    "currency",
    "subsidiary",
    "department",
    "classification",
    "location",
    "transaction",
}

# `transaction` alias: union of JE + VB headers, mapped to NetSuite-ish columns.
TRANSACTION_VIEW_SQL = """
WITH transaction AS (
  SELECT
    CAST(je.id AS TEXT) AS id,
    je.tranId AS tranid,
    'JournalEntry' AS recordtype,
    je.tranDate AS trandate,
    je.memo AS memo,
    je.postingPeriod_id AS postingperiod,
    NULL AS entity,
    NULL AS total
  FROM journalEntry je
  UNION ALL
  SELECT
    CAST(vb.id AS TEXT) AS id,
    vb.tranId AS tranid,
    'VendorBill' AS recordtype,
    vb.tranDate AS trandate,
    vb.memo AS memo,
    vb.postingPeriod_id AS postingperiod,
    CAST(vb.entity_id AS TEXT) AS entity,
    vb.total AS total
  FROM vendorBill vb
)
"""


@router.post("")
async def suiteql(
    request: Request,
    db: Session = Depends(get_db),
    prefer: str | None = Header(default=None, alias="Prefer"),
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if not prefer or "transient" not in prefer.lower():
        raise NSError(400, "Prefer: transient header is required for SuiteQL.", "USER_ERROR")
    body = await request.json()
    if not isinstance(body, dict) or "q" not in body:
        raise NSError(400, "Body must be { 'q': '<SELECT ...>' }.", "USER_ERROR")
    q = body["q"].strip().rstrip(";")
    if not q:
        raise NSError(400, "Empty query.", "USER_ERROR")
    upper = q.upper()
    if not upper.startswith("SELECT"):
        raise NSError(400, "Only SELECT statements are supported by this mock.", "USER_ERROR")
    forbidden = ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "PRAGMA ", "--", "/*")
    if any(tok in upper for tok in forbidden):
        raise NSError(400, "Forbidden token in query.", "USER_ERROR")
    if ";" in q:
        raise NSError(400, "Multiple statements not allowed.", "USER_ERROR")

    table_refs = re.findall(r"\bFROM\s+(\w+)|\bJOIN\s+(\w+)", q, flags=re.IGNORECASE)
    referenced = {tbl for pair in table_refs for tbl in pair if tbl}
    bad = referenced - SAFE_TABLES
    if bad:
        raise NSError(400, f"Unknown or disallowed table(s): {sorted(bad)}.", "USER_ERROR")

    final_sql = q
    if "transaction" in referenced:
        final_sql = TRANSACTION_VIEW_SQL + final_sql
    paged_sql = f"SELECT * FROM ({final_sql}) AS _sub LIMIT :_limit OFFSET :_offset"
    count_sql = f"SELECT COUNT(*) FROM ({final_sql}) AS _sub"

    try:
        total = db.execute(text(count_sql)).scalar_one()
        rows = db.execute(text(paged_sql), {"_limit": limit, "_offset": offset}).mappings().all()
    except Exception as e:
        raise NSError(400, f"Query error: {e}", "USER_ERROR")

    items = [dict(r) for r in rows]
    base = "/services/rest/query/v1/suiteql"
    has_more = (offset + len(items)) < total
    links = [{"rel": "self", "href": f"{base}?limit={limit}&offset={offset}"}]
    if has_more:
        links.append({"rel": "next", "href": f"{base}?limit={limit}&offset={offset + limit}"})
    return {
        "links": links,
        "count": len(items),
        "hasMore": has_more,
        "offset": offset,
        "totalResults": total,
        "items": items,
    }
