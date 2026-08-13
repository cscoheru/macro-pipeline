"""Lightweight cache for the 最新读数 table.

The SQLite store is the raw time-series archive; this JSON is the single source
of truth for the *display* table. It decouples the table from source-specific
stat computation: FRED fills yoy via history math, China fills yoy directly from
the release text. Both write entries here in a uniform shape.
"""
import json
import os
import paths

CACHE_PATH = os.path.join(paths.DATA, "latest_readings.json")

# Entry shape:
#   {source, economy, name, unit, value, yoy_pct, mom_pct, trend, period, updated}
# key = f"{source}:{series_id}"


def load() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        return json.load(open(CACHE_PATH, "r", encoding="utf-8"))
    except Exception:
        return {}


def save(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def upsert(cache: dict, key: str, entry: dict) -> None:
    cache[key] = entry
