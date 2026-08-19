#!/usr/bin/env python3
"""Macro data pipeline entry point.

Phase 1: FRED (US) — fetch CSV -> change-detect -> store -> stats -> cache.
Phase 3: China (财政部/统计局) — discover latest release -> parse -> store -> cache.

Both write a uniform "update" shape; the vault 最新读数 table is rendered from a
lightweight JSON cache (data/latest_readings.json), decoupling display from
source-specific stat math. Writes ONLY to 宏观经济/_pipeline/ via Obsidian REST.
Deep interpretation is left for Claude in the next session (待解读/ briefs).
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import datetime
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import yaml
import paths
import fetcher
import store
import ledger
import detector
import stats as stats_mod
import vault_writer
import notify
import readings_cache
import cn_parsers
import jp_parsers  # noqa: F401  -- registered into INT_PARSERS below
import de_parsers  # noqa: F401  -- registered into INT_PARSERS below
import insight_context
import insight_provider
import insight_render
import insight_runner

ECON_LABEL = {"us": "🇺🇸", "cn": "🇨🇳", "jp": "🇯🇵", "de": "🇩🇪"}
ECON_NAME = {"us": "美国", "cn": "中国", "jp": "日本", "de": "德国"}

# International parsers (cn + jp + de). The cn_release flow in
# process_cn_release is intentionally generic; the name persists for backwards
# compat with existing source configs.
INT_PARSERS = {
    "parse_mof_fiscal": cn_parsers.parse_mof_fiscal,
    "parse_stats_investment": cn_parsers.parse_stats_investment,
    "parse_stats_cpi": cn_parsers.parse_stats_cpi,
    "parse_stats_ppi": cn_parsers.parse_stats_ppi,
    "parse_stats_pmi": cn_parsers.parse_stats_pmi,
    "parse_pbc_financial": cn_parsers.parse_pbc_financial,
    # Japan (BOJ / Statistics Bureau / Cabinet Office)
    "parse_jp_cpi": jp_parsers.parse_jp_cpi,
    "parse_jp_ppi": jp_parsers.parse_jp_ppi,
    "parse_jp_unrate": jp_parsers.parse_jp_unrate,
    "parse_jp_gdp": jp_parsers.parse_jp_gdp,
    "parse_jp_policy": jp_parsers.parse_jp_policy,
    # Germany (Destatis English press releases)
    "parse_de_cpi": de_parsers.parse_de_cpi,
    "parse_de_ppi": de_parsers.parse_de_ppi,
    "parse_de_unrate": de_parsers.parse_de_unrate,
    "parse_de_gdp": de_parsers.parse_de_gdp,
}


def setup_logging():
    os.makedirs(paths.LOGS, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(paths.LOGS, "pipeline.log"), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_config():
    with open(paths.SOURCES_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d-%H%M")


def fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def fmt_value(v, unit=""):
    if v is None:
        return "—"
    if isinstance(v, float):
        s = f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}"
    else:
        s = str(v)
    return f"{s} {unit}".strip() if unit else s


def display_value(value, yoy, unit):
    """Value cell: level+unit if available, else the reported YoY (for % -only series)."""
    if value is not None:
        return fmt_value(value, unit)
    if yoy is not None:
        return f"{fmt(yoy)}% 同比"
    return "—"


def save_local_snapshot(source, label, text, period, ext="csv"):
    """Content-addressed snapshot: filename embeds a sha256 prefix so a same-period
    revision creates a new file instead of overwriting prior evidence (T2)."""
    d = os.path.join(paths.SNAPS, source)
    os.makedirs(d, exist_ok=True)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = os.path.join(d, f"{label}-{period}-{sha[:12]}.{ext}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path, sha


def _yoy_key(key: str) -> str:
    """YoY series key without double _yoy suffix (cpi_yoy stays cpi_yoy)."""
    return key if key.endswith("_yoy") else key + "_yoy"


# --- Ledger integration helpers. Acquisition-first: every one logs and continues,
#     never breaking data collection if the ledger write fails. ---

def _record_failure(source, series, error_class, detail, last_valid_evi=None):
    """Persist a source failure event (G1). Never raises."""
    conn = None
    try:
        conn = store._connect()
        with conn:
            ledger.record_failure(conn, source=source, series=series,
                                  error_class=error_class, detail=detail,
                                  last_valid_evi=last_valid_evi)
    except Exception:
        logging.warning("ledger.record_failure(%s/%s) failed", source, series)
    finally:
        if conn:
            conn.close()


def _record_evidence(source, metric_id, value, unit, period, raw_path, sha,
                     included, url=None, publisher=None):
    """Record a content-addressed evidence snapshot for a new observation (T2/G2).

    Returns the evi_id (or None on failure) so the insight queue can link it.
    """
    conn = None
    try:
        conn = store._connect()
        with conn:
            return ledger.create_evidence_snapshot(
                conn, source_url=url, publisher=publisher,
                published_at=period, observed_period=period, metric_id=metric_id,
                value=value, unit=unit, content_sha256=sha, raw_path=raw_path,
                included=included, missing=[])
    except Exception:
        logging.warning("ledger.create_evidence_snapshot(%s/%s) failed:\n%s",
                        source, metric_id, traceback.format_exc())
        return None
    finally:
        if conn:
            conn.close()


def _record_research_item(queue_source, title, source_event_id=None, priority="normal"):
    """Queue one research item when a source produces new data."""
    conn = None
    try:
        conn = store._connect()
        with conn:
            return ledger.create_research_item(
                conn, queue_source=queue_source, title=title,
                source_event_id=source_event_id, priority=priority)
    except Exception:
        logging.warning("ledger.create_research_item(%s) failed", queue_source)
        return None
    finally:
        if conn:
            conn.close()


# --- Insight queue helpers (acquisition-first: failures log + continue). ---
# Queue-first: the fact pack is built, content-addressed, persisted, and a
# 'queued' generated_insight row inserted in one transaction at collection
# time. Generation + publish happen later in _drain_insights (which itself
# never breaks collection). The whole subsystem is feature-flagged and
# default-off; see lib/insight_runner.py and plans/eager-snacking-micali.md.

def _insight_model_name():
    """Model name for queue idempotency, without requiring the API key."""
    try:
        return insight_provider.load_config().model
    except insight_provider.ConfigurationError:
        return "claude-fable-5"


def _insight_generator_name():
    """Provider family actually configured in insight.env (for provenance)."""
    try:
        return insight_provider.load_config().provider
    except insight_provider.ConfigurationError:
        return "anthropic"


def _persist_fact_pack(fact_pack, input_sha256):
    """Content-addressed fact pack at INSIGHT_FACTS/<sha>.json (idempotent)."""
    root = paths.INSIGHT_FACTS
    os.makedirs(root, mode=0o700, exist_ok=True)
    target = os.path.join(root, f"{input_sha256}.json")
    if os.path.exists(target):
        return target
    tmp = f"{target}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(insight_context.canonical_json(fact_pack))
        handle.flush()
        os.fsync(handle.fileno())
    # Match persist_artifact/persist_response: the fact pack is pre-publication
    # evidence, keep it 0600 like its siblings.
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def _queue_source_insight(src, updates, flags, cache, rit_id):
    """Build + persist a fact pack and insert a queued generated_insight row.

    One fact pack per source-release (mirrors write_queue_brief granularity).
    Returns ins_id or None on any failure (acquisition-first).
    """
    evi_ids = [u.get("evi_id") for u in updates if u.get("evi_id")]
    if not evi_ids or not rit_id:
        return None
    conn = None
    try:
        conn = store._connect()
        fact_pack, input_sha = insight_context.build_fact_pack(
            conn, research_item_id=rit_id, evidence_ids=evi_ids,
            readings=cache, flags=flags,
        )
        _persist_fact_pack(fact_pack, input_sha)
        prompt_version = insight_provider.load_prompt_and_schema()[2]
        # A revision article supersedes the last published article built on
        # evidence of the same metrics (None if none ever published).
        supersedes = None
        if any(u.get("revision") for u in updates):
            metric_ids = [f"{u.get('source', src)}:{u['id']}" for u in updates]
            supersedes = ledger.latest_published_for_metrics(conn, metric_ids)
            if supersedes:
                logging.info("revision insight will supersede %s", supersedes)
        ins_id = ledger.new_id("generated_insight")
        planned = insight_render.planned_vault_path(ins_id, fact_pack["as_of"])
        with conn:
            ledger.create_generated_insight(
                conn, research_item_id=rit_id, input_sha256=input_sha,
                prompt_version=prompt_version, generator=_insight_generator_name(),
                model=_insight_model_name(), planned_vault_path=planned,
                supersedes_id=supersedes,
                ins_id=ins_id,
            )
            for index, evi_id in enumerate(evi_ids):
                ledger.create_insight_provenance(
                    conn, ins_id=ins_id, source_type="evidence_snapshot",
                    source_id=evi_id, role="evidence", ordinal=index,
                )
        logging.info("queued insight %s for %s (as_of=%s, %d evidence)",
                     ins_id, src, fact_pack["as_of"], len(evi_ids))
        return ins_id
    except Exception:
        logging.warning("queue insight for %s failed:\n%s", src, traceback.format_exc())
        return None
    finally:
        if conn:
            conn.close()


def _drain_insights(vw, max_insights=None, auto_publish=False):
    """Generate queued insights and (optionally) publish ready ones.

    Provider/Vault faults never break collection — tasks stay queued or ready
    for a later run. Returns the drain summary dict (empty on config error).
    """
    try:
        provider = insight_provider.build_provider()
    except insight_provider.ConfigurationError as exc:
        logging.warning("insight drain skipped (provider not configured): %s", exc)
        return {}
    conn = None
    try:
        conn = store._connect()
        summary = insight_runner.drain(
            conn, provider=provider, writer=vw, max_insights=max_insights,
            auto_publish=auto_publish,
        )
        conn.commit()
        return summary
    except Exception:
        logging.warning("insight drain failed:\n%s", traceback.format_exc())
        return {}
    finally:
        if conn:
            conn.close()


def _notify_drain_summary(summary):
    """Surface a drain summary as one notification line (skipped if empty)."""
    if not summary:
        return
    labels = {"published": "已发布", "needs_review": "待审",
              "requeued": "重试", "failed": "失败"}
    parts = [f"{summary[k]}{labels[k]}" for k in labels if summary.get(k)]
    if parts:
        notify.notify("宏观洞察流水线", "；".join(parts))


# ---------------------------------------------------------------------------
# Source processors — return (updates, error_or_none). Each update:
#   {id, name, unit, economy, source, stats:{value, yoy_pct, mom_pct, trend, date}}
# ---------------------------------------------------------------------------

def process_fred(cfg, state):
    updates = []
    econ = cfg.get("fred", {}).get("economy", "us")
    for s in cfg.get("fred", {}).get("series", []):
        sid = s["id"]
        try:
            csv_text = fetcher.fetch_fred_series(sid)
        except Exception as e:
            logging.warning("fetch fred/%s failed: %s", sid, e)
            _record_failure("fred", sid, "fetch_error", str(e))
            continue
        rows = fetcher.parse_fred_csv(csv_text)
        if not rows:
            logging.warning("fred/%s parsed empty rows", sid)
            _record_failure("fred", sid, "empty_parse", "parse_fred_csv returned no rows")
            continue
        latest_period = rows[-1][0]
        # Revision detection: classify by (period, content hash) so an official
        # revision of the same period re-records evidence instead of being
        # silently skipped. Hash is computed from the raw CSV, identical to
        # save_local_snapshot's content addressing.
        content_sha = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        kind = detector.classify("fred", sid, latest_period, content_sha, state)
        if kind == "same":
            logging.info("fred/%s no new data (latest=%s)", sid, latest_period)
            continue
        store.upsert_observations("fred", sid, rows)
        snap_path, snap_sha = save_local_snapshot("fred", sid, csv_text, latest_period)
        history = store.get_history("fred", sid, limit=30)
        st = stats_mod.compute_stats(history, display=s.get("display", "level"))
        detector.mark_seen("fred", sid, latest_period, state, content_sha256=snap_sha)
        # T2/G2: content-addressed evidence snapshot for this observation.
        evi_id = _record_evidence("fred", f"fred:{sid}", st["value"] if st else None,
                                  s.get("unit", ""), latest_period, snap_path, snap_sha,
                                  included=[f"{sid}={st['value']}" if st else sid],
                                  url=f"https://fred.stlouisfed.org/series/{sid}",
                                  publisher="FRED (St. Louis Fed)")
        logging.info("fred/%s %s period=%s value=%s", sid,
                     "REVISED" if kind == "revision" else "NEW", latest_period,
                     fmt(st["value"]) if st else "?")
        updates.append({"id": sid, "name": s["name"], "unit": s.get("unit", ""),
                        "economy": econ, "source": "fred", "stats": st,
                        "evi_id": evi_id, "revision": kind == "revision"})
    return updates, None


def _fetch_release_text(url):
    """Fetch the body of a release page. If the URL points at a PDF (BOJ CGPI /
    MPM, Cabinet Office GDP), extract via pdftotext; otherwise strip HTML."""
    if fetcher.discover_pdf(url):
        return fetcher.pdf_to_text(fetcher.fetch_pdf(url))
    return fetcher.strip_tags(fetcher.fetch_html(url))


def process_cn_release(cfg, state, src_name):
    """Generic HTML-or-PDF release processor: discover -> fetch -> parse -> store.
    Handles both CN HTML releases and JP/DE PDF releases via the same flow;
    dispatch is by URL suffix at fetch time.

    Returns (updates, error)."""
    scfg = cfg[src_name]
    listing_url = scfg["listing_url"]
    # Optional: resolve a year aggregator (BOJ state_all/) to its newest year
    # folder (state_2026/) so we never hardcode the current year in config.
    # resolver raises RuntimeError on layout change — caught below as a
    # discover_error so the source records failure rather than crashing.
    if scfg.get("year_index"):
        try:
            listing_url = fetcher.resolve_year_index(
                listing_url, href_regex=scfg.get("year_index_href_regex"))
        except Exception as e:
            _record_failure(src_name, "_period", "discover_error", str(e))
            return [], f"{src_name} 年份索引解析失败: {e}"
    try:
        if scfg.get("hops"):
            # Multi-hop discovery (e.g. CAO GDP: top → quarter menu → data PDF)
            title, url = fetcher.discover_latest_release_chained(
                listing_url, scfg["hops"])
        else:
            title, url = fetcher.discover_latest_release(
                listing_url, scfg["title_regex"],
                href_regex=scfg.get("href_regex"),
                follow_href_regex=scfg.get("follow_href_regex"),
                href_base=scfg.get("href_base"),
            )
        # Tripwire (not gate): warn if the discovered URL looks stale. Detects
        # year-pinned listings (state_2026/) that didn't roll over on Jan 1.
        fetcher.freshness_check(url)
    except Exception as e:
        _record_failure(src_name, "_period", "discover_error", str(e))
        return [], f"{src_name} 发现最新发布稿失败: {e}"
    if not url:
        _record_failure(src_name, "_period", "discover_nomatch",
                        f"listing未匹配 regex={scfg.get('title_regex') or scfg.get('hops')}")
        return [], f"{src_name} 列表未匹配到发布稿（regex={scfg.get('title_regex') or scfg.get('hops')}）"
    try:
        text = _fetch_release_text(url)
        parsed = INT_PARSERS[scfg["parser"]](title, text, url) \
            if scfg["parser"].startswith(("parse_jp_", "parse_de_")) \
            else INT_PARSERS[scfg["parser"]](title, text)
    except Exception as e:
        logging.warning("%s parse failed:\n%s", src_name, traceback.format_exc())
        _record_failure(src_name, "_period", "parse_error", f"{e}（可能源站改版）")
        return [], f"{src_name} 解析失败（可能源站改版）: {e}"

    # Completeness gate: when the config declares expected metric_keys, refuse
    # to publish a partial parse. Without this, a layout shift would quietly
    # drop one of (cpi_yoy, cpi_mom) yet still mark the release as seen, so
    # the next run would skip the page entirely and no alert would fire.
    expected = set(scfg.get("metric_keys") or [])
    missing = expected - set(parsed["metrics"])
    if missing:
        msg = f"parser returned {sorted(parsed['metrics'])}; expected {sorted(expected)}; missing={sorted(missing)}"
        _record_failure(src_name, "_period", "parse_incomplete", msg)
        return [], f"{src_name} 解析不完整（{msg}）"

    period = parsed["period"]
    snapshot = f"period={period}\ntitle={title}\nurl={url}\n\n{text}"
    # Revision detection: same period + changed page content (title/url/text
    # all feed the hash) is an official revision, not a skip. Hash mirrors
    # save_local_snapshot's content addressing, computed before any writes.
    content_sha = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    kind = detector.classify(src_name, "_period", period, content_sha, state)
    if kind == "same":
        logging.info("%s no new period (latest=%s)", src_name, period)
        return [], None

    snap_path, snap_sha = save_local_snapshot(src_name, "release", snapshot, period, ext="txt")
    economy = scfg.get("economy", "cn")
    updates = []
    for key, m in parsed["metrics"].items():
        if m.get("value") is not None:
            store.upsert_observations(src_name, key, [(period, m["value"])])
        if m.get("yoy") is not None:
            store.upsert_observations(src_name, _yoy_key(key), [(period, m["yoy"])])
        # T2/G2: one content-addressed evidence record per cited metric.
        # For yoy-only series (CPI/PPI yoy, some investment breakdowns) the
        # parser returns no level value — the yoy reading IS the observation,
        # and the unit ("% 同比") already says so. Recording null here would
        # dead-end the validator's current_value == value gate.
        evi_value = m.get("value")
        if evi_value is None:
            evi_value = m.get("yoy")
        evi_id = _record_evidence(src_name, f"{src_name}:{key}", evi_value,
                                  m.get("unit") or "", period, snap_path, snap_sha,
                                  included=[f"{key}={evi_value}"], url=url)
        st = {"value": m.get("value"), "yoy_pct": m.get("yoy"),
              "mom_pct": None, "trend": "—", "date": period}
        updates.append({"id": key, "name": m["name"], "unit": m.get("unit") or "",
                        "economy": economy, "source": src_name, "stats": st,
                        "evi_id": evi_id, "revision": kind == "revision"})
    detector.mark_seen(src_name, "_period", period, state, content_sha256=snap_sha)
    logging.info("%s %s period=%s metrics=%d (%s)", src_name,
                 "REVISED" if kind == "revision" else "NEW", period, len(updates), title)
    return updates, None


def run_source(src, cfg, state):
    if src == "fred":
        return process_fred(cfg, state)
    if cfg.get(src, {}).get("type") == "cn_release":
        return process_cn_release(cfg, state, src)
    return [], f"unknown source {src}"


# ---------------------------------------------------------------------------
# Cache bootstrap (FRED stats come from store; fill cache gaps so the table is complete)
# ---------------------------------------------------------------------------

def bootstrap_cache(cache, cfg):
    for s in cfg.get("fred", {}).get("series", []):
        key = f"fred:{s['id']}"
        if key in cache:
            continue
        if not store.latest_observation("fred", s["id"]):
            continue
        hist = store.get_history("fred", s["id"], limit=30)
        st = stats_mod.compute_stats(hist, display=s.get("display", "level"))
        if st:
            cache[key] = {
                "source": "fred", "economy": cfg["fred"].get("economy", "us"),
                "name": s["name"], "unit": s.get("unit", ""),
                "value": st["value"], "yoy_pct": st.get("yoy_pct"),
                "mom_pct": st.get("mom_pct"), "trend": st.get("trend", "—"),
                "period": st["date"], "updated": now_ts() + " (bootstrap)",
            }


def cache_entry_from_update(u):
    st = u["stats"]
    return {
        "source": u.get("source", "?"), "economy": u.get("economy", "?"),
        "name": u["name"], "unit": u.get("unit", ""),
        "value": st.get("value"), "yoy_pct": st.get("yoy_pct"),
        "mom_pct": st.get("mom_pct"), "trend": st.get("trend", "—"),
        "period": st.get("date"), "updated": now_ts(),
    }


# ---------------------------------------------------------------------------
# Trigger engine (single-metric, safe — no eval)
# ---------------------------------------------------------------------------

def evaluate_triggers(triggers, updates):
    """Single-metric triggers (type != cross). Evaluated against this run's updates,
    so they fire exactly when the triggering data lands (no repeat)."""
    lookup = {(u.get("source", "fred"), u["id"]): u["stats"]
              for u in updates if u.get("stats")}
    flags = []
    for t in triggers or []:
        if t.get("type") == "cross":
            continue
        m = t.get("metric")
        if not m:
            continue
        st = lookup.get((m["source"], m["series"]))
        if not st:
            continue
        val = st.get(m["field"])
        if val is None:
            continue
        thr, op = t["threshold"], t.get("op", "gt")
        if op == "range":
            lo, hi = thr[0], thr[1]
            inside = lo <= val <= hi
            hit = (not inside) if t.get("invert") else inside
        else:
            hit = {"gt": val > thr, "lt": val < thr, "eq": val == thr}.get(op, False)
        if hit:
            flags.append(f"**{t['flag']}** — {t.get('note', '')}（{m['field']}={val:.2f}）")
    return flags


def _cache_val(cache, source, series, field):
    """Read a stat field for (source, series) from the readings cache."""
    e = cache.get(f"{source}:{series}")
    if not e:
        return None
    return e.get(field)


def evaluate_cross_flags(triggers, cache, run_keys):
    """Cross-series triggers (type: cross). Evaluated against the cache (latest of all
    series), but only when at least one constituent series was updated this run — so
    they fire when relevant new data arrives, not every run."""
    flags = []
    for t in triggers or []:
        if t.get("type") != "cross":
            continue
        ex = t["expr"]
        a, b = ex["a"], ex["b"]
        ka = (a["source"], a["series"])
        kb = (b["source"], b["series"])
        if ka not in run_keys and kb not in run_keys:
            continue
        va = _cache_val(cache, a["source"], a["series"], a["field"])
        vb = _cache_val(cache, b["source"], b["series"], b["field"])
        if va is None or vb is None:
            continue
        computed = {"minus": va - vb,
                    "ratio": (va / vb if vb else None)}.get(ex["op"])
        if computed is None:
            continue
        cmp = t["compare"]
        hit = {"gt": computed > cmp["threshold"],
               "lt": computed < cmp["threshold"]}.get(cmp["op"], False)
        if hit:
            flags.append(f"**{t['flag']}** — {t.get('note', '')}"
                         f"（{a['series']}({va:.1f}) {ex['op']} {b['series']}({vb:.1f}) = {computed:.1f}）")
    return flags


# ---------------------------------------------------------------------------
# Vault writers (machine-owned namespace), rendered from cache
# ---------------------------------------------------------------------------

def rebuild_latest_readings(vw, cache):
    entries = list(cache.values())
    order = {"us": 0, "cn": 1}
    entries.sort(key=lambda e: (order.get(e.get("economy", ""), 9), e.get("name", "")))
    lines = [
        "---",
        "类型: 数据流水线自动生成（脚本独占，请勿手改）",
        f"更新: {now_ts()}",
        "tags: [宏观, 数据, 自动]",
        "---",
        "",
        "# 最新读数（自动）",
        "",
        "> 由 `~/macro-pipeline` 经 Obsidian REST API 自动写入。深度解读见同目录 `待解读/`。",
        "",
        "| 经济体 | 序列 | 最新值 | 同比% | 环比% | 趋势 | 数据期 |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        label = ECON_LABEL.get(e.get("economy", ""), e.get("economy", ""))
        val_cell = display_value(e.get("value"), e.get("yoy_pct"), e.get("unit", ""))
        yoy_cell = fmt(e.get("yoy_pct")) if e.get("value") is not None else "—"
        lines.append(
            f"| {label} | {e['name']} | {val_cell} | {yoy_cell} | "
            f"{fmt(e.get('mom_pct'))} | {e.get('trend', '—')} | {e.get('period', '—')} |"
        )
    lines.append("")
    vw.put_pipeline("最新读数.md", "\n".join(lines))


def write_queue_brief(vw, updates, flags, source_name):
    stamp = now_stamp()
    econ = updates[0]["economy"] if updates else "us"
    lines = [
        "---",
        f"source: {source_name}",
        f"generated: {now_ts()}",
        f"economy: {econ}",
        f"count: {len(updates)}",
        "tags: [宏观, 待解读]",
        "---",
        f"# {source_name} 数据更新（{stamp}）",
        "",
        f"本次检测到 **{len(updates)}** 项。请套用 [[01-研究方法-李厚辰]] 六步法 + 手册 F1-F7 框架写解读，完成后移入 `宏观经济/_pipeline/_done/`。",
        "",
        "## 新数据明细",
        "",
        "| 序列 | 最新值 | 同比% | 数据期 |",
        "|---|---|---|---|",
    ]
    for u in updates:
        st = u["stats"]
        val_cell = display_value(st.get("value"), st.get("yoy_pct"), u.get("unit", ""))
        yoy_cell = fmt(st.get("yoy_pct")) if st.get("value") is not None else "—"
        lines.append(f"| {u['name']} | {val_cell} | {yoy_cell} | {st.get('date', '—')} |")
    lines.append("")
    if flags:
        lines.append("## 触发的框架 flag")
        lines.append("")
        for f in flags:
            lines.append(f"- {f}")
        lines.append("")
    econ_link = "00-中国宏观体检" if econ == "cn" else "00-美国宏观体检"
    lines.append("## 建议")
    lines.append(f"- 关联 [[{econ_link}]] 与对应研究笔记；推进 [[研究手册]] 验证点看板")
    lines.append("- 处理完将本文件移到 `宏观经济/_pipeline/_done/`")
    lines.append("")
    vw.put_pipeline(f"待解读/{stamp}-{source_name}.md", "\n".join(lines))


def append_update_log(vw, updates, flags, source_name):
    head = ", ".join(f"{u['name']}={display_value(u['stats'].get('value'), u['stats'].get('yoy_pct'), u.get('unit',''))}"
                     for u in updates[:6])
    line = f"- {now_ts()} | {source_name} | {len(updates)}项: {head}"
    if flags:
        line += " | flags: " + ";".join(f.split("—")[0].strip() for f in flags)
    vw.append_pipeline("更新日志.md", line + "\n")


def write_cross_brief(vw, cross_flags):
    """Dedicated brief for cross-series framework signals (span multiple sources)."""
    stamp = now_stamp()
    lines = [
        "---",
        "source: cross",
        f"generated: {now_ts()}",
        "tags: [宏观, 待解读, 跨序列]",
        "---",
        f"# 跨序列信号（{stamp}）",
        "",
        "本轮新数据触发了跨序列框架判断：",
        "",
    ]
    for f in cross_flags:
        lines.append(f"- {f}")
    lines += ["",
              "建议：套用对应框架写综合解读，关联 [[00-中国宏观体检]] / [[00-美国宏观体检]] 与研究笔记。",
              "处理完将本文件移到 `宏观经济/_pipeline/_done/`。",
              ""]
    vw.put_pipeline(f"待解读/{stamp}-cross.md", "\n".join(lines))


def ensure_done_archive(vw):
    """Pre-create the _done/ archive as a sibling of 待解读/.

    Obsidian drops empty folders, so a placeholder note keeps the archive
    visible. Move target is 宏观经济/_pipeline/_done/ (option A: a system
    folder, underscore-prefixed like _ledger/, parallel to 待解读/).
    Idempotent — safe to call every run.
    """
    vw.put_pipeline("_done/_说明.md", "\n".join([
        "---",
        "类型: 数据流水线自动生成（脚本独占，请勿手改）",
        "tags: [宏观, 数据, 自动]",
        "---",
        "",
        "# 已解读归档（_done）",
        "",
        "`待解读/` 中的简报处理完成后，将文件移到本目录。",
        "约定：本目录与 `待解读/` 平级，同在 `宏观经济/_pipeline/` 下。",
        "",
    ]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(sources_requested, *, insights=None, no_generate=False,
        insights_only=False, max_insights=None):
    setup_logging()
    cfg = load_config()
    state = detector.load_state()
    insights_on = insights if insights is not None else cfg.get("insights", {}).get("enabled", False)
    auto_publish = cfg.get("insights", {}).get("auto_publish", False)
    logging.info("=== pipeline run start (sources=%s, insights=%s) ===",
                 sources_requested, "on" if (insights_on or insights_only) else "off")

    # Non-source config sections (trigger rules, insight feature flags) must
    # not become run targets even when they carry enabled: true.
    _NON_SOURCE_KEYS = ("triggers", "insights")
    targets = sources_requested or [k for k in cfg
                                    if k not in _NON_SOURCE_KEYS
                                    and isinstance(cfg[k], dict)
                                    and cfg[k].get("enabled", True)]
    try:
        vw = vault_writer.VaultWriter()
    except Exception as e:
        logging.error("vault writer init failed: %s — vault writes skipped", e)
        vw = None
    if vw:
        try:
            ensure_done_archive(vw)
        except Exception:
            logging.warning("ensure_done_archive failed: %s", traceback.format_exc())

    cache = readings_cache.load()
    bootstrap_cache(cache, cfg)

    if insights_only:
        summary = _drain_insights(vw, max_insights=max_insights, auto_publish=auto_publish)
        _notify_drain_summary(summary)
        logging.info("=== insights-only drain done: %s ===", summary)
        return

    total_updates = []
    run_keys = set()  # (source, series) updated this run — gates cross-trigger evaluation
    for src in targets:
        try:
            updates, err = run_source(src, cfg, state)
        except Exception:
            logging.error("processor %s crashed:\n%s", src, traceback.format_exc())
            notify.notify("宏观数据流水线", f"{src} 处理异常，见日志")
            continue
        if err:
            logging.error("%s: %s", src, err)
            notify.notify("宏观数据流水线", err[:120])
            continue
        if not updates:
            continue
        flags = evaluate_triggers(cfg.get("triggers", []), updates)
        logging.info("source %s: %d new, %d flags", src, len(updates), len(flags))
        kind_label = "修订" if any(u.get("revision") for u in updates) else "新数据"
        rit_id = _record_research_item(
            queue_source=src,
            title=f"{src} {kind_label} {len(updates)} 项（{', '.join(u['name'] for u in updates[:3])}）")
        if insights_on and rit_id:
            # The fact pack's derived values read the cache; fold this source's
            # just-collected readings in (they are only upserted below).
            local_cache = dict(cache)
            for u in updates:
                local_cache[f"{u.get('source', src)}:{u['id']}"] = cache_entry_from_update(u)
            _queue_source_insight(src, updates, flags, local_cache, rit_id)
        if vw:
            try:
                write_queue_brief(vw, updates, flags, src)
                append_update_log(vw, updates, flags, src)
            except Exception:
                logging.error("vault write (brief/log) failed:\n%s", traceback.format_exc())
        for u in updates:
            run_keys.add((u.get("source", src), u["id"]))
            readings_cache.upsert(cache, f"{u.get('source', src)}:{u['id']}", cache_entry_from_update(u))
        total_updates.extend(updates)

    readings_cache.save(cache)
    detector.save_state(state)

    if total_updates and vw:
        try:
            rebuild_latest_readings(vw, cache)
        except Exception:
            logging.error("vault write (最新读数) failed:\n%s", traceback.format_exc())

    # Cross-series triggers: evaluate against full cache after all sources ran
    cross_flags = evaluate_cross_flags(cfg.get("triggers", []), cache, run_keys)
    if cross_flags and vw:
        try:
            write_cross_brief(vw, cross_flags)
        except Exception:
            logging.error("vault write (cross brief) failed:\n%s", traceback.format_exc())

    if total_updates:
        names = ", ".join(u["name"] for u in total_updates[:4])
        more = f" 等{len(total_updates)}项" if len(total_updates) > 4 else ""
        suffix = f" +{len(cross_flags)}跨序列信号" if cross_flags else ""
        notify.notify("宏观数据更新", f"{names}{more} — {len(total_updates)}条待解读{suffix}")
        logging.info("=== run done: %d updates, %d cross-flags, notified ===",
                     len(total_updates), len(cross_flags))
    elif cross_flags:
        notify.notify("宏观跨序列信号", "; ".join(f.split("—")[0].strip() for f in cross_flags[:2]))
        logging.info("=== run done: %d cross-flags ===", len(cross_flags))
    else:
        logging.info("=== run done: no new data ===")

    if insights_on and not no_generate:
        summary = _drain_insights(vw, max_insights=max_insights, auto_publish=auto_publish)
        _notify_drain_summary(summary)
        logging.info("insight drain: %s", summary)


def main():
    ap = argparse.ArgumentParser(description="Macro data pipeline")
    ap.add_argument("--source", action="append", help="source to run (repeatable); default all enabled")
    ap.add_argument("--rebuild", action="store_true",
                    help="only rebuild 宏观经济/_pipeline/最新读数.md from cache, then exit (no fetch)")
    ap.add_argument("--insights", action="store_true",
                    help="enable insight queue+drain this run (overrides config insights.enabled)")
    ap.add_argument("--insights-only", action="store_true",
                    help="skip collection; only drain queued insights (implies --insights)")
    ap.add_argument("--no-generate", action="store_true",
                    help="collect data but skip insight generation/publish this run")
    ap.add_argument("--max-insights", type=int, default=None,
                    help="cap how many queued insights to generate this run")
    ap.add_argument("--insights-status", action="store_true",
                    help="print insight queue summary (queued/ready/published/...) and exit")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    if args.insights_status:
        conn = store._connect()
        try:
            s = insight_runner.summarize(conn)
        finally:
            conn.close()
        print("洞察队列状态："
              f"queued={s['queued']} generating={s['generating']} "
              f"ready={s['ready']} needs_review={s['needs_review']} "
              f"published={s['published']} superseded={s['superseded']}")
        if s["oldest_queued_created_at"]:
            print(f"最老积压：{s['oldest_queued_created_at']}")
        if s["last_error_class"]:
            print(f"最近错误类别：{s['last_error_class']}")
        return
    if args.rebuild:
        try:
            vw = vault_writer.VaultWriter()
            ensure_done_archive(vw)
            cache = readings_cache.load()
            bootstrap_cache(cache, cfg)
            readings_cache.save(cache)
            rebuild_latest_readings(vw, cache)
            logging.info("rebuilt 最新读数.md from cache (%d series)", len(cache))
        except Exception:
            logging.error("rebuild failed:\n%s", traceback.format_exc())
        return
    run(args.source,
        insights=True if (args.insights or args.insights_only) else None,
        no_generate=args.no_generate,
        insights_only=args.insights_only,
        max_insights=args.max_insights)


if __name__ == "__main__":
    main()
