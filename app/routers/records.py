"""Generic record CRUD for simple NetSuite record types (no sublists).

journalEntry and vendorBill have their own routers because of sublist validation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import require_token
from ..db import get_db
from ..errors import NSError
from ..queryparser import apply_query_params, parse_q

router = APIRouter(
    prefix="/services/rest/record/v1",
    tags=["records"],
    dependencies=[Depends(require_token)],
)


def _ref_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        rid = value.get("id")
        return int(rid) if rid is not None else None
    return int(value)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise NSError(400, f"Invalid date {value!r}.", "INVALID_FLD_VALUE")


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise NSError(400, f"Invalid numeric value {value!r}.", "INVALID_FLD_VALUE")


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


CONFIG: dict[str, dict] = {
    "currency": {
        "model": models.Currency,
        "scalar": ["name", "symbol", "isoCode"],
        "decimal": ["exchangeRate"],
        "bool": ["isBaseCurrency"],
        "refs": {},
    },
    "subsidiary": {
        "model": models.Subsidiary,
        "scalar": ["name", "country"],
        "bool": ["isElimination", "isInactive"],
        "refs": {"currency": "currency_id"},
    },
    "department": {
        "model": models.Department,
        "scalar": ["name"],
        "bool": ["isInactive"],
        "refs": {},
    },
    "classification": {
        "model": models.Classification,
        "scalar": ["name"],
        "bool": ["isInactive"],
        "refs": {},
    },
    "location": {
        "model": models.Location,
        "scalar": ["name"],
        "bool": ["isInactive"],
        "refs": {},
    },
    "account": {
        "model": models.Account,
        "scalar": ["acctNumber", "acctName", "acctType", "description"],
        "bool": ["isInactive"],
        "refs": {"currency": "currency_id"},
        "multi_refs": {"subsidiary": "subsidiary_id"},
    },
    "accountingPeriod": {
        "model": models.AccountingPeriod,
        "scalar": ["periodName"],
        "date": ["startDate", "endDate"],
        "bool": ["closed", "allLocked", "aplocked", "arlocked", "isQuarter", "isYear"],
        "refs": {"parent": "parent_id"},
    },
    "vendor": {
        "model": models.Vendor,
        "scalar": ["entityId", "companyName", "email"],
        "bool": ["isPerson", "isInactive"],
        "refs": {"subsidiary": "subsidiary_id", "currency": "currency_id"},
    },
}


def _apply_body(db: Session, cfg: dict, obj, body: dict, partial: bool):
    for k in cfg.get("scalar", []):
        if k in body:
            setattr(obj, k, body[k])
    for k in cfg.get("date", []):
        if k in body:
            setattr(obj, k, _parse_date(body[k]))
    for k in cfg.get("decimal", []):
        if k in body:
            setattr(obj, k, _parse_decimal(body[k]))
    for k in cfg.get("bool", []):
        if k in body:
            setattr(obj, k, _parse_bool(body[k]))
    for body_key, fk in cfg.get("refs", {}).items():
        if body_key in body:
            setattr(obj, fk, _ref_id(body[body_key]))
    for body_key, fk in cfg.get("multi_refs", {}).items():
        if body_key in body:
            val = body[body_key]
            items = val.get("items") if isinstance(val, dict) else val
            if items:
                first = items[0]
                setattr(obj, fk, _ref_id(first))
            else:
                setattr(obj, fk, None)


def _resolve(record_type: str) -> dict:
    cfg = CONFIG.get(record_type)
    if not cfg:
        raise NSError(404, f"Unknown record type {record_type!r}.", "INVALID_RECORD_TYPE")
    return cfg


def _serialize(record_type: str, obj):
    return schemas.SERIALIZERS[record_type](obj)


@router.get("/{record_type}")
def list_records(
    record_type: str,
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    cfg = _resolve(record_type)
    model = cfg["model"]
    query = db.query(model)
    if q:
        try:
            for clause in parse_q(q, model):
                query = query.filter(clause)
        except ValueError as e:
            raise NSError(400, str(e), "USER_ERROR")
    query = apply_query_params(query, model, dict(request.query_params))
    total = query.count()
    items = query.order_by(model.id).offset(offset).limit(limit).all()
    base_url = f"{schemas.BASE_RECORD_PATH}/{record_type}"
    return schemas.list_envelope(record_type, items, total, offset, limit, base_url)


@router.get("/{record_type}/{rec_id}")
def get_record(record_type: str, rec_id: int, db: Session = Depends(get_db)):
    cfg = _resolve(record_type)
    obj = db.get(cfg["model"], rec_id)
    if not obj:
        raise NSError(404, f"{record_type} {rec_id} not found.", "RCRD_DSNT_EXIST")
    return _serialize(record_type, obj)


@router.post("/{record_type}")
async def create_record(record_type: str, request: Request, db: Session = Depends(get_db)):
    cfg = _resolve(record_type)
    body = await request.json()
    if not isinstance(body, dict):
        raise NSError(400, "Body must be a JSON object.", "USER_ERROR")
    model = cfg["model"]
    obj = model()
    _apply_body(db, cfg, obj, body, partial=False)
    db.add(obj)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise NSError(400, f"Could not create {record_type}: {e}", "USER_ERROR")
    db.refresh(obj)
    location = f"{schemas.BASE_RECORD_PATH}/{record_type}/{obj.id}"
    return Response(status_code=204, headers={"Location": location})


@router.patch("/{record_type}/{rec_id}")
async def patch_record(record_type: str, rec_id: int, request: Request, db: Session = Depends(get_db)):
    cfg = _resolve(record_type)
    obj = db.get(cfg["model"], rec_id)
    if not obj:
        raise NSError(404, f"{record_type} {rec_id} not found.", "RCRD_DSNT_EXIST")
    body = await request.json()
    if not isinstance(body, dict):
        raise NSError(400, "Body must be a JSON object.", "USER_ERROR")
    _apply_body(db, cfg, obj, body, partial=True)
    db.commit()
    db.refresh(obj)
    return _serialize(record_type, obj)


@router.delete("/{record_type}/{rec_id}", status_code=204)
def delete_record(record_type: str, rec_id: int, db: Session = Depends(get_db)):
    cfg = _resolve(record_type)
    obj = db.get(cfg["model"], rec_id)
    if not obj:
        raise NSError(404, f"{record_type} {rec_id} not found.", "RCRD_DSNT_EXIST")
    db.delete(obj)
    db.commit()
    return Response(status_code=204)
