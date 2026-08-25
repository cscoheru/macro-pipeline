#!/usr/bin/env python3
"""CLI entry point for the Hou Chen research corpus (PR-1, hardened).

Exit codes (stable, documented — P2-2):
    0  success (catalog partial returns 3, not 0)
    1  runtime / acquisition failure
    2  usage error / network authorization refused
    3  catalog partial success (some tabs failed, data persisted)
    4  data-root isolation violation / config error

dry-run (P1-4): a `--dry-run` command NEVER creates dirs, DB, raw files, or
any environment-external state; it also does NOT imply network authorization.
Real backend calls always require `--live-smoke-allow` unless a `--runner`
fixture is injected (and the runner is constrained to the canonical fixture
path, symlinks rejected — P1-4/P0-2).

Read-only commands (`status`, `coverage`) open a `mode=ro` connection and
never create directories or migrate (P2-2).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import textwrap

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_THIS_DIR, "..", "lib"))

import houchen_acquisition  # noqa: E402
import houchen_concept  # noqa: E402
import houchen_paths  # noqa: E402
import houchen_publish_paths  # noqa: E402  # PR-4 Phase 1
import houchen_publisher  # noqa: E402  # PR-4 Phase 1
import houchen_render  # noqa: E402  # PR-4 Phase 1
import houchen_runner  # noqa: E402
import houchen_search  # noqa: E402  # PR-4 Phase 0: FTS5
import houchen_status  # noqa: E402
import houchen_store  # noqa: E402
import macro_bridge  # noqa: E402  # PR-5: macro bridge
import houchen_import_transcript  # noqa: E402  # PR-5 P2b: WPS import

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_PARTIAL = 3
EXIT_CONFIG = 4

_CANONICAL_RUNNER = os.path.join(_THIS_DIR, "houchen_fixtures", "fake_ytdlp.py")


def _nonneg_int(s: str) -> int:
    """argparse type: reject a negative --limit at parse time (P2-4)."""
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError("--limit must be >= 0")
    return v


def _apply_data_root_override(args) -> None:
    if args.data_root:
        os.environ["HOUCHEN_DATA_ROOT"] = os.path.abspath(args.data_root)


def _build_runner(args):
    """Return an injected subprocess runner for the canonical fixture only.

    Production MUST NOT accept arbitrary `--runner` paths (P1-4): the runner
    is constrained to the canonical repo fixture, and symlinks are rejected.
    """
    if not args.runner:
        return None
    runner_path = os.path.realpath(args.runner)
    if runner_path != _CANONICAL_RUNNER:
        print(f"--runner must be the canonical fixture: {_CANONICAL_RUNNER}",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if os.path.islink(args.runner):
        print("--runner must not be a symlink", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    def _runner(argv, *, timeout_sec, stdin_bytes=None, cwd=None):
        import subprocess
        env = dict(os.environ)
        # Honor a caller-provided scenario dir (tests) but never let an
        # arbitrary runner path leak into FAKE_YTDLP_SCENARIO.
        env.setdefault("FAKE_YTDLP_SCENARIO", os.path.dirname(runner_path))
        return subprocess.run(
            [sys.executable, runner_path] + list(argv),
            shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_sec, check=False, cwd=cwd, env=env,
        )

    return _runner


def _open_write_db(args):
    _apply_data_root_override(args)
    try:
        return houchen_store.connect()
    except houchen_paths.DataRootError as e:
        print(f"data-root error: {e}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)


def _open_readonly_db(args):
    _apply_data_root_override(args)
    try:
        return houchen_store.connect_readonly()
    except FileNotFoundError:
        # No DB yet → emit empty status (no dirs/migration created).
        return None
    except houchen_paths.DataRootError as e:
        print(f"data-root error: {e}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)


def _empty_status():
    return {
        "schema_version": 0,
        "output_version": houchen_status.OUTPUT_VERSION,
        "generated_at": houchen_status._now(),
        "tools": {"yt_dlp_version": ""},
        "totals": {"videos": 0, "by_availability": {}, "by_content_kind": {}},
        "captions": {"frozen": 0, "pending": 0, "missing": 0,
                     "auth_required": 0, "unavailable": 0, "retryable": 0,
                     "tool_error": 0, "permanent_error": 0,
                     "raw_integrity_error": 0},
        "transcripts": {"normalized": 0, "pending_normalize": 0},
        "claims": {"accepted": 0, "needs_review": 0, "rejected": 0, "proposed": 0},
        "concepts": {"seed": 0, "proposed": 0, "canonical": 0, "deprecated": 0},
        "analyze_scope": {"pending_analyze": 0, "analyzed": 0},
        "oldest_pending": None,
        "recent_errors_by_class": {},
    }


def cmd_preflight(args):
    runner = _build_runner(args)
    if args.dry_run:
        # Zero-write preflight (P1-2): probe the tool version but never create
        # directories or the DB.
        _apply_data_root_override(args)
        try:
            version = houchen_acquisition.preflight_ytdlp(
                binary=args.ytdlp, runner=runner)
        except Exception as e:
            print(f"preflight failed: {e}", file=sys.stderr)
            return EXIT_RUNTIME
        print(json.dumps({"ok": True, "yt_dlp_version": version,
                          "dry_run": True}, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    conn = _open_write_db(args)
    try:
        result = houchen_runner.preflight(conn, binary=args.ytdlp, runner=runner)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    except Exception as e:
        print(f"preflight failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_catalog(args):
    runner = _build_runner(args)
    if runner is None and not args.live_smoke_allow:
        print("refusing to run catalog against real YouTube without --live-smoke-allow",
              file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run:
        # Zero-write catalog (P1-2): enumerate via an in-memory connection so
        # no directory or SQLite file is ever created.
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            summary = houchen_runner.run_catalog(
                conn, binary=args.ytdlp, runner=runner, dry_run=True,
                tabs=houchen_runner.CATALOG_TABS, limit=args.limit)
        finally:
            conn.close()
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    conn = _open_write_db(args)
    try:
        summary = houchen_runner.run_catalog(
            conn, binary=args.ytdlp, runner=runner, dry_run=False,
            tabs=houchen_runner.CATALOG_TABS, limit=args.limit)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        if summary["status"] == "partial":
            return EXIT_PARTIAL
        if summary["status"] == "failed":
            return EXIT_RUNTIME
        return EXIT_OK
    except Exception as e:
        print(f"catalog failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_fetch_captions(args):
    runner = _build_runner(args)
    if runner is None and not args.live_smoke_allow and not args.dry_run:
        print("refusing to run fetch-captions against real YouTube without --live-smoke-allow",
              file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run:
        # dry-run must not touch disk; perform a plan-only pass.
        return _cmd_fetch_dry_run(args)
    conn = _open_write_db(args)
    try:
        video_ids = [args.video_id] if args.video_id else None
        summary = houchen_runner.run_fetch_captions(
            conn, video_ids=video_ids, pending_only=args.pending,
            include_terminal=args.include_terminal, limit=args.limit,
            binary=args.ytdlp, runner=runner, dry_run=False)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        if summary["status"] == "partial":
            return EXIT_PARTIAL
        if summary["status"] == "failed":
            return EXIT_RUNTIME
        return EXIT_OK
    except Exception as e:
        print(f"fetch-captions failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def _cmd_fetch_dry_run(args):
    """dry-run: open read-only, compute scope, print plan, no writes."""
    _apply_data_root_override(args)
    conn = _open_readonly_db(args)
    scope = []
    if conn is not None:
        video_ids = [args.video_id] if args.video_id else None
        scope = houchen_runner._select_scope(
            conn, video_ids=video_ids, pending_only=args.pending,
            include_terminal=args.include_terminal)
        if args.limit is not None:
            scope = list(scope)[:args.limit]
        conn.close()
    plan = {"scope_count": len(scope), "scope": scope[:20], "dry_run": True}
    print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
    return EXIT_OK


def cmd_status(args):
    conn = _open_readonly_db(args)
    try:
        if conn is None:
            out = _empty_status()
        else:
            out = houchen_status.status(conn)
        print(houchen_status.to_json(out))
        return EXIT_OK
    finally:
        if conn is not None:
            conn.close()


def cmd_coverage(args):
    conn = _open_readonly_db(args)
    try:
        if conn is None:
            out = {"schema_version": 0, "output_version": houchen_status.OUTPUT_VERSION,
                   "by_collection": {}, "by_availability": {},
                   "by_content_kind": {}, "caption_outcomes": _empty_status()["captions"],
                   "transcript_state": _empty_status()["transcripts"],
                   "claim_outcomes": _empty_status()["claims"],
                   "concept_state": _empty_status()["concepts"],
                   "analyze_scope": _empty_status()["analyze_scope"],
                   "catalog_partial": []}
        elif args.markdown:
            print(houchen_status.coverage_markdown(conn))
            return EXIT_OK
        else:
            out = houchen_status.coverage(conn)
        print(houchen_status.to_json(out))
        return EXIT_OK
    finally:
        if conn is not None:
            conn.close()


def cmd_normalize(args):
    """PR-2: deterministic transcript normalizer layer.

    Pure-derived step (no network, no yt-dlp): reads frozen raw_caption files,
    parses + normalizes them into transcript_version + transcript_segment
    rows, writes the content-addressed derived JSON. Re-runs are idempotent
    via the UNIQUE(video_id, raw_caption_sha256, normalizer_*) constraint.
    """
    if args.dry_run:
        # Zero-write dry-run (P1-2): open read-only, compute scope, print plan.
        return _cmd_normalize_dry_run(args)
    conn = _open_write_db(args)
    try:
        video_ids = [args.video_id] if args.video_id else None
        summary = houchen_runner.run_normalize(
            conn, video_ids=video_ids, pending_only=args.pending,
            limit=args.limit, dry_run=False)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        if summary["status"] == "failed":
            return EXIT_RUNTIME
        if summary["status"] == "partial":
            return EXIT_PARTIAL
        return EXIT_OK
    except Exception as e:
        print(f"normalize failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def _cmd_normalize_dry_run(args):
    """dry-run: open read-only, compute normalize scope, print plan, no writes."""
    _apply_data_root_override(args)
    conn = _open_readonly_db(args)
    scope = []
    if conn is not None:
        try:
            video_ids = [args.video_id] if args.video_id else None
            scope = houchen_runner._select_normalize_scope(
                conn, video_ids=video_ids, pending_only=args.pending)
        finally:
            conn.close()
        if args.limit is not None:
            scope = list(scope)[:args.limit]
    plan = {
        "scope_count": len(scope),
        "scope": scope[:20],
        "normalizer": {
            "name": houchen_runner.DEFAULT_NORMALIZER_NAME,
            "version": houchen_runner.DEFAULT_NORMALIZER_VERSION,
        },
        "dry_run": True,
    }
    print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
    return EXIT_OK


def cmd_analyze(args):
    """PR-3: build analysis INPUT bundles, invoke provider (default fake), and
    persist the per-run derived JSON. Idempotent via the UNIQUE-style
    `corpus_attempt(stage='analyze')` + content-addressed derived JSON."""
    video_ids = [args.video_id] if args.video_id else None
    if args.dry_run:
        _apply_data_root_override(args)
        conn = _open_readonly_db(args)
        scope = []
        if conn is not None:
            try:
                scope = houchen_runner._select_analyze_scope(
                    conn, video_ids=video_ids, pending_only=args.pending)
            finally:
                conn.close()
            if args.limit is not None:
                scope = list(scope)[:args.limit]
        plan = {
            "scope_count": len(scope),
            "scope": scope[:20],
            "provider": args.provider,
            "prompt_version": houchen_runner.DEFAULT_PROMPT_VERSION,
            "schema_version": houchen_runner.DEFAULT_SCHEMA_VERSION,
            "dry_run": True,
        }
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    conn = _open_write_db(args)
    try:
        summary = houchen_runner.run_analyze(
            conn, video_ids=video_ids, pending_only=args.pending,
            limit=args.limit, dry_run=False,
            provider=args.provider, model=args.model,
        )
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        if summary.get("status") == "failed":
            return EXIT_RUNTIME
        if summary.get("status") == "partial":
            return EXIT_PARTIAL
        return EXIT_OK
    except Exception as e:
        print(f"analyze failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_validate(args):
    """PR-3: read each analyzed run's artifact, run the hard validator, and
    write claim/concept/etc. rows. Per-run idempotent on analysis_run_id."""
    if args.dry_run:
        # dry-run: open read-only, count videos with a successful analyze.
        _apply_data_root_override(args)
        conn = _open_readonly_db(args)
        scope_count = 0
        if conn is not None:
            try:
                rows = conn.execute(
                    "SELECT COUNT(DISTINCT ca.video_id) FROM corpus_attempt ca"
                    " JOIN corpus_run cr ON cr.run_id = ca.run_id"
                    " WHERE ca.stage='analyze' AND ca.outcome='success'"
                    "   AND cr.status='success'").fetchone()
                scope_count = rows[0] or 0
            finally:
                conn.close()
        plan = {"scope_count": scope_count, "dry_run": True}
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    conn = _open_write_db(args)
    try:
        video_ids = [args.video_id] if args.video_id else None
        summary = houchen_runner.run_validate(
            conn, video_ids=video_ids, limit=args.limit, dry_run=False)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        if summary.get("status") == "failed":
            return EXIT_RUNTIME
        if summary.get("status") == "partial":
            return EXIT_PARTIAL
        return EXIT_OK
    except Exception as e:
        print(f"validate failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_concept_seed(args):
    """PR-3: idempotently insert the 7-domain skeleton (audit F-1)."""
    if args.dry_run:
        _apply_data_root_override(args)
        conn = _open_readonly_db(args)
        existing = 0
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM domain").fetchone()
                existing = row[0] or 0
            finally:
                conn.close()
        plan = {
            "dry_run": True,
            "existing_domain_rows": existing,
            "skeleton_size": len(houchen_concept.DEFAULT_DOMAIN_SKELETON),
        }
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    conn = _open_write_db(args)
    try:
        summary = houchen_runner.run_concept_seed(conn, dry_run=False)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    except Exception as e:
        print(f"concept-seed failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_search(args):
    """PR-4 Phase 0: read-only FTS5 search (brief §10).

    Always opens the DB read-only (P1-2 / P2-2). Persists a `corpus_run`
    row in the read-only connection is not possible, so the run row is
    written via a separate write connection only when not in dry-run.
    """
    if args.dry_run:
        _apply_data_root_override(args)
        # Dry-run = a NO-OP plan. Print a JSON object that documents the
        # query and the installed FTS5 status, and exit 0. Never touches
        # the corpus_run / corpus_attempt tables.
        plan = {
            "dry_run": True,
            "kind": args.kind,
            "query": args.query,
            "limit": args.limit,
            "note": "FTS5 MATCH is read-only; dry-run only documents the query",
        }
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    _apply_data_root_override(args)
    try:
        conn = houchen_store.connect()
    except houchen_paths.DataRootError as e:
        print(f"data-root error: {e}", file=sys.stderr)
        return EXIT_CONFIG
    try:
        summary = houchen_runner.run_search(
            conn, kind=args.kind, query=args.query, limit=args.limit)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    except RuntimeError as e:
        # Most likely: FTS5 substrate not installed (schema_version < 4).
        print(f"search failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    except Exception as e:
        print(f"search failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def _load_render_page_obj(conn, args):
    """Return a page dataclass for render from --from-json or --from-db."""
    import dataclasses
    from houchen_render import (
        ClaimSummary, ConceptPage, ConceptSource, CoveragePage,
        ForecastPage, ReviewQueuePage, VideoPage,
    )
    kind = args.kind
    if args.from_db:
        if kind == "video":
            return houchen_runner.build_video_page_from_db(conn, args.page_key)
        if kind == "concept":
            return houchen_runner.build_concept_page_from_db(conn, args.page_key)
        raise ValueError(
            "--from-db is only supported for --kind video|concept")

    if not args.from_json:
        raise ValueError("render requires --from-json or --from-db")

    with open(args.from_json, encoding="utf-8") as fh:
        data = json.load(fh)
    cls = {
        "video": VideoPage, "concept": ConceptPage,
        "forecast": ForecastPage, "review_queue": ReviewQueuePage,
        "coverage": CoveragePage,
    }.get(kind)
    if cls is None:
        raise ValueError(f"unsupported page kind for render-from-json: {kind!r}")
    nested = {
        "claims": ClaimSummary,
        "canonical_definition_sources": ConceptSource,
        "speaker_use_sources": ConceptSource,
        "system_evaluations": ClaimSummary,
    }
    for k, dccls in nested.items():
        if k in data and isinstance(data[k], list):
            data[k] = [dccls(**item) for item in data[k]]
    return cls(**data)


def cmd_render(args):
    """PR-4 Phase 1: render one page to Markdown (write-side).

    Dry-run is the default; `--apply` flips it. Per-claim pages are OFF
    by default in v1 (S-2 audit fix); pass `--include-claim-pages` to
    opt in. Page data is read from the JSON file at `--from-json` (a
    flat dict matching the renderer's dataclass).

    In `--dry-run` mode the CLI does NOT open the corpus database and
    does NOT touch the filesystem (matches `search --dry-run`).
    """
    _apply_data_root_override(args)

    # Pre-flight: reject --kind=claim without opt-in (S-2 audit fix).
    if args.kind == "claim" and not args.include_claim_pages:
        print("claim pages are OFF by default in v1 (S-2 audit fix);"
              " pass --include-claim-pages to opt in",
              file=sys.stderr)
        return EXIT_USAGE

    if args.dry_run:
        # Pure plan: print the would-be path and exit. No FS writes.
        if args.from_db:
            try:
                conn = houchen_store.connect()
            except houchen_paths.DataRootError as e:
                print(f"data-root error: {e}", file=sys.stderr)
                return EXIT_CONFIG
            try:
                page_obj = _load_render_page_obj(conn, args)
            except ValueError as e:
                print(f"render rejected: {e}", file=sys.stderr)
                return EXIT_USAGE
            finally:
                conn.close()
        else:
            page_obj = _load_render_page_obj(None, args)
        markdown = houchen_render.render_page(args.kind, page_obj)
        plan = {
            "dry_run": True,
            "kind": args.kind, "page_key": args.page_key,
            "render_sha256": houchen_render.render_sha256(markdown),
            "note": "render --dry-run: no file written, no row recorded",
        }
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
        return EXIT_OK

    try:
        conn = houchen_store.connect()
    except houchen_paths.DataRootError as e:
        print(f"data-root error: {e}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        page_obj = _load_render_page_obj(conn, args)
        summary = houchen_runner.run_render(
            conn, kind=args.kind, page_key=args.page_key, page_obj=page_obj,
            include_claim_pages=args.include_claim_pages,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        return EXIT_OK
    except ValueError as e:
        print(f"render rejected: {e}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as e:
        print(f"render failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_publish(args):
    """PR-4 Phase 1: PUT → GET → SHA via VaultWriter (write-side).

    Dry-run is the default. Real PUT requires BOTH `--apply` AND
    `--operator-authorized`; missing either exits 2 with a remediation
    message. A `DryRunVaultWriter` records every call when
    `--dry-run` is set; the test surface swaps in `FakeVaultWriter`.

    In `--dry-run` mode the CLI does NOT open the corpus database and
    does NOT touch the filesystem (matches `search --dry-run`).
    """
    _apply_data_root_override(args)

    if args.apply and not args.operator_authorized:
        print("--apply requires --operator-authorized (audit gate)",
              file=sys.stderr)
        return EXIT_USAGE

    if args.dry_run:
        plan = {
            "dry_run": True,
            "apply": args.apply,
            "operator_authorized": args.operator_authorized,
            "vault_prefix": args.vault_prefix or
                houchen_publish_paths.DEFAULT_VAULT_PREFIX,
            "note": "publish --dry-run: no PUT/GET attempted, no row recorded",
        }
        print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
        return EXIT_OK

    try:
        conn = houchen_store.connect()
    except houchen_paths.DataRootError as e:
        print(f"data-root error: {e}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        vault_prefix = args.vault_prefix or \
            houchen_publish_paths.DEFAULT_VAULT_PREFIX

        if args.apply and args.operator_authorized:
            try:
                cfg = houchen_publish_paths.load_publish_config()
                if not args.vault_prefix and cfg.get("HOUCHEN_PUBLISH_VAULT_PREFIX"):
                    vault_prefix = cfg["HOUCHEN_PUBLISH_VAULT_PREFIX"]
                vault_writer = houchen_publisher.obsidian_writer_from_env()
            except FileNotFoundError as e:
                print(str(e), file=sys.stderr)
                return EXIT_USAGE
            except ValueError as e:
                print(f"publish env invalid: {e}", file=sys.stderr)
                return EXIT_USAGE
        else:
            vault_writer = houchen_publisher.DryRunVaultWriter()

        summary = houchen_runner.run_publish(
            conn,
            page_ids=args.page_id or None,
            kind=args.kind or None,
            vault_writer=vault_writer,
            vault_prefix=vault_prefix,
            dry_run=False,
            apply=args.apply,
            operator_authorized=args.operator_authorized,
            actor=args.actor,
        )
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        if summary.get("status") == "failed":
            return EXIT_RUNTIME
        if summary.get("status") == "partial":
            return EXIT_PARTIAL
        return EXIT_OK
    except RuntimeError as e:
        print(f"publish refused: {e}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as e:
        print(f"publish failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def cmd_macro_bridge(args):
    """PR-5: macro bridge — link HouChen claims to macro observations."""
    from pathlib import Path

    db_path = houchen_paths.sqlite_path()
    store_path = macro_bridge._MACRO_STORE_PATH

    # --verify-sha: quick check, no DB work
    if args.verify_sha:
        expected = args.verify_sha
        ok = macro_bridge.verify_store_sha(expected, store_path)
        result = {"sha_match": ok, "expected": expected,
                  "store_path": str(store_path)}
        print(json.dumps(result, indent=2))
        return EXIT_OK if ok else EXIT_RUNTIME

    # --scan: scan accepted claims → produce candidates
    if args.scan:
        houchen_conn = sqlite3.connect(str(db_path))
        houchen_conn.row_factory = sqlite3.Row
        macro_conn = macro_bridge.open_macro_store_readonly(store_path)
        try:
            candidates = macro_bridge.scan_all(
                houchen_conn, macro_conn,
                keywords_path=Path(macro_bridge._KEYWORDS_PATH),
            )
            # Count by relation
            relations = {}
            for c in candidates:
                relations[c.relation] = relations.get(c.relation, 0) + 1
            result = {
                "status": "success",
                "claims_scanned": len(set(c.claim_id for c in candidates))
                    if candidates else _count_accepted(houchen_conn),
                "candidates_produced": len(candidates),
                "relations": relations,
            }
            print(json.dumps(result, indent=2))
            return EXIT_OK
        except Exception as e:
            print(f"macro-bridge scan failed: {e}", file=sys.stderr)
            return EXIT_RUNTIME
        finally:
            macro_conn.close()
            houchen_conn.close()

    # --review-queue: export unreviewed candidates
    if args.review_queue is not None:
        houchen_conn = sqlite3.connect(str(db_path))
        houchen_conn.row_factory = sqlite3.Row
        try:
            queue = macro_bridge.review_queue(
                houchen_conn,
                limit=args.review_queue,
                reviewed=False,
            )
            if args.review_queue_md:
                # Markdown format
                print("# Macro Bridge Review Queue\n")
                for c in queue:
                    print(f"- `{c['candidate_id']}` | {c['claim_id'][:12]}… | "
                          f"{c['macro_source']}/{c['macro_series']} | "
                          f"{c['relation']} | reviewed={c['reviewed']}")
                    print(f"  - claim: {c['claim_snippet']}")
            else:
                print(json.dumps(queue, indent=2, ensure_ascii=False))
            return EXIT_OK
        finally:
            houchen_conn.close()

    # --mark-reviewed: mark candidate(s) as reviewed
    if args.mark_reviewed:
        houchen_conn = sqlite3.connect(str(db_path))
        try:
            ids = args.mark_reviewed
            relation = args.relation
            results = []
            for cid in ids:
                rowcount = macro_bridge.mark_reviewed(
                    houchen_conn, cid, relation=relation
                )
                results.append({"candidate_id": cid, "updated": rowcount})
            print(json.dumps(results, indent=2))
            return EXIT_OK
        except Exception as e:
            print(f"mark-reviewed failed: {e}", file=sys.stderr)
            return EXIT_RUNTIME
        finally:
            houchen_conn.close()

    # --import-reviewed: import reviewed candidates to evaluation
    if args.import_reviewed:
        houchen_conn = sqlite3.connect(str(db_path))
        try:
            ids = macro_bridge.import_reviewed(
                houchen_conn, limit=args.import_reviewed
            )
            print(json.dumps({"imported": len(ids), "evaluation_ids": ids},
                            indent=2))
            return EXIT_OK
        except Exception as e:
            print(f"import-reviewed failed: {e}", file=sys.stderr)
            return EXIT_RUNTIME
        finally:
            houchen_conn.close()

    # --export: dump candidates to JSONL
    if args.export:
        output = Path(args.export)
        houchen_conn = sqlite3.connect(str(db_path))
        houchen_conn.row_factory = sqlite3.Row
        try:
            count = macro_bridge.export_jsonl(houchen_conn, output)
            result = {"status": "success", "exported": count,
                      "path": str(output)}
            print(json.dumps(result, indent=2))
            return EXIT_OK
        except Exception as e:
            print(f"macro-bridge export failed: {e}", file=sys.stderr)
            return EXIT_RUNTIME
        finally:
            houchen_conn.close()

    print("macro-bridge: specify --scan, --export, or --verify-sha",
          file=sys.stderr)
    return EXIT_USAGE


def _count_accepted(conn: sqlite3.Connection) -> int:
    """Count accepted claims in houchen DB."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM claim WHERE status='accepted'"
    ).fetchone()
    return row["cnt"] if row else 0


def cmd_import_transcript(args):
    """PR-5 P2b: import human-written transcript (WPS etc.)."""
    from pathlib import Path

    if not args.video_id:
        print("import-transcript: --video-id is required", file=sys.stderr)
        return EXIT_USAGE
    if not args.from_file:
        print("import-transcript: --from-file is required", file=sys.stderr)
        return EXIT_USAGE

    file_path = Path(args.from_file)
    if not file_path.exists():
        print(f"import-transcript: file not found: {file_path}",
              file=sys.stderr)
        return EXIT_RUNTIME

    db_path = houchen_paths.sqlite_path()
    conn = houchen_store.connect(db_path)
    try:
        result = houchen_import_transcript.import_transcript(
            conn,
            video_id=args.video_id,
            file_path=file_path,
            language=args.language or "zh",
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") in ("success", "already_imported"):
            return EXIT_OK
        return EXIT_RUNTIME
    except Exception as e:
        print(f"import-transcript failed: {e}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        conn.close()


def build_parser():
    p = argparse.ArgumentParser(
        prog="houchen_pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            PR-1 + PR-2 Hou Chen research corpus CLI.

            Write commands require --live-smoke-allow for the real backend, or a
            --runner pointing at the canonical repo fixture. Read commands are
            truly read-only. Exit codes: 0 ok, 1 runtime, 2 usage/auth-refused,
            3 partial / catalog partial, 4 data-root config error.
        """),
    )
    p.add_argument("--data-root", help="Override data root (default <repo>/data/houchen)")

    # Options that must be accepted both before AND after the subcommand
    # (e.g. `houchen_pipeline catalog --runner ...`). argparse only forwards
    # pre-subcommand options on the main parser, so these are shared via a
    # parent parser to every subparser as well.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ytdlp", default="yt-dlp", help="yt-dlp binary path")
    common.add_argument("--runner",
                        help="Path to canonical fake_ytdlp fixture (tests only)")
    common.add_argument("--live-smoke-allow", action="store_true",
                        help="Explicit opt-in for real network calls")
    common.add_argument("--dry-run", action="store_true",
                        help="Plan only; never creates/modifies dirs, DB or files")

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight", parents=[common])

    pc = sub.add_parser("catalog", parents=[common])
    pc.add_argument("--limit", type=_nonneg_int, default=None)

    pf = sub.add_parser("fetch-captions", parents=[common])
    pf.add_argument("--video-id")
    pf.add_argument("--pending", action="store_true", default=True)
    pf.add_argument("--no-pending", dest="pending", action="store_false")
    pf.add_argument("--include-terminal", action="store_true",
                    help="Also re-run terminal (missing/permanent) videos")
    pf.add_argument("--limit", type=_nonneg_int, default=None)

    pn = sub.add_parser("normalize", parents=[common],
                        help="PR-2: deterministic transcript normalizer (no network)")
    pn.add_argument("--video-id")
    pn.add_argument("--pending", action="store_true", default=True)
    pn.add_argument("--no-pending", dest="pending", action="store_false")
    pn.add_argument("--limit", type=_nonneg_int, default=None)

    pa = sub.add_parser("analyze", parents=[common],
                        help="PR-3: build INPUT bundles + invoke provider (default fake)")
    pa.add_argument("--video-id")
    pa.add_argument("--pending", action="store_true", default=True)
    pa.add_argument("--no-pending", dest="pending", action="store_false")
    pa.add_argument("--limit", type=_nonneg_int, default=None)
    pa.add_argument("--provider", default="fake",
                    choices=["fake", "anthropic", "deepseek", "minimax"],
                    help="Model provider (default 'fake' = offline)")
    pa.add_argument("--model", default="",
                    help="Model identifier (recorded in artifact; not used by fake)")

    pv = sub.add_parser("validate", parents=[common],
                        help="PR-3: hard-validate each analyze artifact and write claim rows")
    pv.add_argument("--video-id")
    pv.add_argument("--limit", type=_nonneg_int, default=None)

    sub.add_parser("concept-seed", parents=[common],
                   help="PR-3: idempotent domain skeleton seed (audit F-1)")

    ps = sub.add_parser("search", parents=[common],
                        help="PR-4 Phase 0: read-only FTS5 MATCH search")
    ps.add_argument("--kind", required=True,
                    choices=["transcript", "claim", "concept", "concept_alias", "all"],
                    help="Which FTS5 table to query")
    ps.add_argument("--query", required=True, help="FTS5 MATCH expression")
    ps.add_argument("--limit", type=_nonneg_int, default=20)

    pr = sub.add_parser("render", parents=[common],
                        help="PR-4 Phase 1: render a page to Markdown")
    pr.add_argument("--kind", required=True,
                    choices=["video", "concept", "forecast", "review_queue",
                             "coverage", "claim"],
                    help="Page kind to render (claim OFF by default)")
    pr.add_argument("--page-key", required=True,
                    help="Stable identifier for this page")
    pr.add_argument("--from-json",
                    help="Path to a JSON file with the page dataclass data")
    pr.add_argument("--from-db", action="store_true",
                    help="Load video/concept page from corpus DB")
    pr.add_argument("--include-claim-pages", action="store_true",
                    help="Opt in to claim pages (S-2 audit fix)")

    pp = sub.add_parser("publish", parents=[common],
                        help="PR-4 Phase 1: PUT → GET → SHA via VaultWriter")
    pp.add_argument("--kind",
                    choices=["video", "concept", "forecast", "review_queue",
                             "coverage", "claim"],
                    help="Limit to one page_kind (default = all)")
    pp.add_argument("--page-id", action="append",
                    help="Specific rendered_page_id (repeatable)")
    pp.add_argument("--vault-prefix",
                    help=f"Obsidian vault prefix (default "
                         f"{houchen_publish_paths.DEFAULT_VAULT_PREFIX!r})")
    pp.add_argument("--apply", action="store_true",
                    help="Actually publish (default is dry-run)")
    pp.add_argument("--operator-authorized", action="store_true",
                    help="Required with --apply; records operator in summary")
    pp.add_argument("--actor", default="cli",
                    help="Operator actor string for the audit trail")

    sub.add_parser("status", parents=[common])
    pcov = sub.add_parser("coverage", parents=[common])
    pcov.add_argument("--markdown", action="store_true")

    # PR-5: macro bridge
    pmb = sub.add_parser("macro-bridge", parents=[common],
                         help="PR-5: link HouChen claims to macro observations")
    pmb.add_argument("--scan", action="store_true",
                     help="Scan accepted claims and produce link candidates")
    pmb.add_argument("--export",
                     help="Export candidates to JSONL at the given path")
    pmb.add_argument("--verify-sha",
                     help="Verify store.db SHA matches (hex string)")
    pmb.add_argument("--review-queue", type=int, nargs="?", const=0, default=None,
                     metavar="LIMIT",
                     help="Export unreviewed candidates (optional limit)")
    pmb.add_argument("--review-queue-md", action="store_true",
                     help="Output review queue as Markdown")
    pmb.add_argument("--mark-reviewed", action="append",
                     metavar="CANDIDATE_ID",
                     help="Mark candidate as reviewed (repeatable)")
    pmb.add_argument("--relation",
                     choices=["supports", "challenges", "contextualizes", "unresolved"],
                     help="Override relation when marking reviewed")
    pmb.add_argument("--import-reviewed", type=int, nargs="?", const=0,
                     default=None, metavar="LIMIT",
                     help="Import reviewed candidates to evaluation")

    # PR-5 P2b: import transcript
    pit = sub.add_parser("import-transcript", parents=[common],
                         help="PR-5 P2b: import human-written transcript (WPS)")
    pit.add_argument("--video-id", required=True,
                     help="YouTube video ID")
    pit.add_argument("--from-file", required=True,
                     help="Path to .txt/.vtt/.srt file")
    pit.add_argument("--language", default="zh",
                     help="Language code (default: zh)")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "preflight":
        return cmd_preflight(args)
    if args.cmd == "catalog":
        return cmd_catalog(args)
    if args.cmd == "fetch-captions":
        return cmd_fetch_captions(args)
    if args.cmd == "normalize":
        return cmd_normalize(args)
    if args.cmd == "analyze":
        return cmd_analyze(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "concept-seed":
        return cmd_concept_seed(args)
    if args.cmd == "search":
        return cmd_search(args)
    if args.cmd == "render":
        return cmd_render(args)
    if args.cmd == "publish":
        return cmd_publish(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "coverage":
        return cmd_coverage(args)
    if args.cmd == "macro-bridge":
        return cmd_macro_bridge(args)
    if args.cmd == "import-transcript":
        return cmd_import_transcript(args)
    print(f"unknown command: {args.cmd}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
