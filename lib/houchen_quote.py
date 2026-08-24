"""Exact-quote normalization and matching (PR-2, brief §8.6 hard gate).

The brief is unambiguous: downstream `claim_source.exact_quote` rows may only
match the frozen caption text after two purely mechanical transforms:

    - Unicode NFC normalization (so `"é"` (U+00E9) matches `"é"` (e + U+0301)).
    - Folding of any run of whitespace to a single ASCII space.

Anything else — model punctuation completion, re-styling, synonym
substitution — is OUT. This module is the single source of truth for that
rule; downstream PR-3 / PR-4 code MUST call `normalize_for_compare` (not roll
their own) so the discipline cannot drift.
"""
from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")


def normalize_for_compare(text: str) -> str:
    """Canonicalize a caption string for substring/exact comparison.

    - Strip BOM and surrounding whitespace.
    - Unicode NFC so composed/decomposed forms compare equal.
    - Fold any run of horizontal / vertical whitespace to a single space.

    The function is pure, deterministic, and stable across Python versions for
    its declared input domain. Tested explicitly for:
      - NFC vs NFD for Chinese and accented Latin.
      - Multiple internal spaces / newlines / NBSP → single space.
      - Leading / trailing whitespace dropped.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    s = s.replace("﻿", "")  # BOM
    s = _WS_RE.sub(" ", s).strip()
    return s


def exact_quote_in_segment(quote: str, segment_text: str) -> bool:
    """True iff `quote` is a substring of `segment_text` after the canonical
    normalize pass on BOTH sides.

    Brief §8.6: this is the ONLY allowed normalization for matching
    `exact_quote` against frozen subtitle text. Never model-polished text.
    """
    return normalize_for_compare(quote) in normalize_for_compare(segment_text)


def quote_coverage_ratio(quote: str, segment_text: str) -> float:
    """Return len(normalized quote) / len(normalized segment_text), 0..1.

    Used by tests to verify the substring match is non-trivial (PR-2 §8.5
    "mapping retained"). A ratio of 0 means empty quote; 1 means the quote
    IS the segment text.
    """
    nq = normalize_for_compare(quote)
    ns = normalize_for_compare(segment_text)
    if not ns:
        return 0.0
    return len(nq) / len(ns)