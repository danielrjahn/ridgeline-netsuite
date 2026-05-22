"""Idempotent seed for the Ridgeline freight-accrual scenario.

If `data/freight_invoices_oct2025_mar2026_v2.csv` exists, vendor bills are aggregated
from it (one bill per carrier per service month). Otherwise a hardcoded representative
set is used so the demo always works.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import ROOT
from .db import SessionLocal, init_db

DATA_DIR = ROOT / "data"

CARRIERS = ["Peak Logistics", "Heartland Freight", "Coastal Express"]
CARRIER_PREFIX = {
    "Peak Logistics": "PK",
    "Heartland Freight": "HL",
    "Coastal Express": "CX",
}

CHART_OF_ACCOUNTS = [
    ("1000", "Operating Bank Account", "Bank"),
    ("2000", "Accounts Payable", "AcctPay"),
    ("2010", "Accrued Liabilities", "OthCurrLiab"),
    ("2011", "Accrued Freight", "OthCurrLiab"),
    ("4000", "Sales Revenue", "Income"),
    ("5000", "Cost of Goods Sold", "COGS"),
    ("6011", "Freight & Delivery Expense", "Expense"),
    ("6610", "Other Operating Expense", "Expense"),
]

PERIODS = [
    ("Oct 2025", date(2025, 10, 1), date(2025, 10, 31), True),
    ("Nov 2025", date(2025, 11, 1), date(2025, 11, 30), True),
    ("Dec 2025", date(2025, 12, 1), date(2025, 12, 31), True),
    ("Jan 2026", date(2026, 1, 1), date(2026, 1, 31), True),
    ("Feb 2026", date(2026, 2, 1), date(2026, 2, 28), True),
    ("Mar 2026", date(2026, 3, 1), date(2026, 3, 31), True),
    ("Apr 2026", date(2026, 4, 1), date(2026, 4, 30), False),
    ("May 2026", date(2026, 5, 1), date(2026, 5, 31), False),
]

FALLBACK_HISTORICAL_BILLS = [
    ("Peak Logistics", "Oct 2025", "PK-INV-2025-1001", date(2025, 11, 8), Decimal("31738.22")),
    ("Heartland Freight", "Oct 2025", "HL-INV-2025-0901", date(2025, 11, 5), Decimal("32800.00")),
    ("Coastal Express", "Oct 2025", "CX-INV-2025-0501", date(2025, 11, 6), Decimal("24100.00")),
    ("Peak Logistics", "Nov 2025", "PK-INV-2025-1101", date(2025, 12, 7), Decimal("31045.29")),
    ("Heartland Freight", "Nov 2025", "HL-INV-2025-1001", date(2025, 12, 5), Decimal("30150.00")),
    ("Coastal Express", "Nov 2025", "CX-INV-2025-0601", date(2025, 12, 6), Decimal("23250.00")),
    ("Peak Logistics", "Dec 2025", "PK-INV-2025-1201", date(2026, 1, 8), Decimal("33920.10")),
    ("Heartland Freight", "Dec 2025", "HL-INV-2025-1101", date(2026, 1, 6), Decimal("31875.00")),
    ("Coastal Express", "Dec 2025", "CX-INV-2025-0701", date(2026, 1, 7), Decimal("24560.00")),
    ("Peak Logistics", "Jan 2026", "PK-INV-2026-0101", date(2026, 2, 8), Decimal("29850.45")),
    ("Heartland Freight", "Jan 2026", "HL-INV-2026-0101", date(2026, 2, 6), Decimal("29200.00")),
    ("Coastal Express", "Jan 2026", "CX-INV-2026-0101", date(2026, 2, 6), Decimal("22950.00")),
    ("Peak Logistics", "Feb 2026", "PK-INV-2026-0201", date(2026, 3, 8), Decimal("30650.88")),
    ("Heartland Freight", "Feb 2026", "HL-INV-2026-0201", date(2026, 3, 5), Decimal("30050.00")),
    ("Coastal Express", "Feb 2026", "CX-INV-2026-0201", date(2026, 3, 6), Decimal("23700.00")),
    ("Peak Logistics", "Mar 2026", "PK-INV-2026-0301", date(2026, 4, 8), Decimal("32115.77")),
    ("Heartland Freight", "Mar 2026", "HL-INV-2026-0301", date(2026, 4, 6), Decimal("31420.00")),
    ("Coastal Express", "Mar 2026", "CX-INV-2026-0301", date(2026, 4, 7), Decimal("24400.00")),
]

# Historical accrual estimates from denise_accruals_v2.csv (Dr 6011 / Cr 2011).
HISTORICAL_ACCRUALS = {
    "Oct 2025": [("Peak Logistics", Decimal("29167")), ("Heartland Freight", Decimal("29767")), ("Coastal Express", Decimal("22500"))],
    "Nov 2025": [("Peak Logistics", Decimal("30246")), ("Heartland Freight", Decimal("29550")), ("Coastal Express", Decimal("22750"))],
    "Dec 2025": [("Peak Logistics", Decimal("32100")), ("Heartland Freight", Decimal("31250")), ("Coastal Express", Decimal("23800"))],
    "Jan 2026": [("Peak Logistics", Decimal("29000")), ("Heartland Freight", Decimal("28500")), ("Coastal Express", Decimal("22250"))],
    "Feb 2026": [("Peak Logistics", Decimal("29950")), ("Heartland Freight", Decimal("29400")), ("Coastal Express", Decimal("23000"))],
    "Mar 2026": [("Peak Logistics", Decimal("31500")), ("Heartland Freight", Decimal("30750")), ("Coastal Express", Decimal("23900"))],
}


def _get_or_create(db: Session, model, defaults: dict | None = None, **kwargs):
    obj = db.execute(select(model).filter_by(**kwargs)).scalar_one_or_none()
    if obj:
        return obj, False
    payload = {**kwargs, **(defaults or {})}
    obj = model(**payload)
    db.add(obj)
    db.flush()
    return obj, True


def _read_invoices_csv() -> list[tuple[str, str, str, date, Decimal]] | None:
    """Return list of (carrier, service_month_period_name, invoice_id, invoice_date, total).
    Aggregates by (carrier, service_month) summing totals across all line invoices."""
    path = DATA_DIR / "freight_invoices_oct2025_mar2026_v2.csv"
    if not path.exists():
        return None
    agg: dict[tuple[str, str], dict] = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["carrier"], row["service_month"])
            slot = agg.setdefault(key, {"total": Decimal("0"), "first_id": row["invoice_id"], "earliest": row["invoice_date"]})
            slot["total"] += Decimal(row["total_charge"])
            if row["invoice_date"] < slot["earliest"]:
                slot["earliest"] = row["invoice_date"]
                slot["first_id"] = row["invoice_id"]
    out = []
    for (carrier, service_month), slot in agg.items():
        period_name = service_month.replace("October", "Oct").replace("November", "Nov").replace("December", "Dec").replace("January", "Jan").replace("February", "Feb").replace("March", "Mar")
        invoice_date = date.fromisoformat(slot["earliest"])
        out.append((carrier, period_name, slot["first_id"], invoice_date, slot["total"].quantize(Decimal("0.01"))))
    return out


def seed(reset: bool = False) -> None:
    init_db()
    if reset:
        from .db import engine
        models.Base.metadata.drop_all(bind=engine)
        models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        usd, _ = _get_or_create(
            db,
            models.Currency,
            defaults={
                "name": "US Dollar",
                "symbol": "$",
                "isoCode": "USD",
                "exchangeRate": Decimal("1"),
                "isBaseCurrency": True,
            },
            id=1,
        )

        ridgeline, _ = _get_or_create(
            db,
            models.Subsidiary,
            defaults={"name": "Ridgeline Foods", "country": "US", "currency_id": usd.id, "isElimination": False},
            id=1,
        )

        ops, _ = _get_or_create(db, models.Department, defaults={"name": "Operations"}, id=1)
        logistics, _ = _get_or_create(db, models.Classification, defaults={"name": "Logistics"}, id=1)
        denver, _ = _get_or_create(db, models.Location, defaults={"name": "Denver HQ"}, id=1)

        accounts: dict[str, models.Account] = {}
        for idx, (num, name, atype) in enumerate(CHART_OF_ACCOUNTS, start=1):
            acct, _ = _get_or_create(
                db,
                models.Account,
                defaults={
                    "acctName": name,
                    "acctType": atype,
                    "subsidiary_id": ridgeline.id,
                    "currency_id": usd.id,
                },
                acctNumber=num,
            )
            accounts[num] = acct

        periods: dict[str, models.AccountingPeriod] = {}
        for idx, (name, start, end, closed) in enumerate(PERIODS, start=1):
            p, created = _get_or_create(
                db,
                models.AccountingPeriod,
                defaults={
                    "startDate": start,
                    "endDate": end,
                    "closed": closed,
                    "allLocked": closed,
                    "aplocked": closed,
                    "arlocked": closed,
                },
                periodName=name,
            )
            if not created:
                p.closed = closed
                p.allLocked = closed
                p.aplocked = closed
                p.arlocked = closed
            periods[name] = p

        vendors: dict[str, models.Vendor] = {}
        for carrier in CARRIERS:
            v, _ = _get_or_create(
                db,
                models.Vendor,
                defaults={
                    "companyName": carrier,
                    "isPerson": False,
                    "subsidiary_id": ridgeline.id,
                    "currency_id": usd.id,
                    "email": f"ap@{carrier.lower().replace(' ', '')}.example",
                },
                entityId=carrier,
            )
            vendors[carrier] = v

        bills_data = _read_invoices_csv() or [
            (carrier, period_name, inv_id, inv_date, total)
            for (carrier, period_name, inv_id, inv_date, total) in FALLBACK_HISTORICAL_BILLS
        ]
        freight_acct = accounts["6011"]
        for carrier, period_name, inv_id, inv_date, total in bills_data:
            vendor = vendors.get(carrier)
            period = periods.get(period_name)
            if not vendor or not period:
                continue
            bill, created = _get_or_create(
                db,
                models.VendorBill,
                defaults={
                    "entity_id": vendor.id,
                    "tranDate": inv_date,
                    "dueDate": inv_date,
                    "currency_id": usd.id,
                    "subsidiary_id": ridgeline.id,
                    "postingPeriod_id": period.id,
                    "memo": f"{carrier} freight for {period_name}",
                    "approvalStatus": "Approved",
                    "total": total,
                },
                tranId=inv_id,
            )
            if created:
                db.add(
                    models.VendorBillExpenseLine(
                        vendorBill_id=bill.id,
                        line=1,
                        account_id=freight_acct.id,
                        amount=total,
                        memo=f"Freight services {period_name}",
                        department_id=ops.id,
                        class_id=logistics.id,
                        location_id=denver.id,
                    )
                )

        accrued_acct = accounts["2011"]
        for period_name, items in HISTORICAL_ACCRUALS.items():
            period = periods.get(period_name)
            if not period:
                continue
            tran_id = f"JE-ACCR-{period.startDate.strftime('%Y%m')}"
            existing = db.execute(select(models.JournalEntry).filter_by(tranId=tran_id)).scalar_one_or_none()
            if existing:
                continue
            total = sum((amt for _, amt in items), Decimal("0"))
            je = models.JournalEntry(
                tranId=tran_id,
                tranDate=period.endDate,
                subsidiary_id=ridgeline.id,
                currency_id=usd.id,
                exchangeRate=Decimal("1"),
                memo=f"Freight accrual {period_name}",
                approved=True,
                postingPeriod_id=period.id,
                isReversal=False,
            )
            db.add(je)
            db.flush()
            for i, (carrier, amt) in enumerate(items, start=1):
                db.add(
                    models.JournalEntryLine(
                        journalEntry_id=je.id,
                        line=i,
                        account_id=freight_acct.id,
                        debit=amt,
                        credit=None,
                        memo=f"{carrier} freight accrual {period_name}",
                        entity_id=vendors[carrier].id,
                        department_id=ops.id,
                        class_id=logistics.id,
                        location_id=denver.id,
                    )
                )
            db.add(
                models.JournalEntryLine(
                    journalEntry_id=je.id,
                    line=len(items) + 1,
                    account_id=accrued_acct.id,
                    debit=None,
                    credit=total,
                    memo=f"Accrued freight {period_name}",
                    department_id=ops.id,
                    class_id=logistics.id,
                    location_id=denver.id,
                )
            )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    reset = "--reset" in sys.argv
    seed(reset=reset)
    msg = "Reset and seeded." if reset else "Seeded (idempotent)."
    print(msg)
