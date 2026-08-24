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
import houchen_runner  # noqa: E402
import houchen_status  # noqa: E402
import houchen_store  # noqa: E402

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

    sub.add_parser("status", parents=[common])
    pcov = sub.add_parser("coverage", parents=[common])
    pcov.add_argument("--markdown", action="store_true")

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
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "coverage":
        return cmd_coverage(args)
    print(f"unknown command: {args.cmd}", file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
