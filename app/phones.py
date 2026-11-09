"""Phone normalisation (Part 1). Everything is stored as E.164, e.g. +966551234567."""
from __future__ import annotations

import re
from typing import Optional

from .countries import COUNTRIES, Country
from .errors import ApiError

_STRIP = re.compile(r"[ \-()]")
# [0-9], not \d: in Python \d also matches Arabic-Indic and other scripts' digits.
_SHAPE = re.compile(r"\+?[0-9]+")


def _invalid(msg: str = "Not a valid AE, SA or BH mobile number") -> ApiError:
    return ApiError(422, "INVALID_PHONE", msg)


def clean(raw: str) -> str:
    """Remove spaces, hyphens and round brackets; then only digits and one leading + may remain."""
    s = _STRIP.sub("", raw)
    if not _SHAPE.fullmatch(s):
        raise _invalid()
    return s


def _parse_international(s: str) -> Optional[tuple[Country, str]]:
    """'+<dial><mobile>' or '<dial><mobile>' -> (country, e164). None if not that shape."""
    digits = s[1:] if s.startswith("+") else s
    for c in COUNTRIES.values():
        if digits.startswith(c.dial) and c.mobile_re.fullmatch(digits[len(c.dial):]):
            return c, "+" + digits
    return None


def _national_countries(s: str) -> list[Country]:
    """Countries whose national mobile shape this fits. A '+' form is never national."""
    if s.startswith("+"):
        return []
    return [c for c in COUNTRIES.values() if c.national_re.fullmatch(s)]


def normalize_for_member(raw: str, country_code: str) -> str:
    """POST /members: international from any country, national read in the member's country."""
    s = clean(raw)
    intl = _parse_international(s)
    if intl:
        return intl[1]
    country = COUNTRIES[country_code]
    if country in _national_countries(s):
        return country.national_to_e164(s)
    raise _invalid()


def normalize_for_lookup(raw: str, country_code: Optional[str]) -> str:
    """GET /members/lookup."""
    s = clean(raw)
    intl = _parse_international(s)
    if intl:
        country, e164 = intl
        if country_code is not None and country_code != country.code:
            raise ApiError(
                422, "PHONE_COUNTRY_MISMATCH",
                f"Number has dial code +{country.dial} ({country.code}) but country={country_code}",
            )
        return e164
    fits = _national_countries(s)
    if not fits:
        raise _invalid()
    if country_code is None:
        raise ApiError(422, "PHONE_NEEDS_COUNTRY", "A national number needs a country parameter")
    country = COUNTRIES[country_code]
    if country not in fits:
        raise _invalid(f"Not a valid {country_code} national mobile number")
    return country.national_to_e164(s)
