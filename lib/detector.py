"""Change + revision detection via state.json.

Per (source, series) we track {"last_period", "content_sha256"}.

A run decides per series via classify():
  * "new"      — newer period than last seen (or first sighting): process normally.
  * "revision" — same period as last seen but content hash differs: an official
                 revision; re-record and (when insights are on) supersede.
  * "same"     — same period and same hash: skip (idempotent re-run).

State is saved atomically (temp + fsync + os.replace) so a crash mid-write
cannot corrupt the last good state. A corrupt state file is reported loudly
rather than silently ignored, since a silent reset would make every series
look "new" again and re-publish duplicate insights.

Limitation: only the last-seen period/hash is kept. An official revision of an
OLDER period (period < last_period) cannot be told apart from a period already
processed without a period->hash history, so classify() returns "same" for it;
full older-period revision tracking is deferred to a later change.
"""
import json
import logging
import os
import tempfile

import paths


def load_state() -> dict:
    if not os.path.exists(paths.STATE_JSON):
        return {}
    try:
        with open(paths.STATE_JSON, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        # A silent reset here would make every series look "new" again and
        # re-publish duplicates; surface it so the operator can restore.
        logging.warning("state.json unreadable, starting empty (%s): %s",
                        type(exc).__name__, exc)
        return {}


def save_state(state: dict) -> None:
    """Persist state atomically: write temp, fsync, then os.replace."""
    directory = os.path.dirname(paths.STATE_JSON) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, tmp_path = tempfile.mkstemp(prefix=".state-", dir=directory, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, paths.STATE_JSON)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _key(source: str, series: str) -> str:
    return f"{source}:{series}"


def is_new_period(source: str, series: str, current_period: str, state: dict) -> bool:
    """True if current_period is newer than the last-seen period for this series."""
    last = state.get(_key(source, series), {}).get("last_period")
    return last is None or current_period > last


def is_revision(source: str, series: str, current_period: str,
                content_sha256: str, state: dict) -> bool:
    """True if the period was already seen but its content hash has changed.

    Returns False when no hash is recorded (legacy entry or first sighting),
    since a revision can only be detected against a known prior hash.
    """
    if not content_sha256:
        return False
    entry = state.get(_key(source, series), {})
    return entry.get("last_period") == current_period and \
        entry.get("content_sha256") not in (None, content_sha256)


def classify(source: str, series: str, current_period: str,
             content_sha256: str, state: dict) -> str:
    """Decide what to do with a series+period+hash: 'new' | 'revision' | 'same'."""
    if is_new_period(source, series, current_period, state):
        return "new"
    if is_revision(source, series, current_period, content_sha256, state):
        return "revision"
    return "same"


def mark_seen(source: str, series: str, period: str, state: dict,
              content_sha256: str = None) -> None:
    """Record the last-seen period (and content hash, when known).

    content_sha256 is optional so legacy callers keep working; passing it lets
    later runs detect same-period revisions via classify()/is_revision().
    """
    entry = {"last_period": period}
    if content_sha256:
        entry["content_sha256"] = content_sha256
    state[_key(source, series)] = entry
