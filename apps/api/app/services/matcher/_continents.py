"""ISO-3166 alpha-2 → continent code map (plan 18, Stage C location dimension).

Used by :mod:`.sme_ranker` to score location proximity:
  * Same country               → 1.0
  * Same continent             → 0.6
  * Different continent / unknown → 0.3
  * Virtual conferences        → 1.0 (computed in the ranker, not here)

Inline map covers the high-likelihood conference + SME locations for a
typical global team. Unknown codes default to "different continent" so
unmapped countries are explicit and easy to spot. Extend as the team's
footprint grows. Continent codes follow the convention: AF, AN, AS, EU,
NA, OC, SA.
"""

from __future__ import annotations

from typing import Final

COUNTRY_TO_CONTINENT: Final[dict[str, str]] = {
    # ---- North America ----
    "US": "NA",
    "CA": "NA",
    "MX": "NA",
    # ---- South America ----
    "BR": "SA",
    "AR": "SA",
    "CL": "SA",
    "CO": "SA",
    "PE": "SA",
    "UY": "SA",
    # ---- Europe ----
    "GB": "EU",
    "IE": "EU",
    "FR": "EU",
    "DE": "EU",
    "ES": "EU",
    "PT": "EU",
    "IT": "EU",
    "NL": "EU",
    "BE": "EU",
    "CH": "EU",
    "AT": "EU",
    "DK": "EU",
    "SE": "EU",
    "NO": "EU",
    "FI": "EU",
    "PL": "EU",
    "CZ": "EU",
    "RO": "EU",
    "GR": "EU",
    "TR": "EU",
    "EE": "EU",
    "LT": "EU",
    "LV": "EU",
    "HU": "EU",
    "BG": "EU",
    "HR": "EU",
    "SI": "EU",
    "SK": "EU",
    "IS": "EU",
    "UA": "EU",
    "RU": "EU",  # treated as EU for conference-circuit purposes
    # ---- Asia ----
    "JP": "AS",
    "KR": "AS",
    "CN": "AS",
    "TW": "AS",
    "HK": "AS",
    "SG": "AS",
    "IN": "AS",
    "ID": "AS",
    "MY": "AS",
    "TH": "AS",
    "VN": "AS",
    "PH": "AS",
    "AE": "AS",
    "SA": "AS",
    "IL": "AS",
    "PK": "AS",
    "BD": "AS",
    # ---- Oceania ----
    "AU": "OC",
    "NZ": "OC",
    # ---- Africa ----
    "ZA": "AF",
    "EG": "AF",
    "NG": "AF",
    "KE": "AF",
    "MA": "AF",
    "TN": "AF",
    "ET": "AF",
}


def continent_for(country_code: str | None) -> str | None:
    """Return the continent code for ``country_code`` or ``None`` if unknown."""
    if not country_code:
        return None
    return COUNTRY_TO_CONTINENT.get(country_code.upper())
