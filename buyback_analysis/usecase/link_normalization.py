"""Rule-versioned normalization primitives used by plan linking."""

from __future__ import annotations

import re
import unicodedata


def normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    match = re.fullmatch(
        r"(\d{4})\s*(?:[-/.]|年)\s*(\d{1,2})\s*(?:[-/.]|月)\s*"
        r"(\d{1,2})\s*日?(?:[T\s].*)?",
        text,
    )
    if not match:
        return text
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def normalize_method(value: str | None) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", value).strip().lower()
    compact = re.sub(r"[\s_・()（）-]+", "", text)
    if "tostnet3" in compact or "立会外買付" in compact:
        return "tostnet-3"
    if "相対" in compact or "relativeacquisition" in compact:
        return "relative_acquisition"
    if "市場買付" in compact or "市場買い付け" in compact or "marketpurchase" in compact:
        return "market_purchase"
    return compact
