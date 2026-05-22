"""Shape SQLAlchemy rows into NetSuite REST Record API payloads.

NetSuite-isms preserved:
- ids are strings (even though they're numeric)
- references are { "id": "5", "refName": "..." }
- dates are YYYY-MM-DD; timestamps are ISO-8601
- sublists are { "items": [...] }
- each record carries a `links: [{ rel: "self", href: ... }]` array
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from . import models

BASE_RECORD_PATH = "/services/rest/record/v1"


def _money(v) -> float | None:
    if v is None:
        return None
    return float(Decimal(v))


def _date(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()


def _ts(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.replace(microsecond=0).isoformat() + "Z"
    return d.isoformat()


def _self_link(record_type: str, rec_id) -> list[dict]:
    return [{"rel": "self", "href": f"{BASE_RECORD_PATH}/{record_type}/{rec_id}"}]


def _ref(rec_id, refName: str | None = None) -> dict | None:
    if rec_id is None:
        return None
    out = {"id": str(rec_id)}
    if refName is not None:
        out["refName"] = refName
    return out


def currency_to_dict(c: models.Currency) -> dict:
    return {
        "links": _self_link("currency", c.id),
        "id": str(c.id),
        "name": c.name,
        "symbol": c.symbol,
        "currencySymbol": c.symbol,
        "isoCode": c.isoCode,
        "exchangeRate": float(c.exchangeRate),
        "isBaseCurrency": c.isBaseCurrency,
        "createdDate": _ts(c.createdDate),
        "lastModifiedDate": _ts(c.lastModifiedDate),
    }


def subsidiary_to_dict(s: models.Subsidiary) -> dict:
    return {
        "links": _self_link("subsidiary", s.id),
        "id": str(s.id),
        "name": s.name,
        "country": s.country,
        "currency": _ref(s.currency_id, s.currency.isoCode if s.currency else None),
        "isElimination": s.isElimination,
        "isInactive": s.isInactive,
        "createdDate": _ts(s.createdDate),
        "lastModifiedDate": _ts(s.lastModifiedDate),
    }


def department_to_dict(d: models.Department) -> dict:
    return {
        "links": _self_link("department", d.id),
        "id": str(d.id),
        "name": d.name,
        "isInactive": d.isInactive,
        "createdDate": _ts(d.createdDate),
        "lastModifiedDate": _ts(d.lastModifiedDate),
    }


def classification_to_dict(c: models.Classification) -> dict:
    return {
        "links": _self_link("classification", c.id),
        "id": str(c.id),
        "name": c.name,
        "isInactive": c.isInactive,
        "createdDate": _ts(c.createdDate),
        "lastModifiedDate": _ts(c.lastModifiedDate),
    }


def location_to_dict(loc: models.Location) -> dict:
    return {
        "links": _self_link("location", loc.id),
        "id": str(loc.id),
        "name": loc.name,
        "isInactive": loc.isInactive,
        "createdDate": _ts(loc.createdDate),
        "lastModifiedDate": _ts(loc.lastModifiedDate),
    }


def account_to_dict(a: models.Account) -> dict:
    return {
        "links": _self_link("account", a.id),
        "id": str(a.id),
        "acctNumber": a.acctNumber,
        "acctName": a.acctName,
        "acctType": {"id": a.acctType, "refName": a.acctType},
        "description": a.description or "",
        "subsidiary": {"items": [_ref(a.subsidiary_id)]} if a.subsidiary_id else {"items": []},
        "currency": _ref(a.currency_id),
        "isInactive": a.isInactive,
        "createdDate": _ts(a.createdDate),
        "lastModifiedDate": _ts(a.lastModifiedDate),
    }


def accountingPeriod_to_dict(p: models.AccountingPeriod) -> dict:
    return {
        "links": _self_link("accountingPeriod", p.id),
        "id": str(p.id),
        "periodName": p.periodName,
        "startDate": _date(p.startDate),
        "endDate": _date(p.endDate),
        "closed": p.closed,
        "allLocked": p.allLocked,
        "aplocked": p.aplocked,
        "arlocked": p.arlocked,
        "isQuarter": p.isQuarter,
        "isYear": p.isYear,
        "parent": _ref(p.parent_id),
        "createdDate": _ts(p.createdDate),
        "lastModifiedDate": _ts(p.lastModifiedDate),
    }


def vendor_to_dict(v: models.Vendor) -> dict:
    return {
        "links": _self_link("vendor", v.id),
        "id": str(v.id),
        "entityId": v.entityId,
        "companyName": v.companyName,
        "isPerson": v.isPerson,
        "subsidiary": _ref(v.subsidiary_id),
        "currency": _ref(v.currency_id),
        "email": v.email or "",
        "isInactive": v.isInactive,
        "createdDate": _ts(v.createdDate),
        "lastModifiedDate": _ts(v.lastModifiedDate),
    }


def journalEntryLine_to_dict(li: models.JournalEntryLine, expand: bool = True) -> dict:
    return {
        "line": li.line,
        "account": _ref(li.account_id),
        "debit": _money(li.debit),
        "credit": _money(li.credit),
        "memo": li.memo or "",
        "entity": _ref(li.entity_id),
        "department": _ref(li.department_id),
        "class": _ref(li.class_id),
        "location": _ref(li.location_id),
    }


def journalEntry_to_dict(je: models.JournalEntry, expand: bool = True) -> dict:
    body: dict[str, Any] = {
        "links": _self_link("journalEntry", je.id),
        "id": str(je.id),
        "tranId": je.tranId,
        "tranDate": _date(je.tranDate),
        "subsidiary": _ref(je.subsidiary_id),
        "currency": _ref(je.currency_id),
        "exchangeRate": float(je.exchangeRate),
        "memo": je.memo or "",
        "approved": je.approved,
        "postingPeriod": _ref(je.postingPeriod_id),
        "reversalDate": _date(je.reversalDate),
        "isReversal": je.isReversal,
        "createdDate": _ts(je.createdDate),
        "lastModifiedDate": _ts(je.lastModifiedDate),
    }
    if expand:
        body["line"] = {"items": [journalEntryLine_to_dict(li) for li in je.lines]}
    else:
        body["line"] = {
            "links": [
                {
                    "rel": "self",
                    "href": f"{BASE_RECORD_PATH}/journalEntry/{je.id}?expandSubResources=true",
                }
            ]
        }
    return body


def vendorBillExpenseLine_to_dict(li: models.VendorBillExpenseLine) -> dict:
    return {
        "line": li.line,
        "account": _ref(li.account_id),
        "amount": _money(li.amount),
        "memo": li.memo or "",
        "department": _ref(li.department_id),
        "class": _ref(li.class_id),
        "location": _ref(li.location_id),
    }


def vendorBill_to_dict(b: models.VendorBill, expand: bool = True) -> dict:
    body: dict[str, Any] = {
        "links": _self_link("vendorBill", b.id),
        "id": str(b.id),
        "tranId": b.tranId,
        "entity": _ref(b.entity_id),
        "tranDate": _date(b.tranDate),
        "dueDate": _date(b.dueDate),
        "currency": _ref(b.currency_id),
        "subsidiary": _ref(b.subsidiary_id),
        "postingPeriod": _ref(b.postingPeriod_id),
        "memo": b.memo or "",
        "approvalStatus": b.approvalStatus,
        "total": _money(b.total),
        "createdDate": _ts(b.createdDate),
        "lastModifiedDate": _ts(b.lastModifiedDate),
    }
    if expand:
        body["expense"] = {"items": [vendorBillExpenseLine_to_dict(li) for li in b.expense_lines]}
    else:
        body["expense"] = {
            "links": [
                {
                    "rel": "self",
                    "href": f"{BASE_RECORD_PATH}/vendorBill/{b.id}?expandSubResources=true",
                }
            ]
        }
    return body


SERIALIZERS = {
    "currency": currency_to_dict,
    "subsidiary": subsidiary_to_dict,
    "department": department_to_dict,
    "classification": classification_to_dict,
    "location": location_to_dict,
    "account": account_to_dict,
    "accountingPeriod": accountingPeriod_to_dict,
    "vendor": vendor_to_dict,
    "journalEntry": journalEntry_to_dict,
    "vendorBill": vendorBill_to_dict,
}


def list_envelope(record_type: str, items: list, total: int, offset: int, limit: int, base_url: str) -> dict:
    has_more = (offset + len(items)) < total
    refs = [
        {"links": _self_link(record_type, it.id), "id": str(it.id)}
        for it in items
    ]
    links = [{"rel": "self", "href": f"{base_url}?limit={limit}&offset={offset}"}]
    if has_more:
        next_offset = offset + limit
        links.append({"rel": "next", "href": f"{base_url}?limit={limit}&offset={next_offset}"})
    if offset > 0:
        prev_offset = max(0, offset - limit)
        links.append({"rel": "prev", "href": f"{base_url}?limit={limit}&offset={prev_offset}"})
    return {
        "links": links,
        "count": len(refs),
        "hasMore": has_more,
        "offset": offset,
        "totalResults": total,
        "items": refs,
    }
