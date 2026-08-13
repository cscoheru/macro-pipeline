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

ECON_LABEL = {"us": "🇺🇸", "cn": "🇨🇳"}
ECON_NAME = {"us": "美国", "cn": "中国"}

CN_PARSERS = {
    "parse_mof_fiscal": cn_parsers.parse_mof_fiscal,
    "parse_stats_investment": cn_parsers.parse_stats_investment,
    "parse_stats_cpi": cn_parsers.parse_stats_cpi,
    "parse_stats_ppi": cn_parsers.parse_stats_ppi,
    "parse_stats_pmi": cn_parsers.parse_stats_pmi,
    "parse_pbc_financial": cn_parsers.parse_pbc_financial,
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
    """Record a content-addressed evidence snapshot for a new observation (T2/G2)."""
    conn = None
    try:
        conn = store._connect()
        with conn:
            ledger.create_evidence_snapshot(
                conn, source_url=url, publisher=publisher,
                published_at=period, observed_period=period, metric_id=metric_id,
                value=value, unit=unit, content_sha256=sha, raw_path=raw_path,
                included=included, missing=[])
    except Exception:
        logging.warning("ledger.create_evidence_snapshot(%s/%s) failed:\n%s",
                        source, metric_id, traceback.format_exc())
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
        if not detector.is_new_period("fred", sid, latest_period, state):
            logging.info("fred/%s no new data (latest=%s)", sid, latest_period)
            continue
        store.upsert_observations("fred", sid, rows)
        snap_path, snap_sha = save_local_snapshot("fred", sid, csv_text, latest_period)
        history = store.get_history("fred", sid, limit=30)
        st = stats_mod.compute_stats(history, display=s.get("display", "level"))
        detector.mark_seen("fred", sid, latest_period, state)
        # T2/G2: content-addressed evidence snapshot for this observation.
        _record_evidence("fred", f"fred:{sid}", st["value"] if st else None,
                         s.get("unit", ""), latest_period, snap_path, snap_sha,
                         included=[f"{sid}={st['value']}" if st else sid],
                         url=f"https://fred.stlouisfed.org/series/{sid}",
                         publisher="FRED (St. Louis Fed)")
        logging.info("fred/%s NEW period=%s value=%s", sid, latest_period,
                     fmt(st["value"]) if st else "?")
        updates.append({"id": sid, "name": s["name"], "unit": s.get("unit", ""),
                        "economy": econ, "source": "fred", "stats": st})
    return updates, None


def process_cn_release(cfg, state, src_name):
    """Generic China-HTML processor: discover -> parse -> store. Returns (updates, error)."""
    scfg = cfg[src_name]
    try:
        title, url = fetcher.discover_latest_release(scfg["listing_url"], scfg["title_regex"])
    except Exception as e:
        _record_failure(src_name, "_period", "discover_error", str(e))
        return [], f"{src_name} 发现最新发布稿失败: {e}"
    if not url:
        _record_failure(src_name, "_period", "discover_nomatch",
                        f"listing未匹配 regex={scfg['title_regex']}")
        return [], f"{src_name} 列表未匹配到发布稿（regex={scfg['title_regex']}）"
    try:
        text = fetcher.strip_tags(fetcher.fetch_html(url))
        parsed = CN_PARSERS[scfg["parser"]](title, text)
    except Exception as e:
        logging.warning("%s parse failed:\n%s", src_name, traceback.format_exc())
        _record_failure(src_name, "_period", "parse_error", f"{e}（可能源站改版）")
        return [], f"{src_name} 解析失败（可能源站改版）: {e}"

    period = parsed["period"]
    if not detector.is_new_period(src_name, "_period", period, state):
        logging.info("%s no new period (latest=%s)", src_name, period)
        return [], None

    snapshot = f"period={period}\ntitle={title}\nurl={url}\n\n{text}"
    snap_path, snap_sha = save_local_snapshot(src_name, "release", snapshot, period, ext="txt")
    economy = scfg.get("economy", "cn")
    updates = []
    for key, m in parsed["metrics"].items():
        if m.get("value") is not None:
            store.upsert_observations(src_name, key, [(period, m["value"])])
        if m.get("yoy") is not None:
            store.upsert_observations(src_name, _yoy_key(key), [(period, m["yoy"])])
        # T2/G2: one content-addressed evidence record per cited metric.
        _record_evidence(src_name, f"{src_name}:{key}", m.get("value"),
                         m.get("unit") or "", period, snap_path, snap_sha,
                         included=[f"{key}={m.get('value')}"], url=url)
        st = {"value": m.get("value"), "yoy_pct": m.get("yoy"),
              "mom_pct": None, "trend": "—", "date": period}
        updates.append({"id": key, "name": m["name"], "unit": m.get("unit") or "",
                        "economy": economy, "source": src_name, "stats": st})
    detector.mark_seen(src_name, "_period", period, state)
    logging.info("%s NEW period=%s metrics=%d (%s)", src_name, period, len(updates), title)
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
        f"本次检测到 **{len(updates)}** 项。请套用 [[01-研究方法-李厚辰]] 六步法 + 手册 F1-F7 框架写解读，完成后移入 `_done/`。",
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
    lines.append("- 处理完将本文件移到 `_done/`")
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
    lines += ["", "建议：套用对应框架写综合解读，关联 [[00-中国宏观体检]] / [[00-美国宏观体检]] 与研究笔记。", ""]
    vw.put_pipeline(f"待解读/{stamp}-cross.md", "\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(sources_requested):
    setup_logging()
    cfg = load_config()
    state = detector.load_state()
    logging.info("=== pipeline run start (sources=%s) ===", sources_requested)

    targets = sources_requested or [k for k in cfg
                                    if k != "triggers" and isinstance(cfg[k], dict)
                                    and cfg[k].get("enabled", True)]
    try:
        vw = vault_writer.VaultWriter()
    except Exception as e:
        logging.error("vault writer init failed: %s — vault writes skipped", e)
        vw = None

    cache = readings_cache.load()
    bootstrap_cache(cache, cfg)

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
        _record_research_item(
            queue_source=src,
            title=f"{src} 新数据 {len(updates)} 项（{', '.join(u['name'] for u in updates[:3])}）")
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


def main():
    ap = argparse.ArgumentParser(description="Macro data pipeline")
    ap.add_argument("--source", action="append", help="source to run (repeatable); default all enabled")
    ap.add_argument("--rebuild", action="store_true",
                    help="only rebuild 宏观经济/_pipeline/最新读数.md from cache, then exit (no fetch)")
    args = ap.parse_args()

    setup_logging()
    cfg = load_config()
    if args.rebuild:
        try:
            vw = vault_writer.VaultWriter()
            cache = readings_cache.load()
            bootstrap_cache(cache, cfg)
            readings_cache.save(cache)
            rebuild_latest_readings(vw, cache)
            logging.info("rebuilt 最新读数.md from cache (%d series)", len(cache))
        except Exception:
            logging.error("rebuild failed:\n%s", traceback.format_exc())
        return
    run(args.source)


if __name__ == "__main__":
    main()
