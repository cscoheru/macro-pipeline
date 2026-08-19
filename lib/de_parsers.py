"""Parsers for Germany macro releases (Destatis English).

Destatis press releases (https://www.destatis.de/EN/Press/.../PE2x_xxx_xxx.html)
follow a consistent prose pattern:
  "<Topic> <period>: +X.X% on the previous <period>"     (headline)
  "  +X.X% on the same <period> a year earlier"          (subtitle)
  "... <Topic> ... <month> <year> +X.X% on the previous month ..."
  "... <Topic> ... <month> <year> <+X.X%> on the same month a year earlier ..."

The MoM/YoY values sit BEFORE the comparative phrase ("on the previous month" /
"on the same month a year earlier"), not after. cn/jp parsers were built for the
inverse "<label>... <pct>%" pattern, so DE adds an `extract_pct_before_en`
helper.

Period detection: the page TITLE always carries the data month/quarter
("Inflation rate at +2.8% in July 2026", "Gross domestic product in the 2nd
quarter of 2026"). The body contains many other dates (release date, prior
year reference) that pollute `normalize_period_de`. We extract the period from
the title only.
"""
import re

from jp_parsers import (
    extract_metric_en, extract_pct_only_en, extract_value_at_en,
    _signed, _to_num, _extract_year, normalize_period_jp,
)


# English quarter notation — Destatis titles use "1st/2nd/3rd/4th quarter of
# YYYY" plus occasional bare "Q1 2026".
_QUARTER_RE = re.compile(
    r"\b([1-4])(?:st|nd|rd|th)\s*quarter\s+of\s+(20\d{2})\b", re.I,
)
_QUARTER_ALT = re.compile(r"\b(Q[1-4])\s*,?\s*(20\d{2})?\b", re.I)


def _month_to_num(name):
    return {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
    }.get(name.lower())


def normalize_period_de_title(title):
    """Period string from a Destatis press release TITLE only.

    Returns 'YYYY-Qn' for quarterly (GDP), 'YYYY-MM' for monthly. The body
    text is intentionally excluded — Destatis body prose mentions release
    dates and prior-year comparisons that pollute the inference.
    """
    if not title:
        return None
    m = _QUARTER_RE.search(title)
    if m:
        return f"{m.group(2)}-q{int(m.group(1))}"
    m = _QUARTER_ALT.search(title)
    if m:
        qnum = int(m.group(1)[1])
        yr = m.group(2) or _extract_year(title) or ""
        return f"{yr}-q{qnum}"
    # Monthly: "<Month> YYYY" (English month name with full 4-digit year)
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\b\s*,?\s*(20\d{2})\b",
        title, re.I,
    )
    if m:
        return f"{m.group(2)}-{_month_to_num(m.group(1))}"
    return None


def extract_pct_before_en(text, label, direction_label=None):
    """'<pct>% <label>' — number comes BEFORE the anchor phrase.

    DE press releases put the percent sign first, then the comparison label:
        "+0.2% on the previous month"
        "+5.3% on the same month a year earlier"
        "0.5% lower than in the same month a year earlier"

    If `direction_label` is set (e.g. "lower than"), the regex anchors on
    "<direction_label> in" so we know the sign: "lower" → negative,
    "higher" → positive. The captured number stays absolute.
    """
    if direction_label:
        # Match: "<pct>% <direction_label> in <...>"
        pat = re.compile(
            r"([-+]?\d+\.?\d*)\s*%\s*" + re.escape(direction_label)
            + r"\s+in\b",
            re.IGNORECASE | re.DOTALL,
        )
        m = pat.search(text)
        if not m:
            return None
        val = _to_num(m.group(1))
        if val is None:
            return None
        if "lower" in direction_label.lower() or "less" in direction_label.lower():
            val = -abs(val)
        else:
            val = abs(val)
        return {"value": None, "yoy": val, "unit": "% YoY"}
    pat = re.compile(
        r"([-+]?\d+\.?\d*)\s*%\s*" + re.escape(label),
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return None
    return {"value": None, "yoy": _to_num(m.group(1)), "unit": "% YoY"}


def _finish_de(title, text, metrics, names):
    period = normalize_period_de_title(title)
    if not period:
        raise ValueError(f"cannot determine period from title: {title!r}")
    out = {k: {"name": names[k], **v} for k, v in metrics.items() if v}
    if not out:
        raise ValueError("no metrics extracted")
    return {"period": period, "metrics": out}


# ---------------------------------------------------------------------------
# CPI / Inflation (Destatis reports "Inflation rate" — same series)
# ---------------------------------------------------------------------------
_CPI_NAMES = {"cpi_yoy": "CPI 同比", "cpi_mom": "CPI 环比"}


def parse_de_cpi(title, text, url=None):
    # Title: "Inflation rate at +2.8% in July 2026" → YoY headline.
    # MoM: subtitle "+X.X% on the previous month" or first body mention.
    metrics = {
        "cpi_yoy": extract_pct_only_en(text, "Inflation rate"),
        "cpi_mom": extract_pct_before_en(text, "on the previous month"),
    }
    return _finish_de(title, text, metrics, _CPI_NAMES)


# ---------------------------------------------------------------------------
# Producer / Wholesale Price Index
# Destatis labels the wholesale (Erzeugerpreise) as "Wholesale prices" in
# English press releases.
# ---------------------------------------------------------------------------
_PPI_NAMES = {"ppi_yoy": "PPI 同比", "ppi_mom": "PPI 环比"}


def parse_de_ppi(title, text, url=None):
    metrics = {
        # YoY is the headline: "Wholesale prices in July 2026: +5.3% on July 2025"
        "ppi_yoy": extract_pct_only_en(text, "Wholesale prices"),
        # MoM sits in the subtitle block: "+0.2% on the previous month"
        "ppi_mom": extract_pct_before_en(text, "on the previous month"),
    }
    return _finish_de(title, text, metrics, _PPI_NAMES)


# ---------------------------------------------------------------------------
# Unemployment (Destatis reports employment change; the body gives YoY
# change: "0.5% lower than in the same month a year earlier")
# ---------------------------------------------------------------------------
_UNRATE_NAMES = {"employment_yoy": "就业人数同比变化"}


def parse_de_unrate(title, text, url=None):
    # Destatis uses "X.X% lower than in the same month a year earlier" for
    # declines and "X.X% higher than in the same month a year earlier" for
    # gains. Try "lower" first (matches recent releases) then fall back to
    # "higher" — if both fail the page layout changed and the parse gate
    # upstream will record a failure rather than silently write null.
    metrics = {
        "employment_yoy": (
            extract_pct_before_en(text, "", direction_label="lower than")
            or extract_pct_before_en(text, "", direction_label="higher than")
        ),
    }
    return _finish_de(title, text, metrics, _UNRATE_NAMES)


# ---------------------------------------------------------------------------
# GDP (quarterly): Destatis subtitle is
#   "Gross domestic product (GDP), 2nd quarter of 2026
#    +0.2% on the previous quarter (price, seasonally and calendar adjusted)
#    +0.9% on the same quarter a year earlier (price adjusted)"
# ---------------------------------------------------------------------------
_GDP_NAMES = {"gdp_qoq": "实际 GDP 环比", "gdp_yoy": "实际 GDP 同比"}


def parse_de_gdp(title, text, url=None):
    metrics = {
        # YoY is the headline; subtitle gives QoQ.
        "gdp_qoq": extract_pct_before_en(text, "on the previous quarter"),
        "gdp_yoy": extract_pct_before_en(
            text, "on the same quarter a year earlier"),
    }
    return _finish_de(title, text, metrics, _GDP_NAMES)