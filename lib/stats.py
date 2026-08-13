"""Compute statistics from a series history and apply framework-trigger rules.

history: list of (date_str, float), oldest -> newest.
A 'step' is one observation. Monthly series use ~12 steps for YoY; quarterly use 4.
"""
from typing import Optional, Dict, Any


def _is_quarterly(history) -> bool:
    """Infer quarterly cadence from month component of the latest dates."""
    if len(history) < 2:
        return False
    months = set()
    for d, _ in history[-4:]:
        try:
            months.add(int(d.split("-")[1]))
        except (ValueError, IndexError):
            pass
    return bool(months) and months.issubset({1, 4, 7, 10})


def _pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100.0


def compute_stats(history, display: str = "level") -> Optional[Dict[str, Any]]:
    """Compute latest value, MoM%, YoY%, prev, trend from history.

    display: which transform is the 'headline' for this series (level|yoy|mom).
    Returns None if history empty.
    """
    if not history:
        return None
    latest_date, latest_val = history[-1]
    prev_val = history[-2][1] if len(history) >= 2 else None
    mom = _pct_change(latest_val, prev_val)

    lookback = 4 if _is_quarterly(history) else 12
    yoy_idx = len(history) - 1 - lookback
    yoy = None
    yoy_base_date = None
    if yoy_idx >= 0:
        yoy_base_date = history[yoy_idx][0]
        base = history[yoy_idx][1]
        # pct change is undefined/nonsensical when base or current <= 0
        # (e.g. fiscal deficit crossing zero) -> report None instead of garbage
        if base > 0 and latest_val > 0:
            yoy = _pct_change(latest_val, base)

    # trend over last 3 observations (up/down/flat) based on raw values
    tail = [v for _, v in history[-3:]]
    if len(tail) >= 2:
        if tail[-1] > tail[0]:
            trend = "↑"
        elif tail[-1] < tail[0]:
            trend = "↓"
        else:
            trend = "→"
    else:
        trend = "—"

    return {
        "date": latest_date,
        "value": latest_val,
        "prev": prev_val,
        "mom_pct": mom,
        "yoy_pct": yoy,
        "yoy_base_date": yoy_base_date,
        "trend": trend,
        "steps": len(history),
    }
