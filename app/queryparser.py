"""Minimal NetSuite-style q= expression parser.

Supports `field OP value [AND field OP value ...]` where OP is one of:
  EQUALS, NOT_EQUALS, START_WITH, CONTAINS,
  ON_OR_AFTER, ON_OR_BEFORE, AFTER, BEFORE,
  =, !=, >=, <=, >, <

Values are quoted strings ("...") or bare numbers. References are matched by id;
i.e. `entity EQUALS "3"` filters by the foreign-key column entity_id == 3.
Returns a list of SQLAlchemy filter expressions to AND together.
"""
from __future__ import annotations

import re
from datetime import date
from sqlalchemy import and_

_OP_ALIASES = {
    "EQUALS": "eq",
    "=": "eq",
    "NOT_EQUALS": "ne",
    "!=": "ne",
    "START_WITH": "startswith",
    "CONTAINS": "contains",
    "ON_OR_AFTER": "ge",
    "ON_OR_BEFORE": "le",
    "AFTER": "gt",
    "BEFORE": "lt",
    ">=": "ge",
    "<=": "le",
    ">": "gt",
    "<": "lt",
}

_REF_FIELDS = {
    "entity": "entity_id",
    "account": "account_id",
    "subsidiary": "subsidiary_id",
    "currency": "currency_id",
    "postingPeriod": "postingPeriod_id",
    "department": "department_id",
    "class": "class_id",
    "location": "location_id",
    "parent": "parent_id",
}


def _coerce(col, raw: str):
    py_type = col.type.python_type
    if py_type is date:
        return date.fromisoformat(raw)
    if py_type is bool:
        return raw.lower() in ("true", "1", "yes")
    if py_type is int:
        return int(raw)
    if py_type is float:
        return float(raw)
    return raw


def _column_for(model, field: str):
    if field in _REF_FIELDS:
        field = _REF_FIELDS[field]
    return getattr(model, field, None)


def parse_q(q: str, model):
    """Return a list of SQLAlchemy filter expressions.

    Raises ValueError on unrecognized fields or operators (caller should 400).
    """
    if not q:
        return []
    clauses = re.split(r"\s+AND\s+", q.strip())
    out = []
    for clause in clauses:
        m = re.match(r'^\s*(\w+)\s+(EQUALS|NOT_EQUALS|START_WITH|CONTAINS|ON_OR_AFTER|ON_OR_BEFORE|AFTER|BEFORE)\s+"(.*?)"\s*$', clause)
        if not m:
            m = re.match(r'^\s*(\w+)\s+(EQUALS|NOT_EQUALS|START_WITH|CONTAINS|ON_OR_AFTER|ON_OR_BEFORE|AFTER|BEFORE)\s+(\S+)\s*$', clause)
        if not m:
            m = re.match(r'^\s*(\w+)\s*(=|!=|>=|<=|>|<)\s*"(.*?)"\s*$', clause)
        if not m:
            m = re.match(r'^\s*(\w+)\s*(=|!=|>=|<=|>|<)\s*(\S+)\s*$', clause)
        if not m:
            raise ValueError(f"Could not parse clause: {clause!r}")
        field, op_token, raw_value = m.group(1), m.group(2), m.group(3)
        op = _OP_ALIASES.get(op_token)
        if not op:
            raise ValueError(f"Unknown operator: {op_token!r}")
        col = _column_for(model, field)
        if col is None:
            raise ValueError(f"Unknown field for q filter: {field!r}")
        value = _coerce(col, raw_value)
        if op == "eq":
            out.append(col == value)
        elif op == "ne":
            out.append(col != value)
        elif op == "gt":
            out.append(col > value)
        elif op == "ge":
            out.append(col >= value)
        elif op == "lt":
            out.append(col < value)
        elif op == "le":
            out.append(col <= value)
        elif op == "startswith":
            out.append(col.like(f"{value}%"))
        elif op == "contains":
            out.append(col.like(f"%{value}%"))
    return out


def apply_query_params(query, model, extra_params: dict):
    """Apply ?field=value fallback filters from query string, ignoring known controls."""
    skip = {"q", "limit", "offset", "expandSubResources"}
    for k, v in extra_params.items():
        if k in skip:
            continue
        col = _column_for(model, k)
        if col is None:
            continue
        try:
            value = _coerce(col, v)
        except (ValueError, TypeError):
            continue
        query = query.filter(col == value)
    return query
