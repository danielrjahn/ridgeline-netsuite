from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..config import DEV_TOKEN
from ..db import get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["ui"])


def _ctx(request: Request, **extra) -> dict[str, Any]:
    return {"request": request, "token": DEV_TOKEN, **extra}


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    counts = {
        "Journal Entries": db.query(models.JournalEntry).count(),
        "Accounts": db.query(models.Account).count(),
        "Vendors": db.query(models.Vendor).count(),
        "Vendor Bills": db.query(models.VendorBill).count(),
        "Accounting Periods": db.query(models.AccountingPeriod).count(),
        "Currencies": db.query(models.Currency).count(),
        "Subsidiaries": db.query(models.Subsidiary).count(),
    }
    return templates.TemplateResponse("home.html", _ctx(request, counts=counts))


@router.get("/ui/journalEntries", response_class=HTMLResponse)
def ui_je_list(request: Request, db: Session = Depends(get_db)):
    items = (
        db.query(models.JournalEntry)
        .options(selectinload(models.JournalEntry.lines))
        .order_by(models.JournalEntry.tranDate.desc(), models.JournalEntry.id.desc())
        .all()
    )
    rows = []
    for je in items:
        debit_total = sum((li.debit for li in je.lines if li.debit), 0)
        rows.append({"je": je, "debit_total": debit_total})
    return templates.TemplateResponse("journalentries/list.html", _ctx(request, rows=rows))


@router.get("/ui/journalEntries/new", response_class=HTMLResponse)
def ui_je_new(request: Request, db: Session = Depends(get_db)):
    accounts = db.query(models.Account).order_by(models.Account.acctNumber).all()
    vendors = db.query(models.Vendor).order_by(models.Vendor.entityId).all()
    return templates.TemplateResponse(
        "journalentries/new.html",
        _ctx(request, accounts=accounts, vendors=vendors),
    )


@router.get("/ui/journalEntries/{rec_id}", response_class=HTMLResponse)
def ui_je_detail(rec_id: int, request: Request, db: Session = Depends(get_db)):
    je = (
        db.query(models.JournalEntry)
        .options(selectinload(models.JournalEntry.lines))
        .filter(models.JournalEntry.id == rec_id)
        .one_or_none()
    )
    if not je:
        return HTMLResponse(f"<h1>journalEntry {rec_id} not found.</h1>", status_code=404)
    accounts = {a.id: a for a in db.query(models.Account).all()}
    vendors = {v.id: v for v in db.query(models.Vendor).all()}
    period = db.get(models.AccountingPeriod, je.postingPeriod_id)
    return templates.TemplateResponse(
        "journalentries/detail.html",
        _ctx(request, je=je, accounts=accounts, vendors=vendors, period=period),
    )


@router.get("/ui/accounts", response_class=HTMLResponse)
def ui_accounts(request: Request, db: Session = Depends(get_db)):
    items = db.query(models.Account).order_by(models.Account.acctNumber).all()
    return templates.TemplateResponse("accounts/list.html", _ctx(request, items=items))


@router.get("/ui/accounts/new", response_class=HTMLResponse)
def ui_accounts_new(request: Request):
    return templates.TemplateResponse(
        "accounts/form.html",
        _ctx(request, item=None, mode="create"),
    )


@router.get("/ui/accounts/{rec_id}", response_class=HTMLResponse)
def ui_account_detail(rec_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(models.Account, rec_id)
    if not a:
        return HTMLResponse(f"<h1>account {rec_id} not found.</h1>", status_code=404)
    return templates.TemplateResponse(
        "accounts/form.html",
        _ctx(request, item=a, mode="edit"),
    )


@router.get("/ui/vendors", response_class=HTMLResponse)
def ui_vendors(request: Request, db: Session = Depends(get_db)):
    items = db.query(models.Vendor).order_by(models.Vendor.entityId).all()
    return templates.TemplateResponse("vendors/list.html", _ctx(request, items=items))


@router.get("/ui/vendors/new", response_class=HTMLResponse)
def ui_vendors_new(request: Request):
    return templates.TemplateResponse(
        "vendors/form.html", _ctx(request, item=None, mode="create")
    )


@router.get("/ui/vendors/{rec_id}", response_class=HTMLResponse)
def ui_vendor_detail(rec_id: int, request: Request, db: Session = Depends(get_db)):
    v = db.get(models.Vendor, rec_id)
    if not v:
        return HTMLResponse(f"<h1>vendor {rec_id} not found.</h1>", status_code=404)
    return templates.TemplateResponse(
        "vendors/form.html", _ctx(request, item=v, mode="edit")
    )


@router.get("/ui/vendorBills", response_class=HTMLResponse)
def ui_vendor_bills(request: Request, db: Session = Depends(get_db)):
    items = (
        db.query(models.VendorBill)
        .options(selectinload(models.VendorBill.expense_lines))
        .order_by(models.VendorBill.tranDate.desc(), models.VendorBill.id.desc())
        .all()
    )
    vendors = {v.id: v for v in db.query(models.Vendor).all()}
    return templates.TemplateResponse(
        "vendorbills/list.html", _ctx(request, items=items, vendors=vendors)
    )


@router.get("/ui/vendorBills/{rec_id}", response_class=HTMLResponse)
def ui_vendor_bill_detail(rec_id: int, request: Request, db: Session = Depends(get_db)):
    b = (
        db.query(models.VendorBill)
        .options(selectinload(models.VendorBill.expense_lines))
        .filter(models.VendorBill.id == rec_id)
        .one_or_none()
    )
    if not b:
        return HTMLResponse(f"<h1>vendorBill {rec_id} not found.</h1>", status_code=404)
    accounts = {a.id: a for a in db.query(models.Account).all()}
    vendors = {v.id: v for v in db.query(models.Vendor).all()}
    return templates.TemplateResponse(
        "vendorbills/detail.html",
        _ctx(request, b=b, accounts=accounts, vendors=vendors),
    )


@router.get("/ui/accountingPeriods", response_class=HTMLResponse)
def ui_periods(request: Request, db: Session = Depends(get_db)):
    items = db.query(models.AccountingPeriod).order_by(models.AccountingPeriod.startDate).all()
    return templates.TemplateResponse("periods/list.html", _ctx(request, items=items))
