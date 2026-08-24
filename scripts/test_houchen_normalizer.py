"""Tests for `lib/houchen_normalizer.py` and `lib/houchen_quote.py`.

Covers:
  - json3 / vtt deterministic parsing (millisecond timestamps).
  - Rolling-caption deduplication (brief §8.2).
  - Empty cue / format-mark stripping.
  - Bounded merge (brief §8.3).
  - Raw-cue reverse mapping preserved.
  - NFC + whitespace folding (brief §8.6).
  - Idempotency (brief §8.7).
  - exact_quote_in_segment discipline (brief §8.6 hard gate).
  - End-to-end `transcribe_video` with atomic install.

All tests run on temp dirs via `tmp_path`; never touch the real repo data root.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import houchen_normalizer as norm
import houchen_paths
import houchen_quote


# ---------------------------------------------------------------------------
# VTT parsing
# ---------------------------------------------------------------------------

def test_parse_vtt_basic_millisecond_timestamps():
    cues = norm.parse_vtt(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.500\n"
        "中央政治局\n\n"
        "00:00:01.500 --> 00:00:03.250\n"
        "第二个 cue\n"
    )
    assert [c.ordinal for c in cues] == [0, 1]
    assert cues[0].start_ms == 0
    assert cues[0].end_ms == 1500
    assert cues[1].start_ms == 1500
    assert cues[1].end_ms == 3250
    assert cues[0].text == "中央政治局"


def test_parse_vtt_drops_empty_cue_body():
    cues = norm.parse_vtt(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "保留这一\n"
    )
    # The empty-body cue (just a newline) is dropped.
    assert len(cues) == 1
    assert cues[0].text == "保留这一"


def test_parse_vtt_raises_without_webvtt_header():
    with pytest.raises(ValueError, match="WEBVTT"):
        norm.parse_vtt("00:00:00.000 --> 00:00:01.000\nfoo\n")


def test_parse_vtt_skips_style_and_note_blocks():
    cues = norm.parse_vtt(
        "WEBVTT\n\n"
        "NOTE this is a comment block\n\n"
        "STYLE\n::cue { color: red }\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "保留\n"
    )
    assert len(cues) == 1


def test_parse_vtt_handles_cue_identifier_lines():
    """Optional cue id on its own line before the timestamp must be tolerated."""
    cues = norm.parse_vtt(
        "WEBVTT\n\n"
        "cue-1\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "first\n\n"
        "cue-2\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "second\n"
    )
    assert [c.text for c in cues] == ["first", "second"]


# ---------------------------------------------------------------------------
# JSON3 parsing
# ---------------------------------------------------------------------------

def test_parse_json3_basic_with_timestamps():
    body = json.dumps({
        "events": [
            {"tStartMs": 0, "dDurationMs": 1500,
             "segs": [{"utf8": "中央政治局会议承认经济面临困难挑战"}]},
            {"tStartMs": 1500, "dDurationMs": 1800,
             "segs": [{"utf8": "但会议没有触及收入分配问题"}]},
        ],
    }, ensure_ascii=False)
    cues = norm.parse_json3(body)
    assert len(cues) == 2
    assert cues[0].start_ms == 0 and cues[0].end_ms == 1500
    assert cues[1].start_ms == 1500 and cues[1].end_ms == 3300


def test_parse_json3_collapses_aappend_newlines():
    """YouTube JSON3 emits a newline as an event with `segs[0].aAppend=1`."""
    body = json.dumps({
        "events": [
            {"tStartMs": 0, "dDurationMs": 1000,
             "segs": [{"utf8": "第一行"}]},
            {"tStartMs": 1000, "dDurationMs": 500,
             "segs": [{"aAppend": 1}, {"utf8": "第二行"}]},
            {"tStartMs": 1500, "dDurationMs": 1000,
             "segs": [{"utf8": "独立 cue"}]},
        ],
    }, ensure_ascii=False)
    cues = norm.parse_json3(body)
    # aAppend merges line 2 into line 1, so we should have 2 cues (line1+line2, line3).
    assert len(cues) == 2
    assert "第一行" in cues[0].text
    assert "第二行" in cues[0].text


def test_parse_json3_raises_on_invalid_json():
    with pytest.raises(ValueError, match="invalid json3"):
        norm.parse_json3("not json at all")


def test_parse_json3_empty_events_list_yields_no_cues():
    cues = norm.parse_json3(json.dumps({"events": []}))
    assert cues == []


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalize_cues_drops_empty_after_nfc_fold():
    cues = [
        norm.Cue(ordinal=0, start_ms=0, end_ms=1000, text="   "),
        norm.Cue(ordinal=1, start_ms=1000, end_ms=2000, text="保留"),
    ]
    segs = norm.normalize_cues(cues)
    assert len(segs) == 1
    assert segs[0].text == "保留"


def test_normalize_cues_collapse_repeats():
    """Deterministic scrolling repetitions (§8.2) — consecutive identical
    texts collapse to one when the run fits within MAX_REPEAT_WINDOW.

    Cues are spaced far enough apart (gap > MAX_MERGE_GAP_MS) so the bounded
    merge step does NOT coalesce them first; only the repeat-collapse
    behavior is being tested here.
    """
    gap = norm.MAX_MERGE_GAP_MS + 500  # > 1500ms, no merge
    cues = [
        norm.Cue(ordinal=0, start_ms=0,        end_ms=1000,    text="滚动"),
        norm.Cue(ordinal=1, start_ms=1000+gap, end_ms=2000+gap, text="滚动"),
        norm.Cue(ordinal=2, start_ms=2000+2*gap, end_ms=3000+2*gap, text="滚动"),
        norm.Cue(ordinal=3, start_ms=3000+3*gap, end_ms=4000+3*gap, text="下一段"),
    ]
    segs = norm.normalize_cues(cues)
    # 3 collapsed → 1, plus 1 distinct = 2
    assert len(segs) == 2
    assert segs[0].text == "滚动"
    assert segs[1].text == "下一段"


def test_normalize_cues_long_repeat_run_truncated_to_window():
    """Brief §8.2 window cap: a run LONGER than MAX_REPEAT_WINDOW is NOT
    collapsed wholesale — only the first MAX_REPEAT_WINDOW segments survive
    (preserving raw_cue_start..end mapping).

    Cues are spaced > MAX_MERGE_GAP_MS apart so the bounded merge step does
    NOT coalesce them — this isolates the repeat-collapse behavior.
    """
    gap = norm.MAX_MERGE_GAP_MS + 500  # > 1500ms, no merge
    n = norm.MAX_REPEAT_WINDOW + 2  # 7 cues by default
    cues = [
        norm.Cue(ordinal=i, start_ms=i * (1000 + gap),
                 end_ms=i * (1000 + gap) + 500, text="长重复")
        for i in range(n)
    ]
    cues.append(norm.Cue(ordinal=n, start_ms=n * (1000 + gap),
                         end_ms=n * (1000 + gap) + 500, text="不同"))
    segs = norm.normalize_cues(cues)
    # The long run is truncated to MAX_REPEAT_WINDOW; the distinct tail
    # follows as one segment.
    assert len(segs) == norm.MAX_REPEAT_WINDOW + 1
    for s in segs[:norm.MAX_REPEAT_WINDOW]:
        assert s.text == "长重复"
    assert segs[norm.MAX_REPEAT_WINDOW].text == "不同"
    # The truncated window still preserves the contiguous raw_cue mapping.
    assert segs[0].raw_cue_start == 0
    assert segs[norm.MAX_REPEAT_WINDOW - 1].raw_cue_end == norm.MAX_REPEAT_WINDOW - 1


def test_normalize_cues_strips_html_formatting():
    cues = [
        norm.Cue(ordinal=0, start_ms=0, end_ms=1000,
                 text="<i>斜体</i> 与 &lt;b&gt;粗体&lt;/b&gt;"),
    ]
    segs = norm.normalize_cues(cues)
    assert len(segs) == 1
    assert segs[0].text == "斜体 与 <b>粗体</b>"
    assert "<i>" not in segs[0].text


def test_normalize_cues_bounded_merge_short_gap_joins():
    cues = [
        norm.Cue(ordinal=0, start_ms=0,    end_ms=1000, text="第一段"),
        norm.Cue(ordinal=1, start_ms=1500, end_ms=2500, text="紧接"),
    ]
    segs = norm.normalize_cues(cues)
    assert len(segs) == 1
    assert segs[0].raw_cue_start == 0
    assert segs[0].raw_cue_end == 1
    assert segs[0].end_ms == 2500


def test_normalize_cues_break_punctuation_does_not_merge():
    """A sentence terminator at the end of a segment blocks the merge."""
    cues = [
        norm.Cue(ordinal=0, start_ms=0,    end_ms=1000, text="第一句。"),
        norm.Cue(ordinal=1, start_ms=1500, end_ms=2500, text="第二句"),
    ]
    segs = norm.normalize_cues(cues)
    # The `。` at end of first segment blocks the merge.
    assert len(segs) == 2


def test_normalize_cues_merge_respects_hard_upper_bound():
    """Adjacent cues must NOT merge when their combined span would exceed
    MAX_MERGE_SEGMENT_MS, even if the gap is small."""
    cues = [
        norm.Cue(ordinal=0, start_ms=0,    end_ms=5000, text="主题A"),
        norm.Cue(ordinal=1, start_ms=5500, end_ms=10000, text="主题B"),  # gap=500ms
    ]
    segs = norm.normalize_cues(cues)
    # Combined span 10000 - 0 = 10000ms > MAX_MERGE_SEGMENT_MS (8000ms).
    assert len(segs) == 2


def test_normalize_cues_preserves_raw_cue_mapping():
    """Each segment's raw_cue_start / raw_cue_end must point to the correct
    source cues after merge / repeat-collapse."""
    cues = [
        norm.Cue(ordinal=0, start_ms=0,    end_ms=1000, text="短句一"),
        norm.Cue(ordinal=1, start_ms=1100, end_ms=2000, text="短句二"),
        norm.Cue(ordinal=2, start_ms=3000, end_ms=4000, text="短句三"),
    ]
    segs = norm.normalize_cues(cues)
    # 0+1 merge (gap=100), 2 stays standalone (gap=1000, no terminator block
    # but the gap is > MAX_MERGE_GAP_MS=1500? no, 1000 ≤ 1500, so they could
    # merge if not blocked. Verify the raw mapping either way is intact.)
    assert all(s.raw_cue_start <= s.raw_cue_end for s in segs)
    assert segs[0].raw_cue_start == 0
    # The last segment's raw_cue_end must reach the highest ordinal.
    assert segs[-1].raw_cue_end == 2


def test_normalize_cues_nfc_normalization_collapses_decomposed():
    """A decomposed-form character (NFD) must match its NFC composed form.

    After NFC, both become the same composed form. With a strictly-positive
    gap (1100ms), they qualify for merge → one segment whose text is the two
    concatenated with a single space (NFC + whitespace fold).
    """
    nfd = "é"  # 'e' + U+0301
    nfc = "é"  # U+00E9
    cues = [
        norm.Cue(ordinal=0, start_ms=0, end_ms=1000, text=nfd),
        norm.Cue(ordinal=1, start_ms=2100, end_ms=3000, text=nfc),
    ]
    segs = norm.normalize_cues(cues)
    assert len(segs) == 1
    # Merged text is NFC'd + whitespace-folded → single-space concatenation.
    assert segs[0].text == f"{nfc} {nfc}"


def test_normalize_cues_text_is_whitespace_folded():
    """Multiple internal spaces / NBSP collapse to single ASCII space."""
    cues = [
        norm.Cue(ordinal=0, start_ms=0, end_ms=1000,
                 text="第一段  第二段"),
    ]
    segs = norm.normalize_cues(cues)
    assert "  " not in segs[0].text
    assert segs[0].text == "第一段 第二段"


def test_normalize_cues_speaker_never_defaults_to_houchen():
    """Brief §7.1: speaker is nullable, never defaulted to "李厚辰"."""
    cues = [
        norm.Cue(ordinal=0, start_ms=0, end_ms=1000, text="一些内容"),
    ]
    segs = norm.normalize_cues(cues)
    assert segs[0].speaker is None


def test_normalize_cues_handles_empty_input():
    assert norm.normalize_cues([]) == []
    assert norm.normalize_cues(None) == []


def test_normalize_cues_skips_inverted_timestamps():
    cues = [
        norm.Cue(ordinal=0, start_ms=1000, end_ms=500, text="bad"),
        norm.Cue(ordinal=1, start_ms=2000, end_ms=3000, text="ok"),
    ]
    segs = norm.normalize_cues(cues)
    assert len(segs) == 1
    assert segs[0].text == "ok"


# ---------------------------------------------------------------------------
# Idempotency (brief §8.7)
# ---------------------------------------------------------------------------

def test_normalize_cues_is_idempotent():
    cues = [
        norm.Cue(ordinal=0, start_ms=0,    end_ms=1000, text="第一段"),
        norm.Cue(ordinal=1, start_ms=1100, end_ms=2000, text="紧接"),
    ]
    a = norm.normalize_cues(cues)
    b = norm.normalize_cues(cues)
    assert a == b


def test_transcribe_video_idempotent_same_sha(tmp_path, monkeypatch):
    """Two calls on the same raw caption produce identical content_sha256 and
    reuse the existing derived JSON file (no rewrite)."""
    monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path))
    raw_path = tmp_path / "raw.vtt"
    raw_path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n唯一内容\n",
        encoding="utf-8")
    a = norm.transcribe_video(
        video_id="aaaaaaaaaaa",
        raw_caption_path=str(raw_path),
        raw_caption_sha256="0" * 64,
        raw_format="vtt",
        created_at="2026-08-24T00:00:00+00:00",
    )
    # Capture the file's mtime before second call.
    mtime_before = os.path.getmtime(a.local_path)
    # Force re-run with same inputs.
    import time
    time.sleep(0.05)
    b = norm.transcribe_video(
        video_id="aaaaaaaaaaa",
        raw_caption_path=str(raw_path),
        raw_caption_sha256="0" * 64,
        raw_format="vtt",
        created_at="2026-08-24T00:00:00+00:00",
    )
    assert a.content_sha256 == b.content_sha256
    assert a.local_path == b.local_path
    # File should NOT have been rewritten (mtime unchanged).
    assert os.path.getmtime(b.local_path) == mtime_before


def test_transcribe_video_atomic_0600_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path))
    raw_path = tmp_path / "raw.vtt"
    raw_path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nx\n", encoding="utf-8")
    result = norm.transcribe_video(
        video_id="aaaaaaaaaaa",
        raw_caption_path=str(raw_path),
        raw_caption_sha256="0" * 64,
        raw_format="vtt",
        created_at="2026-08-24T00:00:00+00:00",
    )
    assert os.path.isfile(result.local_path)
    assert oct(os.stat(result.local_path).st_mode & 0o777) == "0o600"
    # No leftover .tmp files.
    assert not any(p.endswith(".tmp") for p in os.listdir(tmp_path))


def test_transcribe_video_refuses_bad_video_id(tmp_path):
    with pytest.raises(ValueError, match="video_id"):
        norm.transcribe_video(
            video_id="not-11-chars",
            raw_caption_path="/nope",
            raw_caption_sha256="0" * 64,
            raw_format="vtt",
            created_at="2026-08-24T00:00:00+00:00",
        )


def test_transcribe_video_refuses_non_v1_normalizer():
    with pytest.raises(ValueError, match="normalizer_name"):
        norm.transcribe_video(
            video_id="aaaaaaaaaaa",
            raw_caption_path="/nope",
            raw_caption_sha256="0" * 64,
            raw_format="vtt",
            created_at="2026-08-24T00:00:00+00:00",
            normalizer_name="something_else",
        )


def test_transcribe_video_rejects_unsupported_format(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUCHEN_DATA_ROOT", str(tmp_path))
    raw_path = tmp_path / "raw.ttml"
    raw_path.write_text("<?xml/>", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported format"):
        norm.transcribe_video(
            video_id="aaaaaaaaaaa",
            raw_caption_path=str(raw_path),
            raw_caption_sha256="0" * 64,
            raw_format="ttml",
            created_at="2026-08-24T00:00:00+00:00",
        )


# ---------------------------------------------------------------------------
# Quote discipline (brief §8.6)
# ---------------------------------------------------------------------------

def test_normalize_for_compare_nfc_collapses_decomposed():
    nfd = "Café"  # 'e' + U+0301
    nfc = "Café"
    assert houchen_quote.normalize_for_compare(nfd) == houchen_quote.normalize_for_compare(nfc)


def test_normalize_for_compare_folds_whitespace():
    assert houchen_quote.normalize_for_compare("a   b\t\tc\n\nd") == "a b c d"
    # NBSP folds too.
    assert houchen_quote.normalize_for_compare("a b") == "a b"


def test_normalize_for_compare_strips_bom_and_outer_whitespace():
    assert houchen_quote.normalize_for_compare("﻿ hello ") == "hello"


def test_exact_quote_in_segment_positive_match():
    seg = "中央政治局会议承认经济面临困难挑战"
    quote = "政治局会议"
    assert houchen_quote.exact_quote_in_segment(quote, seg) is True


def test_exact_quote_in_segment_negative_one_char_mismatch():
    seg = "中央政治局会议承认经济面临困难挑战"
    quote = "政治局议"  # missing the "会"
    assert houchen_quote.exact_quote_in_segment(quote, seg) is False


def test_exact_quote_in_segment_handles_whitespace_difference():
    """Brief §8.6: matching normalization is NFC + consecutive-whitespace
    fold. RUNS of whitespace collapse to a SINGLE space; a single space
    does NOT get removed. So a segment with explicit single spaces is not
    considered to contain a quote that has them removed.
    """
    seg = "中央 政治局 会议"
    quote = "中央政治局会议"
    # Single spaces in the segment are NOT removed by the canonical normalize.
    assert houchen_quote.exact_quote_in_segment(quote, seg) is False
    # But multiple internal whitespace in the SEGMENT folds to a single space,
    # so a quote with the same folded spaces matches:
    seg_folded = "中央  政治局\n会议"
    quote_folded = "中央 政治局 会议"  # already single-spaced → folds identically
    assert houchen_quote.exact_quote_in_segment(quote_folded, seg_folded) is True


def test_exact_quote_in_segment_handles_nfc_normalization():
    nfd = "Café"
    nfc = "Café"
    assert houchen_quote.exact_quote_in_segment(nfd, nfc) is True
    assert houchen_quote.exact_quote_in_segment(nfc, nfd) is True


def test_quote_coverage_ratio_basic():
    seg = "中央政治局会议承认经济面临困难挑战"
    assert houchen_quote.quote_coverage_ratio("政治局", seg) > 0
    assert houchen_quote.quote_coverage_ratio(seg, seg) == 1.0
    assert houchen_quote.quote_coverage_ratio("", seg) == 0.0


# ---------------------------------------------------------------------------
# Integration: VTT_BODY from PR-1 fixtures
# ---------------------------------------------------------------------------

def test_normalizer_works_on_pr1_vtt_fixture():
    """The PR-1 fixture `VTT_BODY` must parse cleanly and produce two segments."""
    from houchen_fixtures.scenario import VTT_BODY
    cues = norm.parse_vtt(VTT_BODY)
    assert len(cues) == 2
    segs = norm.normalize_cues(cues)
    assert len(segs) == 2
    assert segs[0].text == "中央政治局"
    assert segs[1].text == "第二个 cue"