"""Strict input checks. Anything malformed -> 422 VALIDATION."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Optional

from .errors import validation

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MONTH = re.compile(r"(\d{4})-(\d{2})")


def obj(body: Any) -> dict:
    if not isinstance(body, dict):
        raise validation("Body must be a JSON object")
    return body


def _present(d: dict, key: str) -> Any:
    if key not in d or d[key] is None:
        raise validation(f"{key} is required")
    return d[key]


def string(d: dict, key: str, *, non_empty: bool = True) -> str:
    v = _present(d, key)
    if not isinstance(v, str):
        raise validation(f"{key} must be a string")
    if non_empty and v.strip() == "":
        raise validation(f"{key} must not be empty")
    return v


def integer(d: dict, key: str, *, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    v = _present(d, key)
    # bool is a subclass of int in Python; JSON true/false is not an integer.
    if type(v) is not int:
        raise validation(f"{key} must be an integer")
    if min_value is not None and v < min_value:
        raise validation(f"{key} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise validation(f"{key} must be <= {max_value}")
    return v


def one_of(d: dict, key: str, allowed: Iterable[str]) -> str:
    v = _present(d, key)
    allowed = set(allowed)
    if not isinstance(v, str) or v not in allowed:
        raise validation(f"{key} must be one of {sorted(allowed)}")
    return v


def parse_date(v: Any, key: str) -> date:
    if not isinstance(v, str) or not _DATE.fullmatch(v):
        raise validation(f"{key} must be a date YYYY-MM-DD")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise validation(f"{key} is not a real date")


def date_field(d: dict, key: str) -> date:
    return parse_date(_present(d, key), key)


def month_field(d: dict, key: str) -> tuple[int, int]:
    v = _present(d, key)
    m = _MONTH.fullmatch(v) if isinstance(v, str) else None
    if not m or not (1 <= int(m.group(2)) <= 12) or int(m.group(1)) < 1:
        raise validation(f"{key} must be a month YYYY-MM")
    return int(m.group(1)), int(m.group(2))
