"""Change detection via state.json. Tracks last-seen period per (source, series).

Keyed by f"{source}:{series}" -> {"last_period": "YYYY-MM-DD"}.
A run only processes series whose latest observation period is newer than stored.
This makes the pipeline idempotent: re-runs without new data do nothing.
"""
import json
import os
import paths


def load_state() -> dict:
    if not os.path.exists(paths.STATE_JSON):
        return {}
    try:
        return json.load(open(paths.STATE_JSON, "r", encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(paths.STATE_JSON), exist_ok=True)
    with open(paths.STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _key(source: str, series: str) -> str:
    return f"{source}:{series}"


def is_new_period(source: str, series: str, current_period: str, state: dict) -> bool:
    """True if current_period is newer than the last-seen period for this series."""
    last = state.get(_key(source, series), {}).get("last_period")
    return last is None or current_period > last


def mark_seen(source: str, series: str, period: str, state: dict) -> None:
    state[_key(source, series)] = {"last_period": period}
