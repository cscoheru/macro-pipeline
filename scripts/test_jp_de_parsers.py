"""Unit tests for JP/DE parsers and their helpers.

Uses inline text fixtures rather than the on-disk snapshots because:
1. Snapshots are content-hash named (sha changes when BOJ/Destatis revise);
2. We want the assertions to be stable across quarterly revisions;
3. The fixtures exercise known risk paths (Unicode minus, "percent" vs "%",
   "lower than" / "higher than", quarterly titles, multi-row PDF tables).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import jp_parsers
import de_parsers


# ---------------------------------------------------------------------------
# JP helpers
# ---------------------------------------------------------------------------

def test_extract_pct_only_en_accepts_percent_word():
    # BOJ CGPI uses "rose 0.1 percent" — the word, not the symbol.
    text = "The Producer Price Index rose 0.1 percent from the previous month."
    out = jp_parsers.extract_pct_only_en(text, "Producer Price Index")
    assert out is not None
    assert out["yoy"] == 0.1
    assert out["unit"] == "% YoY"


def test_extract_pct_only_en_Accepts_percent_symbol():
    text = "Consumer Price Index rose 2.1 percent from a year earlier."
    out = jp_parsers.extract_pct_only_en(text, "Consumer Price Index")
    assert out is not None
    assert abs(out["yoy"] - 2.1) < 1e-9


def test_extract_pct_only_en_NegativeDirection():
    text = "Wholesale prices fell 0.4 percent year-on-year."
    out = jp_parsers.extract_pct_only_en(text, "Wholesale prices")
    assert out is not None
    assert out["yoy"] == -0.4


def test_normalize_period_jp_Monthly():
    text = "Tokyo — The unemployment rate was 2.5% in July 2026."
    assert jp_parsers.normalize_period_jp("2026", text) == "2026-07"


def test_normalize_period_jp_Quarterly_RangeForm():
    text = "Quarterly Estimates of GDP for Apr.-Jun. 2026 (The First preliminary)"
    assert jp_parsers.normalize_period_jp("2026", text) == "2026-q2"


def test_normalize_period_jp_Quarterly_QToken():
    text = "GDP for Q3 2026 was revised upward."
    assert jp_parsers.normalize_period_jp("2026", text) == "2026-q3"


def test_normalize_period_jp_NoYearReturnsNone():
    # Empty year must NOT produce "-07" / "-q2" — those would write degenerate
    # periods to the ledger and pass the unique-key check.
    assert jp_parsers.normalize_period_jp("", "July 2026 text") is None


# ---------------------------------------------------------------------------
# JP GDP — row-extraction resilience
# ---------------------------------------------------------------------------

def test_gdp_row_numbers_HandlesUnicodeMinus():
    # CAO PDF exports GDP contraction with U+2212 (mathematical minus).
    line = "国内総生産（ＧＤＰ）    −0.5    1.2    2.3    3.4    4.5    0.8"
    nums = jp_parsers._gdp_row_numbers(line)
    assert nums[0] == -0.5, f"Unicode minus must convert to float, got {nums[0]!r}"
    assert nums[-1] == 0.8


def test_gdp_row_numbers_HandlesParenthesizedContribution():
    line = "GDP  1.1  0.9  1.3  0.7  ( 0.3 )   -1.2"
    nums = jp_parsers._gdp_row_numbers(line)
    # Contribution column stripped; numeric sequence = [1.1, 0.9, 1.3, 0.7, -1.2]
    assert nums == [1.1, 0.9, 1.3, 0.7, -1.2]


def test_jp_gdp_PositionalExtraction():
    # Simulate two bilingual GDP table rows; rows[0] QoQ (5+annualized),
    # rows[1] YoY (5 quarters).
    text = "\n".join([
        "some noise line",
        "国 内 総 生 産 （ Ｇ Ｄ Ｐ )    0.2    0.4    0.3    0.1    0.5    1.5",
        "国 内 総 生 産 （ Ｇ Ｄ Ｐ )    1.0    1.1    1.3    1.5    1.8",
        "more noise",
    ])
    parsed = jp_parsers.parse_jp_gdp(
        "GDP for Apr.-Jun. 2026", text, url="https://example/gdp.pdf")
    assert parsed["period"] == "2026-q2"
    assert parsed["metrics"]["gdp_qoq"]["yoy"] == 1.5  # annualized (6th value)
    assert parsed["metrics"]["gdp_yoy"]["yoy"] == 1.8  # 5th YoY value


def test_jp_gdp_OneRowMeansIncomplete_FailsGracefully():
    # When only one GDP row is found, parser must NOT emit a YoY metric —
    # otherwise it would fall back to position 0 and write junk. _finish
    # surfaces "no metrics extracted", which the upstream process_cn_release
    # now records as parse_incomplete rather than marking the release as seen.
    import pytest
    text = "国 内 総 生 産 （ Ｇ Ｄ Ｐ )    0.2    0.4    0.3    0.1    0.5    1.5"
    with pytest.raises(ValueError, match="no metrics extracted"):
        jp_parsers.parse_jp_gdp("GDP for Apr.-Jun. 2026", text)


# ---------------------------------------------------------------------------
# JP policy rate
# ---------------------------------------------------------------------------

def test_jp_policy_PeriodFromUrlWinsOverTitle():
    # BOJ encodes the decision date in the PDF filename; that's the highest-
    # signal period source even when the title doesn't say "August 2026".
    parsed = jp_parsers.parse_jp_policy(
        "Statement on Monetary Policy",
        "the uncollateralized overnight call rate to be at around 0.5 percent.",
        url="https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k260731a.pdf",
    )
    assert parsed["period"] == "2026-07"
    assert parsed["metrics"]["policy_rate"]["value"] == 0.5


# ---------------------------------------------------------------------------
# DE helpers
# ---------------------------------------------------------------------------

def test_normalize_period_de_title_Quarterly():
    assert de_parsers.normalize_period_de_title(
        "Gross domestic product in the 2nd quarter of 2026") == "2026-q2"
    assert de_parsers.normalize_period_de_title(
        "Gross domestic product in the 4th quarter of 2025") == "2025-q4"


def test_normalize_period_de_title_QuarterlyQToken():
    assert de_parsers.normalize_period_de_title(
        "GDP Q3 2026 up 0.4%") == "2026-q3"


def test_normalize_period_de_title_Monthly():
    assert de_parsers.normalize_period_de_title(
        "Inflation rate at +2.8% in July 2026") == "2026-07"


def test_extract_pct_before_en_HandlesLowerThan():
    text = "Employment in June 2026 was 0.5% lower than in the same month a year earlier."
    out = de_parsers.extract_pct_before_en(
        text, "", direction_label="lower than")
    assert out is not None
    assert out["yoy"] == -0.5


def test_extract_pct_before_en_HandlesHigherThan():
    # Pre-2024 releases used "higher than"; parser must not silently fail.
    text = "Employment in July 2026 was 0.3% higher than in the same month a year earlier."
    out = de_parsers.extract_pct_before_en(
        text, "", direction_label="higher than")
    assert out is not None
    assert out["yoy"] == 0.3


def test_de_unrate_AcceptsBothDirections():
    # parse_de_unrate tries "lower than" first, then "higher than".
    parsed_lower = de_parsers.parse_de_unrate(
        "Employment in June 2026 down on the previous month",
        "Employment in June 2026 was 0.5% lower than in the same month a year earlier.")
    assert parsed_lower["metrics"]["employment_yoy"]["yoy"] == -0.5

    parsed_higher = de_parsers.parse_de_unrate(
        "Employment in July 2026 up on the previous month",
        "Employment in July 2026 was 0.3% higher than in the same month a year earlier.")
    assert parsed_higher["metrics"]["employment_yoy"]["yoy"] == 0.3


def test_de_gdp_QuarterlyPeriodFromTitle():
    # Destatis subtitle gives the QoQ; the headline paragraph gives the YoY.
    title = "Gross domestic product in the 2nd quarter of 2026 up 0.2%"
    body = ("Gross domestic product (GDP), 2nd quarter of 2026 +0.2% on the "
            "previous quarter (price, seasonally and calendar adjusted) "
            "+0.9% on the same quarter a year earlier (price adjusted)")
    parsed = de_parsers.parse_de_gdp(title, body)
    assert parsed["period"] == "2026-q2"
    # Two-pass extraction: "on the previous quarter" + "on the same quarter a year earlier"
    assert abs(parsed["metrics"]["gdp_qoq"]["yoy"] - 0.2) < 1e-9
    assert abs(parsed["metrics"]["gdp_yoy"]["yoy"] - 0.9) < 1e-9


# ---------------------------------------------------------------------------
# DE PPI / CPI
# ---------------------------------------------------------------------------

def test_de_ppi_WholesalePrices_BothYoYAndMoM():
    title = "Wholesale prices in July 2026: +5.3% on July 2025"
    body = ("Wholesale prices in July 2026: +5.3% on July 2025 "
            "The index also rose +0.4% on the previous month")
    parsed = de_parsers.parse_de_ppi(title, body)
    assert parsed["period"] == "2026-07"
    assert abs(parsed["metrics"]["ppi_yoy"]["yoy"] - 5.3) < 1e-9


def test_de_cpi_ExtractsBothRates():
    title = "Inflation rate at +2.8% in July 2026"
    body = ("Inflation rate at +2.8% in July 2026. "
            "Compared with June 2026, consumer prices rose by +0.8%.")
    parsed = de_parsers.parse_de_cpi(title, body)
    assert parsed["period"] == "2026-07"
    assert parsed["metrics"]["cpi_yoy"]["yoy"] == 2.8