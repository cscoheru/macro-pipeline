"""Tests for CC Autopilot inspect + ASR guard."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_asr_guard  # noqa: E402
import cc_autopilot_inspect as inspect  # noqa: E402


def test_list_asr_pids_skips_zsh_wrapper():
    ps_out = "\n".join([
        " 4484 /bin/zsh -c python3 scripts/houchen_pipeline.py asr-transcribe --video-id x",
        " 4487 /Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python scripts/houchen_pipeline.py asr-transcribe --video-id x",
    ])
    assert inspect.list_asr_pids(ps_out) == [4487]


def test_inbox_status_parses_do():
    text = "foo\nSTATUS=DO\n"
    assert inspect.inbox_status(text) == "DO"


def test_classify_duplicate_whisper_is_action():
    sev, actions, _ = inspect.classify(
        "DO", [1, 2], {}, True)
    assert sev == "ACTION"
    assert "kill_duplicate_whisper" in actions


def test_classify_wait_cursor_is_action():
    sev, actions, _ = inspect.classify("WAIT_CURSOR", [], {}, True)
    assert sev == "ACTION"
    assert "accept_inbox" in actions


def test_classify_wait_cursor_with_whisper_is_not_accept():
    sev, actions, _ = inspect.classify("WAIT_CURSOR", [29901], {}, True)
    assert "accept_inbox" not in actions
    assert sev == "OK"


def test_classify_ok_single_pid():
    sev, actions, _ = inspect.classify("DO", [4487], {}, True)
    assert sev == "OK"
    assert actions == []


def test_classify_pending_import_is_action():
    sev, actions, _ = inspect.classify(
        "DO", [], {}, True, pending_import=["jfXAn1dgkyw"])
    assert sev == "ACTION"
    assert "finish_import_analyze" in actions


def test_classify_store_drift_is_warn():
    sev, _, _ = inspect.classify("DO", [4487], {}, False)
    assert sev == "WARN"


def test_guard_blocks_second_transcribe():
    reason = cc_asr_guard.should_block(
        "python3 scripts/houchen_pipeline.py asr-transcribe --video-id x",
        [3787],
    )
    assert reason and "second whisper" in reason


def test_guard_blocks_rm_lock_while_running():
    reason = cc_asr_guard.should_block(
        "rm -f data/houchen/asr/vtt/*.lock data/houchen/asr/vtt/*.tmp",
        [4487],
    )
    assert reason and "rm ASR" in reason


def test_guard_allows_inspect():
    assert cc_asr_guard.should_block(
        "python3 scripts/cc_autopilot_inspect.py", [4487]) is None


def test_extract_command_cursor_and_claude():
    assert cc_asr_guard.extract_command({"command": "echo hi"}) == "echo hi"
    assert cc_asr_guard.extract_command(
        {"tool_input": {"command": "ls"}}) == "ls"


def test_inspect_uses_env_pids(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "reviews"
    inbox.mkdir()
    (inbox / "CC_INBOX.md").write_text("STATUS=DO\n", encoding="utf-8")
    (inbox / "bus").mkdir()
    (inbox / "bus" / "state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CC_AUTOPILOT_ROOT", str(tmp_path))
    monkeypatch.setenv("CC_AUTOPILOT_PIDS", "4487")
    monkeypatch.setenv("CC_AUTOPILOT_STORE", str(tmp_path / "missing.db"))
    report = inspect.inspect(tmp_path)
    assert report["asr_pids"] == [4487]
    assert report["inbox"] == "DO"
