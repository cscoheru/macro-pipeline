"""Parsers for Japan macro releases (BOJ / Statistics Bureau / Cabinet Office).

Input: clean text (HTML stripped by fetcher.strip_tags).
Output: {"period": "YYYY-MM" or "YYYY-Qn", "metrics": {key: {name, unit, value, yoy}}}

English-language pages follow a similar pattern to cn_parsers:
  <label> ... <number><unit> ... YoY <direction> <pct>%      (level + YoY)
  <label> ... <direction> ... <pct>%                          (YoY only, e.g. CGPI)
  <label> ... was <number>%                                   (level only, e.g. unemployment)

The English release pages for BOJ/e-Stat/Cabinet Office are structured, so
extract_metric_en / extract_pct_only_en / extract_value_at_en reuse the same
shape as cn_parsers — adapted for English direction words.
"""
import re

# English direction words used by BOJ / e-Stat / Cabinet Office releases.
# "down" / "up" appear as standalone adverbs; longer phrases are preferred
# where ambiguous (e.g. "advanced" can mean rose or merely progressed).
_DIRECTIONS = (
    "rose", "fell", "increased", "decreased", "climbed", "dropped",
    "edged up", "edged down", "was unchanged", "was flat", "jumped",
    "slumped", "grew", "contracted", "advanced", "retreated",
    "accelerated", "slowed", "down", "up",
)

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

_NEGATIVE = {"fell", "decreased", "dropped", "edged down",
             "was unchanged", "was flat", "slumped", "contracted",
             "retreated", "slowed", "down"}


def _to_num(s):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _signed(pct, direction):
    if pct is None:
        return None
    return -abs(pct) if direction in _NEGATIVE else pct


def _extract_year(title_or_text):
    m = re.search(r"(20\d{2})", title_or_text)
    return m.group(1) if m else None


def normalize_period_jp(year, text):
    """Detect period string from a Japan release.

    Returns 'YYYY-MM' for monthly releases, 'YYYY-Qn' for quarterly GDP.
    Returns None if neither can be inferred (caller treats as parse error).
    """
    if not year:
        # Empty year must not produce "-07" / "-q2" — those would write
        # degenerate periods to the ledger and pass the unique-key check.
        return None
    # Quarterly: Cabinet Office titles use English fiscal-quarter form like
    # "Quarterly Estimates of GDP for Apr.-Jun. 2026 (The First preliminary)".
    # The PDF edition spells months out: "for April - June 2026".
    qmap = [
        (r"Jan(?:uary)?\.?\s*[-–]\s*Mar(?:ch)?\.?", "q1"),
        (r"Apr(?:il)?\.?\s*[-–]\s*Jun(?:e)?\.?", "q2"),
        (r"Jul(?:y)?\.?\s*[-–]\s*Sep(?:tember)?\.?", "q3"),
        (r"Oct(?:ober)?\.?\s*[-–]\s*Dec(?:ember)?\.?", "q4"),
    ]
    for pat, q in qmap:
        if re.search(pat, text, re.I):
            return f"{year}-{q}"
    # Quarterly (alternative): explicit "Q1" / "Q2" tokens in text.
    m = re.search(r"\b(Q[1-4])\b", text)
    if m:
        return f"{year}-{m.group(1).lower()}"
    # Monthly: "<Month> 20XX" or "<Month>, 20XX"
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\b[,\s]+{year}\b", text, re.IGNORECASE):
            return f"{year}-{num}"
    return None


def extract_metric_en(text, label, unit="%"):
    """'<label> ... <number><unit> ... YoY [direction] <pct>%'."""
    pat = re.compile(
        re.escape(label)
        + r"\D{0,8}?([\d,]+\.?\d*)\s*" + re.escape(unit)
        + r".{0,60}?(?:YoY|Year[-\s]on[-\s][Yy]ear)"
        + r"\s*(" + "|".join(_DIRECTIONS) + r")?\s*"
        + r"([-\d.]+)\s*%",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        # Fall back to value-only (no YoY) so the unit + level still land.
        pat2 = re.compile(
            re.escape(label) + r"\D{0,8}?([\d,]+\.?\d*)\s*" + re.escape(unit),
            re.IGNORECASE | re.DOTALL,
        )
        m2 = pat2.search(text)
        if not m2:
            return None
        return {"value": _to_num(m2.group(1)), "yoy": None, "unit": unit}
    return {"value": _to_num(m.group(1)),
            "yoy": _signed(_to_num(m.group(3)), m.group(2)),
            "unit": unit}


def extract_pct_only_en(text, label):
    """'<label> ... [direction] <pct>%' (YoY-only reading).

    Accepts both '%' and the word 'percent'/'percentage points' because BOJ
    CGPI prose uses "rose 0.1 percent" rather than the symbol."""
    pct_token = r"(?:%(?:\s*YoY)?|\bpercent(?:age)?(?:\s+points?)?\b)"
    pat = re.compile(
        re.escape(label)
        + r".{0,80}?(?:YoY|year[-\s]on[-\s][Yy]ear)?"
        + r"\s*(" + "|".join(_DIRECTIONS) + r")?\s*"
        + r"([-+]?\d+\.?\d*)\s*"
        + pct_token,
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return None
    return {"value": None, "yoy": _signed(_to_num(m.group(2)), m.group(1)), "unit": "% YoY"}


def extract_value_at_en(text, label, stop="%"):
    """'<label> ... was|stood at|at|is|of|remain <number><stop>' (level only)."""
    pat = re.compile(
        re.escape(label)
        + r"\D{0,30}?(?:was|stood at|at|is|of|remain|to be|to remain)"
        + r"\D{0,20}?([-\d.]+)\s*" + re.escape(stop),
        re.IGNORECASE,
    )
    m = pat.search(text)
    if not m:
        return None
    return {"value": _to_num(m.group(1)), "yoy": None, "unit": stop}


def _period_from_jp_policy_url(url):
    """Extract YYYY-MM from BOJ policy URL like mpr_2026/k260731a.pdf.

    BOJ encodes the decision date in the filename `kYYMMDDa.pdf`. Only useful
    for jp_policy — other JP parsers derive the period from text.
    """
    m = re.search(r"/k(\d{2})(\d{2})\d{2}a\.pdf", url or "")
    if not m:
        return None
    yy, mm = m.group(1), m.group(2)
    return f"20{yy}-{mm}"


def _period_from_jp_cgpi_url(url):
    """Extract YYYY-MM from BOJ CGPI URL like cgpi2607.pdf.

    Filename encodes YYMM as the last 4 chars before .pdf.
    """
    m = re.search(r"/cgpi(\d{2})(\d{2})\.pdf", url or "")
    if not m:
        return None
    yy, mm = m.group(1), m.group(2)
    return f"20{yy}-{mm}"


def _finish(title, text, metrics, names, url=None):
    # URL has highest signal (BOJ encodes YYMM in filenames); only fall back
    # to text-based extraction if URL doesn't yield a period.
    period = None
    if url:
        period = (_period_from_jp_policy_url(url)
                  or _period_from_jp_cgpi_url(url))
    if not period:
        year = _extract_year(title) or _extract_year(text) or ""
        period = normalize_period_jp(year, (title or "") + " " + (text or ""))
    if not period:
        raise ValueError(f"cannot determine period from title: {title!r}")
    out = {}
    for key, res in metrics.items():
        if res:
            out[key] = {"name": names[key], **res}
    if not out:
        raise ValueError("no metrics extracted")
    return {"period": period, "metrics": out}


# ---------------------------------------------------------------------------
# BOJ — Corporate Goods Price Index (CGPI) monthly release
# ---------------------------------------------------------------------------
_CGPI_NAMES = {"cgpi_mom": "企业物价指数 环比"}


def parse_jp_ppi(title, text, url=None):
    # BOJ CGPI PDFs only state the MoM in prose ("Producer Price Index rose
    # 0.1 percent from the previous month"); the YoY lives in a data table
    # that requires tabular parsing — out of scope here. The MO labeling is
    # "Producer Price Index" not "Corporate Goods Price Index" in prose.
    metrics = {
        "cgpi_mom": extract_pct_only_en(
            text, "Producer Price Index", ),
    }
    return _finish(title, text, metrics, _CGPI_NAMES, url=url)


# ---------------------------------------------------------------------------
# Statistics Bureau — Consumer Price Index (CPI) monthly press release
# ---------------------------------------------------------------------------
_CPI_NAMES = {"cpi_yoy": "CPI 同比", "cpi_core_yoy": "核心 CPI 同比"}


def parse_jp_cpi(title, text, url=None):
    metrics = {
        "cpi_yoy": extract_pct_only_en(text, "Consumer Price Index"),
        "cpi_core_yoy": extract_pct_only_en(text, "core CPI"),
    }
    return _finish(title, text, metrics, _CPI_NAMES, url=url)


# ---------------------------------------------------------------------------
# Statistics Bureau — Unemployment Rate monthly release
# ---------------------------------------------------------------------------
_UNRATE_NAMES = {"unrate": "完全失業率"}


def parse_jp_unrate(title, text, url=None):
    metrics = {
        "unrate": extract_value_at_en(text, "unemployment rate", stop="%"),
    }
    return _finish(title, text, metrics, _UNRATE_NAMES, url=url)


# ---------------------------------------------------------------------------
# Cabinet Office — Real GDP quarterly release
# The English data PDF (main_1e.pdf) is bilingual tabular: the GDP total row
# `国 内 総 生 産 （ Ｇ Ｄ Ｐ ）` appears once per table. Table 1-1 (QoQ,
# seasonally adjusted) rows read: 5 quarterly QoQ values, a parenthesized
# contribution, then the annualized rate. Table 1-2 (YoY, original series)
# rows read: 5 quarterly YoY values. Later tables (nominal/deflator) repeat
# the row, so only rows[0]/rows[1] are trusted.
# ---------------------------------------------------------------------------
_GDP_NAMES = {"gdp_qoq": "实际 GDP 环比折年率", "gdp_yoy": "实际 GDP 同比"}

_GDP_ROW_RE = re.compile(r"総\s*生\s*産.*Ｇ\s*Ｄ\s*Ｐ")


def _gdp_row_numbers(line):
    """Extract the numeric sequence from a GDP table row, dropping the
    parenthesized contribution column first (it would shift positions).

    Normalizes Unicode minus (U+2212) and similar to ASCII '-' so float()
    never raises; otherwise an actual contraction (the most important
    release!) would crash the parser."""
    # Unicode minus U+2212, full-width hyphen-minus U+FF0D, en-dash U+2013.
    clean = re.sub(r"\([^)]*\)", " ", line)
    return [
        float(n.replace("−", "-").replace("－", "-").replace("–", "-"))
        for n in re.findall(r"[-−－–]?\d+\.?\d*", clean)
    ]


def parse_jp_gdp(title, text, url=None):
    rows = [ln for ln in text.splitlines() if _GDP_ROW_RE.search(ln)]
    metrics = {}
    # Exact count check (not >=) — CAO PDFs put the GDP row in Tables 1-1 and
    # 1-2 only; later tables (nominal/deflator) repeat the row. Anything else
    # means the layout shifted and we should refuse to publish rather than
    # silently take row[0]'s tail number as "the latest GDP".
    if len(rows) >= 2:
        nums = _gdp_row_numbers(rows[0])
        # Table 1-1: [QoQ x5, annualized] — last value is the annualized rate.
        if len(nums) >= 6:
            metrics["gdp_qoq"] = {"value": None, "yoy": nums[-1],
                                  "unit": "% QoQ annualized"}
        elif len(nums) == 5:
            metrics["gdp_qoq"] = {"value": None, "yoy": nums[-1],
                                  "unit": "% QoQ"}
        nums = _gdp_row_numbers(rows[1])
        # Table 1-2: [YoY x5] — 5th value is the latest quarter, YoY.
        if len(nums) >= 5:
            metrics["gdp_yoy"] = {"value": None, "yoy": nums[4],
                                  "unit": "% YoY"}
    return _finish(title, text, metrics, _GDP_NAMES, url=url)


# ---------------------------------------------------------------------------
# BOJ — Policy rate (uncollateralized overnight call rate target)
# ---------------------------------------------------------------------------
_POLICY_NAMES = {"policy_rate": "无担保隔夜拆借利率目标"}


def parse_jp_policy(title, text, url=None):
    # BOJ MPM PDFs phrase it as: "the uncollateralized overnight call rate to
    # remain at around X.X percent" (or "to be at around X.X percent" in older
    # releases). The value stays positive post-YCC-exit; "0.X" yields the
    # actual target.
    metrics = {
        "policy_rate": extract_value_at_en(
            text, "uncollateralized overnight call rate", stop="percent"),
    }
    return _finish(title, text, metrics, _POLICY_NAMES, url=url)