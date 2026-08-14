"""Build deterministic, replayable fact packs for insight generation."""
import hashlib
import json
from decimal import Decimal


FACT_PACK_VERSION = "1"
HISTORY_LIMIT = 24

OFFICIAL_SOURCES = {
    "fred": "Federal Reserve Economic Data (FRED)",
    "cn_mof": "中华人民共和国财政部",
    "cn_pbc": "中国人民银行",
    "cn_stats_cpi": "国家统计局",
    "cn_stats_inv": "国家统计局",
    "cn_stats_pmi": "国家统计局",
    "cn_stats_ppi": "国家统计局",
}

FRAMEWORKS = {
    "F1": "区分货币存量与流通速度，观察资金是否从账面进入交易。",
    "F2": "同时核对货币条件、实际利率、债息与财政主导约束。",
    "F3": "分开资产价格、抵押品价值和实体现金流，检查资产负债表传导。",
    "F4": "检查房地产与汇率两类阀门，以及资金停留和外流压力。",
    "F5": "沿就业、收入、需求、价格链验证总需求变化。",
    "F6": "核对中央与地方财政、基建和政府性基金的约束与行为。",
    "F7": "把观察写成可证伪 Claim、Forecast、Review 和下一验证点。",
    "F8": "用历史危机机制对照，不以表面相似替代资产负债表与制度差异。",
}

DERIVED_DEFINITIONS = (
    {
        "id": "cn_m2_minus_cpi",
        "name": "M2同比与CPI同比差",
        "a": ("cn_pbc:pbc_m2", "yoy_pct"),
        "b": ("cn_stats_cpi:cpi_yoy", "yoy_pct"),
        "operator": "minus",
        "unit": "个百分点",
        "stock_flow_note": "比较的是两个同比增速，不是把M2存量与CPI指数直接相减。",
    },
    {
        "id": "cn_m2_minus_m1",
        "name": "M2同比与M1同比差",
        "a": ("cn_pbc:pbc_m2", "yoy_pct"),
        "b": ("cn_pbc:pbc_m1", "yoy_pct"),
        "operator": "minus",
        "unit": "个百分点",
        "stock_flow_note": "比较的是同口径增速差，用作资金定期化线索。",
    },
)


def canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def content_sha256(value):
    payload = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(conn, query, params):
    cur = conn.execute(query, params)
    row = cur.fetchone()
    return {item[0]: row[index] for index, item in enumerate(cur.description)} if row else None


def _json_list(value):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _split_metric(metric_id):
    if not metric_id or ":" not in metric_id:
        return None, None
    return tuple(metric_id.split(":", 1))


def _history(conn, source, series):
    if not source or not series:
        return []
    rows = conn.execute(
        "SELECT date, value FROM observations WHERE source=? AND series=? "
        "ORDER BY date DESC LIMIT ?", (source, series, HISTORY_LIMIT),
    ).fetchall()
    return [{"period": date, "value": value} for date, value in reversed(rows)]


def _evidence(conn, evidence_id):
    row = _row(conn, "SELECT * FROM evidence_snapshot WHERE evi_id=?", (evidence_id,))
    if not row:
        raise ValueError(f"unknown evidence snapshot: {evidence_id}")
    source, series = _split_metric(row["metric_id"])
    history = _history(conn, source, series)
    publisher = row["publisher"] or OFFICIAL_SOURCES.get(source) or source or "unknown"
    return {
        "id": row["evi_id"],
        "source": source,
        "source_url": row["source_url"],
        "publisher": publisher,
        "official_primary": source in OFFICIAL_SOURCES,
        "published_at": row["published_at"],
        "observed_period": row["observed_period"],
        "metric_id": row["metric_id"],
        "value": row["value"],
        "unit": row["unit"] or "",
        "methodology_version": row["methodology_version"],
        "content_sha256": row["content_sha256"],
        "included_metrics": _json_list(row["included_metrics"]),
        "missing_metrics": _json_list(row["missing_metrics"]),
        "history": history,
        "previous_value": history[-2]["value"] if len(history) > 1 else None,
    }


def _related_claims(conn, research_item, evidence_ids, requested_ids):
    ids = set(requested_ids or [])
    if research_item.get("claim_id"):
        ids.add(research_item["claim_id"])
    rows = conn.execute("SELECT clm_id, evidence_ids FROM claim ORDER BY created_at").fetchall()
    for claim_id, cited in rows:
        if set(_json_list(cited)) & set(evidence_ids):
            ids.add(claim_id)
    claims = []
    for claim_id in sorted(ids):
        row = _row(conn, "SELECT * FROM claim WHERE clm_id=?", (claim_id,))
        if not row:
            raise ValueError(f"unknown claim: {claim_id}")
        claims.append({
            "id": claim_id,
            "as_of_time": row["as_of_time"],
            "statement": row["statement"],
            "scope": row["scope"],
            "mechanism": row["mechanism"],
            "alternative_explanations": _json_list(row["alternative_explanations"]),
            "confidence": row["confidence"],
            "status": _status(conn, "claim", claim_id, row["initial_status"]),
            "evidence_ids": _json_list(row["evidence_ids"]),
        })
    return claims


def _status(conn, entity_type, entity_id, initial_status):
    rows = conn.execute(
        "SELECT to_status FROM ledger_event WHERE entity_type=? AND entity_id=? "
        "ORDER BY occurred_at, evt_id", (entity_type, entity_id),
    ).fetchall()
    return rows[-1][0] if rows else initial_status


def _forecasts(conn, claim_ids, requested_ids):
    ids = set(requested_ids or [])
    if claim_ids:
        marks = ",".join("?" for _ in claim_ids)
        rows = conn.execute(
            f"SELECT fcst_id FROM forecast WHERE claim_id IN ({marks})", tuple(claim_ids),
        ).fetchall()
        ids.update(item[0] for item in rows)
    result = []
    for forecast_id in sorted(ids):
        row = _row(conn, "SELECT * FROM forecast WHERE fcst_id=?", (forecast_id,))
        if not row:
            raise ValueError(f"unknown forecast: {forecast_id}")
        result.append({
            "id": forecast_id,
            "claim_id": row["claim_id"],
            "metric_id": row["metric_id"],
            "target_period": row["target_period"],
            "decision_rule": row["decision_rule"],
            "threshold": row["threshold"],
            "direction": row["direction"],
            "review_due_at": row["review_due_at"],
            "status": _status(conn, "forecast", forecast_id, row["initial_status"]),
        })
    return result


def _reading(cache, key, field):
    entry = (cache or {}).get(key) or {}
    value = entry.get(field)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _derived_values(cache):
    result = []
    for definition in DERIVED_DEFINITIONS:
        a_value = _reading(cache, *definition["a"])
        b_value = _reading(cache, *definition["b"])
        if a_value is None or b_value is None:
            continue
        value = float(Decimal(str(a_value)) - Decimal(str(b_value)))
        result.append({
            "id": definition["id"],
            "name": definition["name"],
            "formula": f"{definition['a'][0]}.{definition['a'][1]} - "
                       f"{definition['b'][0]}.{definition['b'][1]}",
            "inputs": {"a": a_value, "b": b_value},
            "value": value,
            "unit": definition["unit"],
            "stock_flow_note": definition["stock_flow_note"],
        })
    return result


def _quality_gate(evidence, derived, flags):
    publishers = {item["publisher"] for item in evidence if item["official_primary"]}
    return {
        "official_primary_only": all(item["official_primary"] for item in evidence),
        "official_evidence_count": sum(item["official_primary"] for item in evidence),
        "independent_publisher_count": len(publishers),
        "unresolved_scope_conflicts": [],
        "multi_book_checklist": {
            "original_tables_first": all(item["official_primary"] for item in evidence),
            "period_scope_unit_explicit": all(
                item["observed_period"] and item["unit"] is not None for item in evidence
            ),
            "stock_flow_arithmetic_precomputed": all(
                item.get("stock_flow_note") for item in derived
            ),
            "cross_book_signal_present": len(publishers) >= 2 or bool(derived),
            "trigger_flags_are_leads_not_conclusions": bool(flags),
        },
    }


def build_fact_pack(conn, *, research_item_id, evidence_ids, readings=None,
                    flags=None, claim_ids=None, forecast_ids=None):
    """Return (fact_pack, input_sha256) without timestamps or other volatile data."""
    research = _row(
        conn, "SELECT * FROM research_item WHERE rit_id=?", (research_item_id,),
    )
    if not research:
        raise ValueError(f"unknown research item: {research_item_id}")
    unique_evidence_ids = list(dict.fromkeys(evidence_ids))
    if not unique_evidence_ids:
        raise ValueError("fact pack requires at least one evidence snapshot")
    evidence = [_evidence(conn, item) for item in unique_evidence_ids]
    claims = _related_claims(conn, research, unique_evidence_ids, claim_ids)
    forecasts = _forecasts(conn, [item["id"] for item in claims], forecast_ids)
    derived = _derived_values(readings or {})
    normalized_flags = sorted(set(flags or []))
    as_of = max(item["observed_period"] or "" for item in evidence)
    allowed_ids = sorted(
        unique_evidence_ids + [research_item_id]
        + [item["id"] for item in claims] + [item["id"] for item in forecasts]
    )
    pack = {
        "fact_pack_version": FACT_PACK_VERSION,
        "as_of": as_of,
        "research_item": {
            "id": research_item_id,
            "queue_source": research["queue_source"],
            "title": research["title"],
            "priority": research["priority"],
        },
        "evidence": evidence,
        "claims": claims,
        "forecasts": forecasts,
        "derived_values": derived,
        "trigger_flags": normalized_flags,
        "frameworks": FRAMEWORKS,
        "quality_gate": _quality_gate(evidence, derived, normalized_flags),
        "allowed_ids": allowed_ids,
    }
    return pack, content_sha256(pack)
