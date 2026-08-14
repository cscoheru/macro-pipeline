"""Detector change + revision detection tests (acceptance #5).

No real state.json — paths.STATE_JSON is monkeypatched to tmp_path.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import detector
import paths


def test_classify_new_period_for_first_sighting():
    assert detector.classify("fred", "GDP", "2026-06", "aaa", {}) == "new"


def test_classify_new_period_advances():
    state = {"fred:GDP": {"last_period": "2026-05", "content_sha256": "aaa"}}
    assert detector.classify("fred", "GDP", "2026-06", "bbb", state) == "new"


def test_classify_same_period_same_hash_is_same():
    state = {"fred:GDP": {"last_period": "2026-06", "content_sha256": "aaa"}}
    assert detector.classify("fred", "GDP", "2026-06", "aaa", state) == "same"


def test_classify_same_period_new_hash_is_revision():
    state = {"fred:GDP": {"last_period": "2026-06", "content_sha256": "aaa"}}
    assert detector.classify("fred", "GDP", "2026-06", "bbb", state) == "revision"


def test_is_revision_requires_known_hash():
    legacy = {"fred:GDP": {"last_period": "2026-06"}}  # no hash recorded
    assert detector.is_revision("fred", "GDP", "2026-06", "bbb", legacy) is False
    assert detector.is_revision("fred", "GDP", "2026-06", "", legacy) is False


def test_classify_older_period_is_same_without_history():
    # Older-period official revisions need a period->hash history to detect,
    # which the last-seen model doesn't keep. classify() returns "same" (never
    # "new", so last_period is never moved backward). Older-period revision
    # tracking is deferred; see module docstring.
    state = {"fred:GDP": {"last_period": "2026-07", "content_sha256": "aaa"}}
    assert detector.classify("fred", "GDP", "2026-06", "bbb", state) == "same"


def test_is_new_period_unchanged_for_legacy_entries():
    # Backward compatibility: entries written by the old detector (last_period
    # only) must still gate collection identically.
    state = {"fred:GDP": {"last_period": "2026-05"}}
    assert detector.is_new_period("fred", "GDP", "2026-06", state) is True
    assert detector.is_new_period("fred", "GDP", "2026-05", state) is False


def test_mark_seen_stores_hash_and_supports_legacy_callers():
    state = {}
    detector.mark_seen("fred", "GDP", "2026-06", state, content_sha256="aaa")
    assert state["fred:GDP"] == {"last_period": "2026-06", "content_sha256": "aaa"}
    detector.mark_seen("cn_pbc", "_period", "2026-06", state)  # legacy, no hash
    assert state["cn_pbc:_period"] == {"last_period": "2026-06"}


def test_atomic_save_roundtrip(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    monkeypatch.setattr(paths, "STATE_JSON", str(target))
    state = {"fred:GDP": {"last_period": "2026-06", "content_sha256": "aaa"}}
    detector.save_state(state)
    assert json.loads(target.read_text(encoding="utf-8")) == state
    assert detector.load_state() == state


def test_save_state_leaves_no_temp_behind(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    monkeypatch.setattr(paths, "STATE_JSON", str(target))
    detector.save_state({"a": 1})
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".state-")]
    assert leftovers == []


def test_corrupt_state_logs_warning_and_starts_empty(tmp_path, monkeypatch, caplog):
    target = tmp_path / "state.json"
    monkeypatch.setattr(paths, "STATE_JSON", str(target))
    target.write_text("{not valid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert detector.load_state() == {}
    assert any("unreadable" in rec.message for rec in caplog.records)


def test_missing_state_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "STATE_JSON", str(tmp_path / "absent.json"))
    assert detector.load_state() == {}
