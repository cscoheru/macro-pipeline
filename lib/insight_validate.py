"""Local schema and evidence gates for generated macro insights."""
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import paths


PROHIBITED_CERTAINTY = (
    "必然", "注定", "肯定会", "一定会", "必定", "毫无疑问", "无疑",
    "马上崩溃", "imminent collapse", "guaranteed", "inevitable",
)
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?")
PRECISE_CRISIS_PATTERN = re.compile(
    r"\d+\s*(?:天|周|个月|月|年)(?:内|后).*?(?:崩溃|爆雷|危机)", re.IGNORECASE
)
# IDs the model may write into prose; structured id fields are checked separately.
# Each prose ID must resolve to an allowed id, or the model is smuggling a fabricated
# reference (or a tracking/exfil vector) past the structured-id gates.
NARRATIVE_ID_PATTERN = re.compile(r"(?:evi|clm|fcst|rit|ins|art|prv|att)_[0-9a-f]{32}")
# Markdown that could exfiltrate or inject when Obsidian renders the published
# note. Bare http(s) URLs are included: Obsidian auto-links them, so a plain
# URL is still an outbound-link channel.
MARKDOWN_INJECTION_PATTERN = re.compile(r"!\[|\]\(|<[A-Za-z/!]|https?://", re.IGNORECASE)
# Periods cited in prose (2026-06, 2026年6月, 6月15日, 至7月) are not statistics;
# strip them before the number gate so a bare year or month never needs an
# evidence value to match. The bare `\d{1,2}月` catches month-only fragments
# like "至7月" left behind after "2026年5月" is stripped from "2026年5月至7月".
DATE_STRIP_PATTERN = re.compile(
    r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?"
    r"|\d{4}年(?:\d{1,2}月)?(?:\d{1,2}日)?"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{1,2}月"
)
NARRATIVE_KEYS = {
    "headline", "text", "statement", "comparison", "finding", "explanation",
    "falsifier", "metric", "limitations",
}
ID_KEYS = {"id", "evidence_id", "source_id", "supporting_ids"}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple
    warnings: tuple
    cited_ids: tuple

    def as_dict(self):
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "cited_ids": list(self.cited_ids),
        }


class InsightValidationError(ValueError):
    def __init__(self, result):
        super().__init__("; ".join(result.errors))
        self.result = result


def load_schema(path=None):
    with open(path or paths.INSIGHT_SCHEMA, encoding="utf-8") as handle:
        return json.load(handle)


def _matches_type(value, expected):
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _schema_errors(value, schema, location="$", errors=None):
    errors = errors if errors is not None else []
    expected = schema.get("type")
    choices = expected if isinstance(expected, list) else [expected] if expected else []
    if choices and not any(_matches_type(value, item) for item in choices):
        errors.append(f"{location}: expected {' or '.join(choices)}")
        return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: value not in enum")
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{location}: missing required field {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{location}: unexpected field {key}")
        for key, item in value.items():
            if key in properties:
                _schema_errors(item, properties[key], f"{location}.{key}", errors)
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{location}: too few items")
        for index, item in enumerate(value):
            _schema_errors(item, schema.get("items", {}), f"{location}[{index}]", errors)
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{location}: string too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{location}: string too long")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{location}: pattern mismatch")
    return errors


def _walk(value, key=None):
    yield key, value
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, key)


def _collect_ids(document):
    ids = set()
    for key, value in _walk(document):
        if key not in ID_KEYS:
            continue
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, list):
            ids.update(item for item in value if isinstance(item, str))
    return ids


def _collect_narrative_ids(document):
    """IDs the model may have written into prose; structured id fields excluded."""
    ids = set()
    for _, text in _narrative_strings(document):
        ids.update(NARRATIVE_ID_PATTERN.findall(text))
    return ids


def _narrative_evidence_ids(document):
    """Evidence cited in substantive fields, excluding source_table render rows.

    source_table only re-states already-cited evidence for display; counting it
    toward the causal/independence gates would let a single real observation
    masquerade as multi-book support.
    """
    ids = set()
    for field in ("supporting_evidence", "counter_evidence"):
        for item in document.get(field, []):
            value = item.get("id") if isinstance(item, dict) else None
            if isinstance(value, str) and value.startswith("evi_"):
                ids.add(value)
    for item in document.get("what_changed", []):
        value = item.get("evidence_id") if isinstance(item, dict) else None
        if isinstance(value, str) and value.startswith("evi_"):
            ids.add(value)
    for item in document.get("mechanism_chain", []):
        for value in (item.get("supporting_ids") or []) if isinstance(item, dict) else []:
            if isinstance(value, str) and value.startswith("evi_"):
                ids.add(value)
    return ids


def _number_token(value):
    try:
        normalized = Decimal(str(value).replace(",", "")).normalize()
    except (InvalidOperation, ValueError):
        return None
    return str(normalized)


_ID_PREFIXES = ("evi_", "clm_", "fcst_", "rit_", "ins_", "art_", "prv_", "att_", "evt_")
# Keys whose string values carry identifier or date content; the digits embedded
# there (e.g. evi_0192..., pbc_m2, 2026-06) must not widen the allowed-number set,
# or a fabricated number that coincides with an id fragment would pass the gate.
_IDENTIFIER_KEYS = {
    "id", "evidence_id", "source_id", "metric_id", "metric", "research_item_id",
    "claim_id", "forecast_id", "allowed_ids", "content_sha256", "as_of",
    "observed_period", "published_at", "target_period", "review_due_at", "period",
    "fact_pack_version", "as_of_time",
}


def _collapse_ws(text):
    return " ".join(str(text or "").split())


def _fact_number_tokens(fact_pack):
    tokens = set()
    for key, value in _walk(fact_pack):
        if key in _IDENTIFIER_KEYS:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            token = _number_token(value)
            if token:
                tokens.add(token)
        elif isinstance(value, str):
            if any(value.startswith(prefix) for prefix in _ID_PREFIXES):
                continue
            for match in NUMBER_PATTERN.findall(value):
                token = _number_token(match)
                if token:
                    tokens.add(token)
    return tokens


def _narrative_strings(document):
    for key, value in _walk(document):
        if key in NARRATIVE_KEYS and isinstance(value, str):
            yield key, value
        elif key == "limitations" and isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield key, item


def _evidence_map(fact_pack):
    return {item["id"]: item for item in fact_pack.get("evidence", [])}


def _check_ids(document, fact_pack, errors):
    cited = _collect_ids(document)
    allowed = set(fact_pack.get("allowed_ids", []))
    unknown = sorted(cited - allowed)
    if unknown:
        errors.append("unknown or fabricated IDs: " + ", ".join(unknown))
    return cited


def _check_narrative_ids(document, allowed, errors):
    for key, text in _narrative_strings(document):
        for match in NARRATIVE_ID_PATTERN.findall(text):
            if match not in allowed:
                errors.append(f"narrative references unknown ID {match} in {key}")


def _check_content(document, errors):
    for key, text in _narrative_strings(document):
        if not _collapse_ws(text):
            errors.append(f"empty or whitespace-only field {key}")


def _is_bare_year(raw):
    """A standalone 4-digit integer in a plausible year range is a date, not a
    statistic (e.g. a model writing '2026' for the as-of year). Exempt it so the
    number gate does not demand an evidence value for a bare year."""
    return raw.isdigit() and len(raw) == 4 and 1900 <= int(raw) <= 2099


def _check_numbers(document, fact_pack, errors):
    allowed = _fact_number_tokens(fact_pack)
    for key, text in _narrative_strings(document):
        scrubbed = DATE_STRIP_PATTERN.sub(" ", text)
        for raw in NUMBER_PATTERN.findall(scrubbed):
            if _is_bare_year(raw):
                continue
            token = _number_token(raw)
            if token not in allowed:
                errors.append(f"untraceable number {raw!r} in {key}")
    for item in document.get("next_checks", []):
        threshold = item.get("threshold")
        if threshold is not None and _number_token(threshold) not in allowed:
            errors.append(f"untraceable next-check threshold: {threshold}")


def _check_changed(document, evidence, errors):
    for index, item in enumerate(document.get("what_changed", [])):
        source = evidence.get(item.get("evidence_id"))
        if not source:
            continue
        if item.get("current_value") != source.get("value"):
            errors.append(f"what_changed[{index}] current_value does not match evidence")
        if item.get("previous_value") != source.get("previous_value"):
            errors.append(f"what_changed[{index}] previous_value does not match evidence history")
        if item.get("unit") != source.get("unit"):
            errors.append(f"what_changed[{index}] unit does not match evidence")


def _check_sources(document, evidence, cited, errors):
    narrative = {item for item in _collect_narrative_ids(document) if item.startswith("evi_")}
    cited_evidence = {item for item in cited if item.startswith("evi_")} | narrative
    rows = document.get("source_table", [])
    row_ids = {item.get("evidence_id") for item in rows}
    if row_ids != cited_evidence:
        errors.append("source_table must exactly cover cited Evidence IDs")
    for index, row in enumerate(rows):
        source = evidence.get(row.get("evidence_id"))
        if not source:
            continue
        expected = (
            source["publisher"], source["observed_period"],
            source["metric_id"], source["unit"],
        )
        actual = (row.get("publisher"), row.get("period"), row.get("metric"), row.get("unit"))
        if actual != expected:
            errors.append(f"source_table[{index}] metadata does not match evidence")
        if not source.get("official_primary"):
            errors.append(f"non-primary evidence cannot auto-publish: {source['id']}")


def _check_language(document, errors):
    text = "\n".join(item for _, item in _narrative_strings(document))
    for phrase in PROHIBITED_CERTAINTY:
        if phrase.lower() in text.lower():
            errors.append(f"prohibited certainty language: {phrase}")
    if PRECISE_CRISIS_PATTERN.search(text):
        errors.append("precise crisis countdown is not publishable")
    if "<script" in text.lower() or "javascript:" in text.lower():
        errors.append("active HTML/script content is forbidden")
    if MARKDOWN_INJECTION_PATTERN.search(text):
        errors.append("markdown links, images and raw HTML are not publishable")


def _check_quality(document, fact_pack, errors, warnings):
    if document.get("bottom_line", {}).get("as_of") != fact_pack.get("as_of"):
        errors.append("bottom_line.as_of must equal fact_pack.as_of")
    gate = fact_pack.get("quality_gate", {})
    if gate.get("unresolved_scope_conflicts"):
        errors.append("fact pack has unresolved scope conflicts")
    mechanism = document.get("mechanism_chain", [])
    kinds = {item.get("kind") for item in mechanism if isinstance(item, dict)}
    causal = bool(kinds & {"derived", "inferred"})
    cited_evidence = _narrative_evidence_ids(document)
    evidence_by_id = {item["id"]: item for item in fact_pack.get("evidence", [])}
    cited_publishers = {
        evidence_by_id[evi]["publisher"]
        for evi in cited_evidence if evi in evidence_by_id
    }
    if causal:
        if len(cited_evidence) < 2:
            errors.append("causal insight must cite two Evidence IDs outside source_table")
        if len(cited_publishers) < 2:
            errors.append(
                "causal insight must cite two independent publishers outside source_table"
            )
        for index, item in enumerate(mechanism):
            if not isinstance(item, dict) or item.get("kind") not in {"derived", "inferred"}:
                continue
            step_evidence = [
                sid for sid in (item.get("supporting_ids") or [])
                if isinstance(sid, str) and sid.startswith("evi_")
            ]
            if len(step_evidence) < 2:
                errors.append(
                    f"mechanism_chain[{index}] {item.get('kind')} step needs two Evidence IDs"
                )
    if document.get("confidence") == "high" and len(cited_publishers) < 2:
        errors.append("high confidence requires two independent publishers")
    histories = [item.get("history", []) for item in fact_pack.get("evidence", [])]
    text = "\n".join(item for _, item in _narrative_strings(document))
    if "趋势" in text and histories and max(map(len, histories)) < 3:
        errors.append("trend language requires at least three historical observations")
    if any(item.get("missing_metrics") for item in fact_pack.get("evidence", [])):
        warnings.append("one or more evidence snapshots report missing metrics")


def validate_output(document, fact_pack, schema=None):
    errors = _schema_errors(document, schema or load_schema())
    warnings = []
    if errors:
        return ValidationResult(False, tuple(dict.fromkeys(errors)), tuple(warnings), ())
    if not isinstance(document, dict):
        return ValidationResult(False, ("model output must be an object",), tuple(warnings), ())
    allowed = set(fact_pack.get("allowed_ids", []))
    evidence = _evidence_map(fact_pack)
    cited = _check_ids(document, fact_pack, errors)
    _check_narrative_ids(document, allowed, errors)
    _check_numbers(document, fact_pack, errors)
    _check_changed(document, evidence, errors)
    _check_sources(document, evidence, cited, errors)
    _check_language(document, errors)
    _check_content(document, errors)
    _check_quality(document, fact_pack, errors, warnings)
    unique_errors = tuple(dict.fromkeys(errors))
    return ValidationResult(not unique_errors, unique_errors, tuple(warnings), tuple(sorted(cited)))


def assert_valid(document, fact_pack, schema=None):
    result = validate_output(document, fact_pack, schema=schema)
    if not result.ok:
        raise InsightValidationError(result)
    return result
