"""Static country table. Everything country-specific lives here."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class Country:
    code: str
    dial: str
    currency: str
    vat_percent: int
    national_re: Pattern[str]  # full national mobile, e.g. 05XXXXXXXX
    mobile_re: Pattern[str]  # subscriber part after the dial code, e.g. 5XXXXXXXX
    trunk_zero: bool  # national form = "0" + subscriber part

    def national_to_e164(self, national: str) -> str:
        subscriber = national[1:] if self.trunk_zero else national
        return f"+{self.dial}{subscriber}"


COUNTRIES: dict[str, Country] = {
    "AE": Country("AE", "971", "AED", 5, re.compile(r"05\d{8}"), re.compile(r"5\d{8}"), True),
    "SA": Country("SA", "966", "SAR", 15, re.compile(r"05\d{8}"), re.compile(r"5\d{8}"), True),
    "BH": Country("BH", "973", "BHD", 10, re.compile(r"3\d{7}"), re.compile(r"3\d{7}"), False),
}

CURRENCIES = {c.currency for c in COUNTRIES.values()}
