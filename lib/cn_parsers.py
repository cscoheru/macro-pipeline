"""Parsers for China macro releases (财政部 / 国家统计局 / 央行).

Input: clean text (HTML stripped by fetcher.strip_tags).
Output: {"period": "YYYY-MM", "metrics": {key: {name, unit, value, yoy}}}

China releases report level AND YoY directly in prose, so we extract both
(unlike FRED where YoY is computed from history). Cumulative periods (1-X月)
make history-based YoY/MoM meaningless, so we trust the reported figure.
"""
import re

# direction words that flip the sign of an extracted percent
_DIRECTIONS = ("增长", "下降", "上升", "减少", "提高", "回落", "上涨", "下跌", "降低", "放缓", "收窄", "扩大")


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
    return -abs(pct) if direction in ("下降", "减少", "下跌", "降低", "放缓", "收窄") else pct


def normalize_period_cn(year, text):
    """Extract end-month -> 'YYYY-MM' (sortable). Handles:
    1-X月 / 上半年 / 一季度 / 前三季度 / 全年 / 单月'X月份'."""
    t = text.replace("—", "-").replace("——", "-").replace("～", "-").replace("至", "-")
    m = re.search(r"1\s*-\s*(\d{1,2})\s*月", t)          # cumulative 1-X月
    if m:
        return f"{year}-{int(m.group(1)):02d}"
    if "上半年" in t:
        return f"{year}-06"
    if "前三季度" in t or "前三个季度" in t:
        return f"{year}-09"
    if "一季度" in t or "第一季度" in t:
        return f"{year}-03"
    if "二季度" in t or "第二季度" in t:
        return f"{year}-06"
    if "三季度" in t or "第三季度" in t:
        return f"{year}-09"
    if "四季度" in t or "第四季度" in t:
        return f"{year}-12"
    if "全年" in t:
        return f"{year}-12"
    m = re.search(r"(\d{1,2})\s*月份?", t)                # single month (e.g. CPI/PMI)
    if m:
        return f"{year}-{int(m.group(1)):02d}"
    return None


def _extract_year(title_or_text):
    m = re.search(r"(20\d{2})年", title_or_text)
    return m.group(1) if m else None


def extract_metric(text, label, unit="亿元"):
    """'<label>...<number><unit>...同比[方向]<pct>%'. Returns {value, yoy, unit} or None."""
    pat = re.compile(
        re.escape(label)
        + r"\D{0,8}?([\d,]+\.?\d*)\s*" + re.escape(unit)
        + r".{0,40}?(?:同比)?" + r"\s*(" + "|".join(_DIRECTIONS) + r")?\s*"
        + r"([-\d.]+)\s*%",
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        pat2 = re.compile(re.escape(label) + r"\D{0,8}?([\d,]+\.?\d*)\s*" + re.escape(unit), re.DOTALL)
        m2 = pat2.search(text)
        if not m2:
            return None
        return {"value": _to_num(m2.group(1)), "yoy": None, "unit": unit}
    return {"value": _to_num(m.group(1)), "yoy": _signed(_to_num(m.group(3)), m.group(2)), "unit": unit}


def extract_pct_only(text, label):
    """For series reported only as '同比[方向]X%' near label (no level 亿元)."""
    pat = re.compile(
        re.escape(label) + r".{0,60}?(?:同比)?\s*(" + "|".join(_DIRECTIONS) + r")?\s*([-\d.]+)\s*%",
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return None
    return {"value": None, "yoy": _signed(_to_num(m.group(2)), m.group(1)), "unit": "% 同比"}


def extract_value_at(text, label, stop="%"):
    """'<label>...为<number>%' (e.g. PMI指数为49.2%). Returns {value, yoy, unit} or None."""
    pat = re.compile(re.escape(label) + r"\D{0,10}?为\s*([\d.]+)\s*" + re.escape(stop), re.DOTALL)
    m = pat.search(text)
    if not m:
        return None
    return {"value": _to_num(m.group(1)), "yoy": None, "unit": stop}


def _finish(title, text, metrics, names):
    year = _extract_year(title) or _extract_year(text) or ""
    period = normalize_period_cn(year, title + " " + text)
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
# 财政部 月度财政收支
# ---------------------------------------------------------------------------
_MOF_NAMES = {
    "mof_revenue": "一般公共预算收入", "mof_expenditure": "一般公共预算支出",
    "mof_central_exp": "中央本级支出", "mof_local_exp": "地方支出",
    "mof_govfund_rev": "政府性基金收入", "mof_govfund_exp": "政府性基金预算支出",
    "mof_land": "土地出让收入",
}
MOF_LABELS = [
    ("mof_revenue", "全国一般公共预算收入", "亿元"),
    ("mof_expenditure", "全国一般公共预算支出", "亿元"),
    ("mof_central_exp", "中央一般公共预算本级支出", "亿元"),
    ("mof_local_exp", "地方一般公共预算支出", "亿元"),
    ("mof_govfund_rev", "全国政府性基金预算收入", "亿元"),
    ("mof_govfund_exp", "全国政府性基金预算支出", "亿元"),
    ("mof_land", "国有土地使用权出让收入", "亿元"),
]


def parse_mof_fiscal(title, text):
    metrics = {k: extract_metric(text, lab, unit) for k, lab, unit in MOF_LABELS}
    return _finish(title, text, metrics, _MOF_NAMES)


# ---------------------------------------------------------------------------
# 国家统计局 固定资产投资
# ---------------------------------------------------------------------------
_INV_NAMES = {"inv_total": "固定资产投资(不含农户)", "inv_infra": "基础设施投资", "inv_private": "民间投资"}


def parse_stats_investment(title, text):
    metrics = {
        "inv_total": extract_metric(text, "全国固定资产投资（不含农户）", "亿元"),
        "inv_infra": extract_pct_only(text, "基础设施投资"),
        "inv_private": extract_pct_only(text, "民间固定资产投资"),
    }
    return _finish(title, text, metrics, _INV_NAMES)


# ---------------------------------------------------------------------------
# 国家统计局 CPI / PPI / PMI
# ---------------------------------------------------------------------------
def parse_stats_cpi(title, text):
    metrics = {"cpi_yoy": extract_pct_only(text, "全国居民消费价格")}
    return _finish(title, text, metrics, {"cpi_yoy": "CPI 同比"})


def parse_stats_ppi(title, text):
    metrics = {"ppi_yoy": extract_pct_only(text, "工业生产者出厂价格")}
    return _finish(title, text, metrics, {"ppi_yoy": "PPI 同比"})


def parse_stats_pmi(title, text):
    metrics = {"pmi_mfg": extract_value_at(text, "制造业采购经理指数", stop="%")}
    return _finish(title, text, metrics, {"pmi_mfg": "制造业PMI"})


# ---------------------------------------------------------------------------
# 央行 金融统计 (M2 / M1 / 社融)
# ---------------------------------------------------------------------------
_PBC_NAMES = {"pbc_m2": "M2 广义货币", "pbc_m1": "M1 狭义货币", "pbc_tsfs": "社融存量"}


def parse_pbc_financial(title, text):
    # release says '广义货币(M2)余额356.71万亿元' — the (M2) digit breaks \D connector,
    # so strip the (Mx) parenthetical first.
    cleaned = re.sub(r"\(M[0-9]\)", "", text)
    metrics = {
        "pbc_m2": extract_metric(cleaned, "广义货币", "万亿元"),
        "pbc_m1": extract_metric(cleaned, "狭义货币", "万亿元"),
        "pbc_tsfs": extract_metric(cleaned, "社会融资规模存量", "万亿元"),
    }
    return _finish(title, text, metrics, _PBC_NAMES)
