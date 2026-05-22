from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .db import Base


def _now():
    return datetime.utcnow()


class TimestampMixin:
    createdDate = Column(DateTime, default=_now, nullable=False)
    lastModifiedDate = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class Currency(Base, TimestampMixin):
    __tablename__ = "currency"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False, default="$")
    isoCode = Column(String, nullable=False, default="USD")
    exchangeRate = Column(Numeric(20, 8), nullable=False, default=1)
    isBaseCurrency = Column(Boolean, nullable=False, default=True)


class Subsidiary(Base, TimestampMixin):
    __tablename__ = "subsidiary"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    country = Column(String, nullable=False, default="US")
    currency_id = Column(Integer, ForeignKey("currency.id"))
    isElimination = Column(Boolean, nullable=False, default=False)
    isInactive = Column(Boolean, nullable=False, default=False)

    currency = relationship("Currency")


class Department(Base, TimestampMixin):
    __tablename__ = "department"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    isInactive = Column(Boolean, nullable=False, default=False)


class Classification(Base, TimestampMixin):
    __tablename__ = "classification"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    isInactive = Column(Boolean, nullable=False, default=False)


class Location(Base, TimestampMixin):
    __tablename__ = "location"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    isInactive = Column(Boolean, nullable=False, default=False)


class Account(Base, TimestampMixin):
    __tablename__ = "account"
    id = Column(Integer, primary_key=True)
    acctNumber = Column(String, nullable=False, index=True)
    acctName = Column(String, nullable=False)
    acctType = Column(String, nullable=False)
    description = Column(Text, default="")
    subsidiary_id = Column(Integer, ForeignKey("subsidiary.id"))
    currency_id = Column(Integer, ForeignKey("currency.id"))
    isInactive = Column(Boolean, nullable=False, default=False)


class AccountingPeriod(Base, TimestampMixin):
    __tablename__ = "accountingPeriod"
    id = Column(Integer, primary_key=True)
    periodName = Column(String, nullable=False)
    startDate = Column(Date, nullable=False)
    endDate = Column(Date, nullable=False)
    closed = Column(Boolean, nullable=False, default=False)
    allLocked = Column(Boolean, nullable=False, default=False)
    aplocked = Column(Boolean, nullable=False, default=False)
    arlocked = Column(Boolean, nullable=False, default=False)
    isQuarter = Column(Boolean, nullable=False, default=False)
    isYear = Column(Boolean, nullable=False, default=False)
    parent_id = Column(Integer, ForeignKey("accountingPeriod.id"), nullable=True)


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendor"
    id = Column(Integer, primary_key=True)
    entityId = Column(String, nullable=False)
    companyName = Column(String, nullable=False)
    isPerson = Column(Boolean, nullable=False, default=False)
    subsidiary_id = Column(Integer, ForeignKey("subsidiary.id"))
    currency_id = Column(Integer, ForeignKey("currency.id"))
    email = Column(String, default="")
    isInactive = Column(Boolean, nullable=False, default=False)


class JournalEntry(Base, TimestampMixin):
    __tablename__ = "journalEntry"
    id = Column(Integer, primary_key=True)
    tranId = Column(String, nullable=False, unique=True)
    tranDate = Column(Date, nullable=False)
    subsidiary_id = Column(Integer, ForeignKey("subsidiary.id"))
    currency_id = Column(Integer, ForeignKey("currency.id"))
    exchangeRate = Column(Numeric(20, 8), nullable=False, default=1)
    memo = Column(Text, default="")
    approved = Column(Boolean, nullable=False, default=True)
    postingPeriod_id = Column(Integer, ForeignKey("accountingPeriod.id"), nullable=False)
    reversalDate = Column(Date, nullable=True)
    isReversal = Column(Boolean, nullable=False, default=False)

    lines = relationship(
        "JournalEntryLine",
        back_populates="journalEntry",
        cascade="all, delete-orphan",
        order_by="JournalEntryLine.line",
    )


class JournalEntryLine(Base):
    __tablename__ = "journalEntryLine"
    id = Column(Integer, primary_key=True)
    journalEntry_id = Column(Integer, ForeignKey("journalEntry.id"), nullable=False)
    line = Column(Integer, nullable=False)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=False)
    debit = Column(Numeric(20, 2), nullable=True)
    credit = Column(Numeric(20, 2), nullable=True)
    memo = Column(Text, default="")
    entity_id = Column(Integer, ForeignKey("vendor.id"), nullable=True)
    department_id = Column(Integer, ForeignKey("department.id"), nullable=True)
    class_id = Column(Integer, ForeignKey("classification.id"), nullable=True)
    location_id = Column(Integer, ForeignKey("location.id"), nullable=True)

    journalEntry = relationship("JournalEntry", back_populates="lines")


class VendorBill(Base, TimestampMixin):
    __tablename__ = "vendorBill"
    id = Column(Integer, primary_key=True)
    tranId = Column(String, nullable=False, unique=True)
    entity_id = Column(Integer, ForeignKey("vendor.id"), nullable=False)
    tranDate = Column(Date, nullable=False)
    dueDate = Column(Date, nullable=True)
    currency_id = Column(Integer, ForeignKey("currency.id"))
    subsidiary_id = Column(Integer, ForeignKey("subsidiary.id"))
    postingPeriod_id = Column(Integer, ForeignKey("accountingPeriod.id"), nullable=False)
    memo = Column(Text, default="")
    approvalStatus = Column(String, nullable=False, default="Approved")
    total = Column(Numeric(20, 2), nullable=False, default=0)

    expense_lines = relationship(
        "VendorBillExpenseLine",
        back_populates="vendorBill",
        cascade="all, delete-orphan",
        order_by="VendorBillExpenseLine.line",
    )


class VendorBillExpenseLine(Base):
    __tablename__ = "vendorBillExpenseLine"
    id = Column(Integer, primary_key=True)
    vendorBill_id = Column(Integer, ForeignKey("vendorBill.id"), nullable=False)
    line = Column(Integer, nullable=False)
    account_id = Column(Integer, ForeignKey("account.id"), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False, default=0)
    memo = Column(Text, default="")
    department_id = Column(Integer, ForeignKey("department.id"), nullable=True)
    class_id = Column(Integer, ForeignKey("classification.id"), nullable=True)
    location_id = Column(Integer, ForeignKey("location.id"), nullable=True)

    vendorBill = relationship("VendorBill", back_populates="expense_lines")
