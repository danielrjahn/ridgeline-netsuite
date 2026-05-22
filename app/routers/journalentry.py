from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..auth import require_token
from ..db import get_db
from ..errors import NSError
from ..queryparser import apply_query_params, parse_q

router = APIRouter(
    prefix="/services/rest/record/v1/journalEntry",
    tags=["journalEntry"],
    dependencies=[Depends(require_token)],
)

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")


def _ref_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        rid = value.get("id")
        return int(rid) if rid is not None else None
    return int(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, ValueError):
        raise NSError(400, f"Invalid numeric value: {value!r}", "INVALID_FLD_VALUE")


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise NSError(400, "tranDate must be a YYYY-MM-DD string.", "INVALID_FLD_VALUE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise NSError(400, f"Invalid date {value!r}.", "INVALID_FLD_VALUE")


def _check_ref(db: Session, model, rec_id: int | None, kind: str):
    if rec_id is None:
        return
    if not db.get(model, rec_id):
        raise NSError(400, f"{kind} id {rec_id} does not exist.", "INVALID_KEY_OR_REF")


def _resolve_posting_period(db: Session, body: dict, tran_date: date) -> models.AccountingPeriod:
    pp_id = _ref_id(body.get("postingPeriod"))
    if pp_id is not None:
        period = db.get(models.AccountingPeriod, pp_id)
        if not period:
            raise NSError(400, f"postingPeriod id {pp_id} does not exist.", "INVALID_KEY_OR_REF")
        return period
    period = db.execute(
        select(models.AccountingPeriod).where(
            models.AccountingPeriod.startDate <= tran_date,
            models.AccountingPeriod.endDate >= tran_date,
        )
    ).scalar_one_or_none()
    if not period:
        raise NSError(400, f"No accounting period contains tranDate {tran_date.isoformat()}.", "USER_ERROR")
    return period


def _validate_and_build_lines(db: Session, raw_lines: list[dict]) -> list[models.JournalEntryLine]:
    if not isinstance(raw_lines, list) or len(raw_lines) < 2:
        raise NSError(400, "A journal entry must have at least 2 lines.", "USER_ERROR")
    built: list[models.JournalEntryLine] = []
    debit_total = Decimal("0")
    credit_total = Decimal("0")
    for idx, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise NSError(400, f"Line {idx} must be an object.", "USER_ERROR")
        acct_id = _ref_id(raw.get("account"))
        if acct_id is None:
            raise NSError(400, f"Line {idx} missing account.id.", "USER_ERROR")
        if not db.get(models.Account, acct_id):
            raise NSError(400, f"account id {acct_id} does not exist.", "INVALID_KEY_OR_REF")
        debit = _decimal_or_none(raw.get("debit"))
        credit = _decimal_or_none(raw.get("credit"))
        if (debit is None) == (credit is None):
            raise NSError(400, f"Line {idx} must have exactly one of debit or credit.", "USER_ERROR")
        if debit is not None and debit <= 0:
            raise NSError(400, f"Line {idx} debit must be > 0.", "USER_ERROR")
        if credit is not None and credit <= 0:
            raise NSError(400, f"Line {idx} credit must be > 0.", "USER_ERROR")
        entity_id = _ref_id(raw.get("entity"))
        dept_id = _ref_id(raw.get("department"))
        class_id = _ref_id(raw.get("class"))
        location_id = _ref_id(raw.get("location"))
        _check_ref(db, models.Vendor, entity_id, "entity (vendor)")
        _check_ref(db, models.Department, dept_id, "department")
        _check_ref(db, models.Classification, class_id, "class")
        _check_ref(db, models.Location, location_id, "location")
        if debit is not None:
            debit_total += debit
        if credit is not None:
            credit_total += credit
        built.append(
            models.JournalEntryLine(
                line=raw.get("line") or idx,
                account_id=acct_id,
                debit=debit,
                credit=credit,
                memo=raw.get("memo") or "",
                entity_id=entity_id,
                department_id=dept_id,
                class_id=class_id,
                location_id=location_id,
            )
        )
    if (debit_total - credit_total).copy_abs() > TOLERANCE:
        raise NSError(
            400,
            f"Debits and credits must be equal. Debit total {debit_total}, credit total {credit_total}.",
            "USER_ERROR",
        )
    return built


def _generate_tran_id(db: Session) -> str:
    max_id = db.execute(select(models.JournalEntry.id).order_by(models.JournalEntry.id.desc()).limit(1)).scalar_one_or_none() or 0
    return f"JE-{max_id + 1:04d}"


def _je_query(db: Session):
    return (
        db.query(models.JournalEntry)
        .options(selectinload(models.JournalEntry.lines))
    )


@router.get("")
def list_journal_entries(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    query = _je_query(db)
    if q:
        try:
            for clause in parse_q(q, models.JournalEntry):
                query = query.filter(clause)
        except ValueError as e:
            raise NSError(400, str(e), "USER_ERROR")
    query = apply_query_params(query, models.JournalEntry, dict(request.query_params))
    total = query.count()
    items = query.order_by(models.JournalEntry.id).offset(offset).limit(limit).all()
    base_url = f"{schemas.BASE_RECORD_PATH}/journalEntry"
    return schemas.list_envelope("journalEntry", items, total, offset, limit, base_url)


@router.get("/{rec_id}")
def get_journal_entry(
    rec_id: int,
    db: Session = Depends(get_db),
    expandSubResources: bool = Query(default=False),
):
    je = _je_query(db).filter(models.JournalEntry.id == rec_id).one_or_none()
    if not je:
        raise NSError(404, f"journalEntry {rec_id} not found.", "RCRD_DSNT_EXIST")
    return schemas.journalEntry_to_dict(je, expand=expandSubResources or True)


@router.post("")
async def create_journal_entry(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    if not isinstance(body, dict):
        raise NSError(400, "Request body must be a JSON object.", "USER_ERROR")
    tran_date = _parse_date(body.get("tranDate"))
    period = _resolve_posting_period(db, body, tran_date)
    if period.closed:
        raise NSError(
            409,
            f"Period {period.periodName} is closed; cannot post to it.",
            "PERIOD_CLOSED",
        )
    raw_line = body.get("line") or {}
    raw_lines = raw_line.get("items") if isinstance(raw_line, dict) else raw_line
    if raw_lines is None:
        raw_lines = body.get("lines")
    lines = _validate_and_build_lines(db, raw_lines or [])

    subsidiary_id = _ref_id(body.get("subsidiary")) or 1
    currency_id = _ref_id(body.get("currency")) or 1
    _check_ref(db, models.Subsidiary, subsidiary_id, "subsidiary")
    _check_ref(db, models.Currency, currency_id, "currency")

    reversal_date = body.get("reversalDate")
    if reversal_date:
        reversal_date = _parse_date(reversal_date)

    tran_id = body.get("tranId") or _generate_tran_id(db)

    je = models.JournalEntry(
        tranId=tran_id,
        tranDate=tran_date,
        subsidiary_id=subsidiary_id,
        currency_id=currency_id,
        exchangeRate=Decimal(str(body.get("exchangeRate") or 1)),
        memo=body.get("memo") or "",
        approved=bool(body.get("approved", True)),
        postingPeriod_id=period.id,
        reversalDate=reversal_date,
        isReversal=bool(body.get("isReversal", False)),
    )
    je.lines = lines
    db.add(je)
    db.commit()
    db.refresh(je)
    location = f"{schemas.BASE_RECORD_PATH}/journalEntry/{je.id}"
    return Response(
        status_code=204,
        headers={"Location": location, "X-NetSuite-PropertyName": "id", "X-NetSuite-PropertyValue": str(je.id)},
    )


@router.patch("/{rec_id}")
async def patch_journal_entry(rec_id: int, request: Request, db: Session = Depends(get_db)):
    je = _je_query(db).filter(models.JournalEntry.id == rec_id).one_or_none()
    if not je:
        raise NSError(404, f"journalEntry {rec_id} not found.", "RCRD_DSNT_EXIST")
    body = await request.json()
    if not isinstance(body, dict):
        raise NSError(400, "Request body must be a JSON object.", "USER_ERROR")

    if "tranDate" in body:
        je.tranDate = _parse_date(body["tranDate"])
        period = _resolve_posting_period(db, body, je.tranDate)
        if period.closed:
            raise NSError(409, f"Period {period.periodName} is closed.", "PERIOD_CLOSED")
        je.postingPeriod_id = period.id
    if "memo" in body:
        je.memo = body["memo"] or ""
    if "approved" in body:
        je.approved = bool(body["approved"])
    if "reversalDate" in body:
        je.reversalDate = _parse_date(body["reversalDate"]) if body["reversalDate"] else None
    if "tranId" in body and body["tranId"]:
        je.tranId = body["tranId"]
    if "line" in body or "lines" in body:
        raw_line = body.get("line") or body.get("lines") or {}
        raw_lines = raw_line.get("items") if isinstance(raw_line, dict) else raw_line
        new_lines = _validate_and_build_lines(db, raw_lines or [])
        je.lines = new_lines

    db.commit()
    db.refresh(je)
    return schemas.journalEntry_to_dict(je, expand=True)


@router.delete("/{rec_id}", status_code=204)
def delete_journal_entry(rec_id: int, db: Session = Depends(get_db)):
    je = db.get(models.JournalEntry, rec_id)
    if not je:
        raise NSError(404, f"journalEntry {rec_id} not found.", "RCRD_DSNT_EXIST")
    db.delete(je)
    db.commit()
    return Response(status_code=204)
