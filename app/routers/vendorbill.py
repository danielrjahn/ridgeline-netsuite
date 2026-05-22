from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..auth import require_token
from ..db import get_db
from ..errors import NSError
from ..queryparser import apply_query_params, parse_q

router = APIRouter(
    prefix="/services/rest/record/v1/vendorBill",
    tags=["vendorBill"],
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


def _parse_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise NSError(400, f"Invalid numeric value {value!r}.", "INVALID_FLD_VALUE")


def _check_ref(db: Session, model, rec_id: int | None, kind: str):
    if rec_id is None:
        return
    if not db.get(model, rec_id):
        raise NSError(400, f"{kind} id {rec_id} does not exist.", "INVALID_KEY_OR_REF")


def _build_expense_lines(db: Session, raw_lines: list[dict]) -> list[models.VendorBillExpenseLine]:
    if not isinstance(raw_lines, list) or not raw_lines:
        return []
    out = []
    for idx, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise NSError(400, f"expense line {idx} must be an object.", "USER_ERROR")
        acct_id = _ref_id(raw.get("account"))
        if acct_id is None:
            raise NSError(400, f"expense line {idx} missing account.id.", "USER_ERROR")
        _check_ref(db, models.Account, acct_id, "account")
        amount = _parse_decimal(raw.get("amount") or 0)
        dept_id = _ref_id(raw.get("department"))
        class_id = _ref_id(raw.get("class"))
        location_id = _ref_id(raw.get("location"))
        _check_ref(db, models.Department, dept_id, "department")
        _check_ref(db, models.Classification, class_id, "class")
        _check_ref(db, models.Location, location_id, "location")
        out.append(
            models.VendorBillExpenseLine(
                line=raw.get("line") or idx,
                account_id=acct_id,
                amount=amount,
                memo=raw.get("memo") or "",
                department_id=dept_id,
                class_id=class_id,
                location_id=location_id,
            )
        )
    return out


def _vb_query(db: Session):
    return db.query(models.VendorBill).options(selectinload(models.VendorBill.expense_lines))


@router.get("")
def list_vendor_bills(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    query = _vb_query(db)
    if q:
        try:
            for clause in parse_q(q, models.VendorBill):
                query = query.filter(clause)
        except ValueError as e:
            raise NSError(400, str(e), "USER_ERROR")
    query = apply_query_params(query, models.VendorBill, dict(request.query_params))
    total = query.count()
    items = query.order_by(models.VendorBill.id).offset(offset).limit(limit).all()
    base_url = f"{schemas.BASE_RECORD_PATH}/vendorBill"
    return schemas.list_envelope("vendorBill", items, total, offset, limit, base_url)


@router.get("/{rec_id}")
def get_vendor_bill(rec_id: int, db: Session = Depends(get_db)):
    b = _vb_query(db).filter(models.VendorBill.id == rec_id).one_or_none()
    if not b:
        raise NSError(404, f"vendorBill {rec_id} not found.", "RCRD_DSNT_EXIST")
    return schemas.vendorBill_to_dict(b, expand=True)


@router.post("")
async def create_vendor_bill(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    if not isinstance(body, dict):
        raise NSError(400, "Body must be a JSON object.", "USER_ERROR")
    entity_id = _ref_id(body.get("entity"))
    _check_ref(db, models.Vendor, entity_id, "entity (vendor)")
    if entity_id is None:
        raise NSError(400, "entity (vendor) is required.", "USER_ERROR")
    tran_date = _parse_date(body.get("tranDate"))
    if tran_date is None:
        raise NSError(400, "tranDate is required.", "USER_ERROR")
    period_id = _ref_id(body.get("postingPeriod"))
    if period_id is None:
        from sqlalchemy import select
        period = db.execute(
            select(models.AccountingPeriod).where(
                models.AccountingPeriod.startDate <= tran_date,
                models.AccountingPeriod.endDate >= tran_date,
            )
        ).scalar_one_or_none()
        if not period:
            raise NSError(400, "No accounting period contains tranDate.", "USER_ERROR")
        period_id = period.id
    else:
        _check_ref(db, models.AccountingPeriod, period_id, "postingPeriod")
    subsidiary_id = _ref_id(body.get("subsidiary")) or 1
    currency_id = _ref_id(body.get("currency")) or 1
    _check_ref(db, models.Subsidiary, subsidiary_id, "subsidiary")
    _check_ref(db, models.Currency, currency_id, "currency")

    raw_exp = body.get("expense") or {}
    raw_lines = raw_exp.get("items") if isinstance(raw_exp, dict) else raw_exp
    lines = _build_expense_lines(db, raw_lines or [])

    total = _parse_decimal(body.get("total") or sum((l.amount for l in lines), Decimal("0")))
    tran_id = body.get("tranId") or f"VB-{int(date.today().strftime('%Y%m%d'))}-{period_id}"

    bill = models.VendorBill(
        tranId=tran_id,
        entity_id=entity_id,
        tranDate=tran_date,
        dueDate=_parse_date(body.get("dueDate")) or tran_date,
        currency_id=currency_id,
        subsidiary_id=subsidiary_id,
        postingPeriod_id=period_id,
        memo=body.get("memo") or "",
        approvalStatus=body.get("approvalStatus") or "Approved",
        total=total,
    )
    bill.expense_lines = lines
    db.add(bill)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise NSError(400, f"Could not create vendorBill: {e}", "USER_ERROR")
    db.refresh(bill)
    location = f"{schemas.BASE_RECORD_PATH}/vendorBill/{bill.id}"
    return Response(status_code=204, headers={"Location": location})


@router.patch("/{rec_id}")
async def patch_vendor_bill(rec_id: int, request: Request, db: Session = Depends(get_db)):
    bill = _vb_query(db).filter(models.VendorBill.id == rec_id).one_or_none()
    if not bill:
        raise NSError(404, f"vendorBill {rec_id} not found.", "RCRD_DSNT_EXIST")
    body = await request.json()
    if not isinstance(body, dict):
        raise NSError(400, "Body must be a JSON object.", "USER_ERROR")

    if "tranId" in body and body["tranId"]:
        bill.tranId = body["tranId"]
    if "entity" in body:
        new_entity = _ref_id(body["entity"])
        _check_ref(db, models.Vendor, new_entity, "entity")
        bill.entity_id = new_entity
    if "tranDate" in body:
        bill.tranDate = _parse_date(body["tranDate"])
    if "dueDate" in body:
        bill.dueDate = _parse_date(body["dueDate"])
    if "postingPeriod" in body:
        pid = _ref_id(body["postingPeriod"])
        _check_ref(db, models.AccountingPeriod, pid, "postingPeriod")
        bill.postingPeriod_id = pid
    if "memo" in body:
        bill.memo = body["memo"] or ""
    if "approvalStatus" in body:
        bill.approvalStatus = body["approvalStatus"]
    if "total" in body:
        bill.total = _parse_decimal(body["total"])
    if "expense" in body:
        raw_exp = body["expense"]
        raw_lines = raw_exp.get("items") if isinstance(raw_exp, dict) else raw_exp
        bill.expense_lines = _build_expense_lines(db, raw_lines or [])

    db.commit()
    db.refresh(bill)
    return schemas.vendorBill_to_dict(bill, expand=True)


@router.delete("/{rec_id}", status_code=204)
def delete_vendor_bill(rec_id: int, db: Session = Depends(get_db)):
    bill = db.get(models.VendorBill, rec_id)
    if not bill:
        raise NSError(404, f"vendorBill {rec_id} not found.", "RCRD_DSNT_EXIST")
    db.delete(bill)
    db.commit()
    return Response(status_code=204)
