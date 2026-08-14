"""Backfill legacy 待解读 briefs into the insight pipeline (Phase D).

One-shot migration. Reads every brief under 宏观经济/_pipeline/待解读/,
classifies it, and (with --apply):

  * legacy brief  -> ResearchItem + reconstructed EvidenceSnapshots (from the
    store observations + content-addressed snapshot files, NEVER from the
    brief's own prose) + a queued GeneratedInsight, drained later by
    `run.py --insights-only`.
  * iteration brief (E2E leftovers of an already-published period) -> archive
    only, no ledger task.

All briefs are copied (not moved/deleted) to _done/legacy/ with a migration
index; deleting the originals stays a separate human decision.

Usage:
  python3 scripts/backfill_insights.py --dry-run   # default: print plan only
  python3 scripts/backfill_insights.py --apply
"""
import argparse
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import insight_context  # noqa: E402
import insight_render  # noqa: E402
import ledger  # noqa: E402
import paths  # noqa: E402
import readings_cache  # noqa: E402
import store  # noqa: E402

BRIEF_DIR = "宏观经济/_pipeline/待解读"
ARCHIVE_DIR = "宏观经济/_pipeline/_done/legacy"
INDEX_PATH = f"{ARCHIVE_DIR}/迁移索引.md"

# Publisher per source, mirroring what run.py records at collection time.
PUBLISHERS = {
    "cn_mof": "财政部",
    "cn_stats_inv": "国家统计局",
    "cn_stats_cpi": "国家统计局",
    "cn_stats_ppi": "国家统计局",
    "cn_stats_pmi": "国家统计局",
    "cn_pbc": "中国人民银行",
    "fred": "FRED (St. Louis Fed)",
}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.S)
FLAG_RE = re.compile(r"^- \*\*(.+?)\*\*", re.M)


def _list_briefs():
    """Filenames under 待解读/, via REST listing with a direct-FS fallback."""
    vault_root = _vault_root()
    folder = os.path.join(vault_root, BRIEF_DIR)
    try:
        # Underscore-prefixed files (e.g. _说明.md) are folder metadata, not briefs.
        return sorted(f for f in os.listdir(folder)
                      if f.endswith(".md") and not f.startswith("_"))
    except OSError:
        return []


def _vault_root():
    """Locate the vault root for read-only listing (writes still go via REST)."""
    candidates = [
        os.path.expanduser("~/Documents/Obsidian Vault"),
    ]
    for path in candidates:
        if os.path.isdir(os.path.join(path, BRIEF_DIR)):
            return path
    raise SystemExit("vault 待解读 folder not found")


def _read_brief(filename):
    path = os.path.join(_vault_root(), BRIEF_DIR, filename)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse_brief(filename, text):
    """Extract source/generated from frontmatter and framework flags from body."""
    meta = {}
    match = FRONTMATTER_RE.match(text)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
    flags = [m.group(1).strip() for m in FLAG_RE.finditer(text)]
    return {
        "filename": filename,
        "source": meta.get("source", "?"),
        "generated": meta.get("generated", "?"),
        "flags": flags,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def classify(brief, published_periods):
    """legacy -> rebuild ledger entities; iteration -> archive only.

    A brief is an iteration leftover when its data period already has a
    published insight (E2E re-fetches of the same release).
    """
    cache = readings_cache.load()
    period = None
    for key, value in cache.items():
        if key.startswith(f"{brief['source']}:"):
            period = value.get("period")
            break
    if period and period in published_periods:
        return "iteration", period
    return "legacy", period


def _published_periods(conn):
    """Data periods (observed_period) of published insights' evidence."""
    rows = conn.execute(
        "SELECT DISTINCT e.observed_period FROM evidence_snapshot e"
        " JOIN insight_provenance p ON p.evi_id = e.evi_id"
        " JOIN ledger_event ev ON ev.entity_type='generated_insight'"
        "  AND ev.entity_id = p.ins_id AND ev.to_status='published'"
    ).fetchall()
    return {row[0] for row in rows}


def _snapshot_for(source, period):
    path = os.path.join(paths.SNAPS, source, f"release-{period}.txt")
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    return path, hashlib.sha256(content.encode("utf-8")).hexdigest()


def _evidence_exists(conn, metric_id, period, sha):
    return conn.execute(
        "SELECT 1 FROM evidence_snapshot WHERE metric_id=? AND observed_period=?"
        " AND content_sha256=? LIMIT 1",
        (metric_id, period, sha),
    ).fetchone() is not None


def _snapshot_meta(source, period):
    """Parse url/title from a pre-T2 CN snapshot header (url=... / title=...)."""
    path, sha = _snapshot_for(source, period)
    meta = {"url": None, "title": None, "path": path, "sha": sha}
    if not path:
        return meta
    with open(path, encoding="utf-8") as handle:
        for line in handle.read().splitlines():
            if line.startswith("url="):
                meta["url"] = line[4:].strip()
            elif line.startswith("title="):
                meta["title"] = line[6:].strip()
            if meta["url"] and meta["title"]:
                break
    return meta


def rebuild_evidence(conn, source):
    """Recreate the EvidenceSnapshots a collection run would have recorded.

    Values come from the store/cache (first-hand), content hash from the
    saved release snapshot; the brief itself is never a source.
    """
    cache = readings_cache.load()
    entries = {k: v for k, v in cache.items() if k.startswith(f"{source}:")}
    if not entries:
        return [], "no readings cache entries"
    periods = {v.get("period") for v in entries.values()}
    if len(periods) != 1:
        return [], f"inconsistent periods {sorted(p for p in periods if p)}"
    period = periods.pop()
    meta = _snapshot_meta(source, period)
    if not meta["sha"]:
        return [], f"snapshot release-{period}.txt missing"
    created = []
    for key, entry in sorted(entries.items()):
        metric_id = key
        if _evidence_exists(conn, metric_id, period, meta["sha"]):
            continue
        evi_id = ledger.create_evidence_snapshot(
            conn, source_url=meta["url"], publisher=PUBLISHERS.get(source),
            published_at=period, observed_period=period, metric_id=metric_id,
            value=entry.get("value"), unit=entry.get("unit", ""),
            content_sha256=meta["sha"], raw_path=meta["path"],
            included=[f"{key}={entry.get('value') if entry.get('value') is not None else entry.get('yoy_pct')}"],
            missing=[],
        )
        created.append(evi_id)
    conn.commit()
    # Include pre-existing evidence of this source+period (idempotent re-run).
    all_ids = [
        row[0] for row in conn.execute(
            "SELECT evi_id FROM evidence_snapshot WHERE metric_id LIKE ?"
            " AND observed_period=? AND content_sha256=? ORDER BY metric_id",
            (f"{source}:%", period, meta["sha"]),
        ).fetchall()
    ]
    return all_ids, None


def _queue_legacy_insight(conn, source, evi_ids, flags, title):
    cache = readings_cache.load()
    research = conn.execute(
        "SELECT rit_id FROM research_item WHERE queue_source=? AND title=? LIMIT 1",
        (f"legacy:{source}", title),
    ).fetchone()
    if research:
        rit_id = research[0]
    else:
        rit_id = ledger.create_research_item(
            conn, queue_source=f"legacy:{source}", title=title,
            priority="normal",
        )
        conn.commit()
    fact_pack, input_sha = insight_context.build_fact_pack(
        conn, research_item_id=rit_id, evidence_ids=evi_ids,
        readings=cache, flags=flags,
    )
    root = paths.INSIGHT_FACTS
    os.makedirs(root, mode=0o700, exist_ok=True)
    target = os.path.join(root, f"{input_sha}.json")
    if not os.path.exists(target):
        tmp = f"{target}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(insight_context.canonical_json(fact_pack))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    ins_id = ledger.new_id("generated_insight")
    planned = insight_render.planned_vault_path(ins_id, fact_pack["as_of"])
    with conn:
        ins_id = ledger.create_generated_insight(
            conn, research_item_id=rit_id, input_sha256=input_sha,
            prompt_version=_prompt_version(), generator="backfill",
            model="backfill", planned_vault_path=planned, ins_id=ins_id,
            reason="legacy brief backfilled",
        )
        for index, evi_id in enumerate(evi_ids):
            ledger.create_insight_provenance(
                conn, ins_id=ins_id, source_type="evidence_snapshot",
                source_id=evi_id, role="evidence", ordinal=index,
            )
    return ins_id, rit_id


def _prompt_version():
    try:
        import insight_provider
        return insight_provider.load_prompt_and_schema()[2]
    except Exception:
        return "unknown"


def plan():
    """Dry-run plan: per-brief decision without touching the ledger or vault."""
    conn = store._connect()
    try:
        published = _published_periods(conn)
    finally:
        conn.close()
    rows = []
    for filename in _list_briefs():
        brief = parse_brief(filename, _read_brief(filename))
        kind, period = classify(brief, published)
        rows.append({**brief, "kind": kind, "period": period,
                     "size": len(brief["flags"])})
    return rows


def apply(writer):
    conn = store._connect()
    index_lines = [
        "---", "title: 待解读简报迁移索引", "---", "",
        "# 待解读 → 洞察流水线迁移记录", "",
        "| 原文件 | 处置 | 数据期 | 账本 |", "|---|---|---|---|",
    ]
    results = []
    try:
        published = _published_periods(conn)
        for filename in _list_briefs():
            brief = parse_brief(filename, _read_brief(filename))
            kind, period = classify(brief, published)
            if kind == "legacy":
                evi_ids, error = rebuild_evidence(conn, brief["source"])
                if error or not evi_ids:
                    results.append((filename, f"SKIPPED: {error or 'no evidence'}"))
                    index_lines.append(f"| {filename} | 跳过（{error or 'no evidence'}） | {period} | — |")
                    continue
                ins_id, rit_id = _queue_legacy_insight(
                    conn, brief["source"], evi_ids, brief["flags"],
                    title=f"{brief['source']} 历史简报回填（{period}）",
                )
                results.append((filename, f"QUEUED {ins_id}"))
                index_lines.append(
                    f"| {filename} | 回填为排队洞察 | {period} | {rit_id} / {ins_id} |")
            else:
                results.append((filename, "ITERATION (archive only)"))
                index_lines.append(
                    f"| {filename} | E2E 迭代产物，仅归档 | {period} | — |")
            # Non-destructive archive copy of the brief itself.
            content = _read_brief(filename)
            writer.put_pipeline(f"_done/legacy/{filename}", content)
        writer.put_pipeline("待解读/_说明.md",
                            "---\ntitle: 待解读（已迁移）\n---\n\n"
                            "历史简报已回填入洞察流水线（见 `_done/legacy/迁移索引.md`）。\n"
                            "新工作流的异常统一进入 `待审/`；本目录仅保留归档。\n")
        writer.put_pipeline("_done/legacy/迁移索引.md", "\n".join(index_lines) + "\n")
    finally:
        conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.apply:
        print(f"{'文件':<40} {'判定':<10} 数据期")
        for row in plan():
            print(f"{row['filename']:<40} {row['kind']:<10} {row['period']}")
        print("\n--dry-run：未做任何修改。加 --apply 执行回填 + 归档（不删除原文件）。")
        return

    from vault_writer import VaultWriter
    results = apply(VaultWriter())
    for filename, outcome in results:
        print(f"{filename:<40} {outcome}")
    print("\n回填完成。原简报未删除（已复制到 _done/legacy/，见迁移索引）。"
          "\n排队洞察将在 insights.enabled 后由 `run.py --insights-only` 生成。")


if __name__ == "__main__":
    main()
