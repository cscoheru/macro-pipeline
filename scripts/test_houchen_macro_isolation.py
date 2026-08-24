"""Macro-isolation + P0-2/P0-3 tests for the Hou Chen corpus (PR-1, hardened).

Covers (per Codex §8):
    - symlink escape (root / captions / DB leaf) rejected before any write
    - protected macro roots rejected as data root
    - dry-run produces zero filesystem change (tree / SHA / mtime)
    - full PR-1 run leaves the macro tree hash unchanged
    - redaction: no secret survives into DB / CLI / exception text
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import houchen_acquisition as acq
import houchen_migrations
import houchen_paths
import houchen_runner
import houchen_schema
import houchen_status
import houchen_store
import paths as macro_paths
from houchen_fixtures.scenario import (  # noqa: E402
    make_runner, write_scenario, playlist_call, info_call, download_call,
    version_call, VTT_BODY,
)

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "houchen_pipeline.py")


def _hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _tree_state(root):
    """Snapshot of every entry (dirs AND files) under root: relpath → marker.

    Directories are included (P2-5) so a dry-run that creates an empty dir
    cannot pass unnoticed."""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            full = os.path.join(dirpath, d)
            out[os.path.relpath(full, root) + "/"] = "dir"
        for f in filenames:
            full = os.path.join(dirpath, f)
            out[os.path.relpath(full, root)] = (
                os.path.getsize(full), os.stat(full).st_mtime_ns)
    return out


def _hash_tree(root):
    h = hashlib.sha256()
    for dirpath, _, files in sorted(os.walk(root)):
        for f in sorted(files):
            full = os.path.join(dirpath, f)
            h.update(os.path.relpath(full, root).encode())
            h.update(_hash_file(full).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# P0-2: symlink escape + protected roots
# ---------------------------------------------------------------------------

def test_data_root_rejects_symlink_component(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = str(link)
    try:
        with pytest.raises(houchen_paths.DataRootError, match="symlink"):
            houchen_paths.resolve_data_root()
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


def test_data_root_rejects_macro_store_path():
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = os.path.dirname(macro_paths.STORE_DB)
    try:
        with pytest.raises(houchen_paths.DataRootError, match="protected"):
            houchen_paths.resolve_data_root()
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


def test_db_symlink_rejected(tmp_path):
    real_db = tmp_path / "real.sqlite3"
    real_db.write_bytes(b"")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(real_db)
    with pytest.raises(houchen_paths.DataRootError, match="symlink"):
        houchen_store.connect(db_path=str(link))


def test_default_connect_rejects_db_symlink(tmp_path):
    """P0-1: the DEFAULT production DB leaf must be symlink-checked — an
    external SQLite is never created or modified."""
    root = tmp_path / "root"
    root.mkdir()
    external = tmp_path / "external.sqlite3"
    external.write_bytes(b"")
    (root / "houchen.sqlite3").symlink_to(external)
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = str(root)
    try:
        with pytest.raises(houchen_paths.DataRootError, match="symlink"):
            houchen_store.connect()  # no db_path → default production path
        # External file untouched (still 0 bytes, not a SQLite DB).
        assert external.read_bytes() == b""
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


def test_data_root_rejects_symlink_middle_component(tmp_path):
    """P0-2: a symlinked MIDDLE component of the configured root is rejected
    (writes must not silently resolve into an external tree)."""
    real = tmp_path / "real"
    (real / "deep").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = str(link / "deep")
    try:
        with pytest.raises(houchen_paths.DataRootError, match="symlink"):
            houchen_paths.resolve_data_root()
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


def test_ensure_dirs_rejects_symlink_raw(tmp_path):
    """P0-2: a symlinked `raw` dir must not let ensure_dirs() create
    directories outside the data root."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "raw").symlink_to(outside, target_is_directory=True)
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = str(root)
    try:
        with pytest.raises(houchen_paths.DataRootError, match="symlink"):
            houchen_store.ensure_dirs()
        # Nothing was created outside the data root.
        assert os.listdir(outside) == []
        assert os.listdir(root) == ["raw"]
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


def test_ensure_dirs_rejects_symlink_captions(tmp_path):
    """P0-2: a symlinked `raw/captions` leaf is rejected the same way."""
    root = tmp_path / "root"
    (root / "raw").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "raw" / "captions").symlink_to(outside, target_is_directory=True)
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = str(root)
    try:
        with pytest.raises(houchen_paths.DataRootError, match="symlink"):
            houchen_store.ensure_dirs()
        assert os.listdir(outside) == []
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


# ---------------------------------------------------------------------------
# P0-3: redaction persistence
# ---------------------------------------------------------------------------

def test_no_secret_persists_in_db(tmp_path):
    """A signed URL + token in stderr must not reach corpus_attempt.detail."""
    old = os.environ.get("HOUCHEN_DATA_ROOT")
    os.environ["HOUCHEN_DATA_ROOT"] = str(tmp_path)
    try:
        c = sqlite3.connect(":memory:")
        c.execute("PRAGMA foreign_keys=ON")
        c.row_factory = sqlite3.Row
        houchen_migrations.ensure_schema(c)
        c.execute(
            "INSERT INTO video(video_id, discovered_at, last_seen_at,"
            " metadata_sha256, availability, content_kind) VALUES (?,?,?,?,?,?)",
            ("aaaaaaaaaaa", "t", "t", "c" * 64, "public", "video"))
        c.execute(
            "INSERT INTO corpus_run(run_id, kind, started_at, status,"
            " config_sha256, tool_versions_json) VALUES (?,?,?,?,?,?)",
            ("hcrun_r1", "caption_fetch", "t", "running", "z" * 64, "{}"))
        c.commit()
        scen = os.path.join(str(tmp_path), "scen")
        write_scenario(scen, [{
            "argv_prefix": ["yt-dlp", "--skip-download", "--dump-json"],
            "exit_code": 1,
            "stderr": "https://youtube.com/api?signature=TOPSECRET123 "
                      "Authorization: Bearer abcdefgh",
        }])
        acq.freeze_one(c, "aaaaaaaaaaa", run_id="hcrun_r1",
                       runner=make_runner(scen), yt_version="y")
        for stage in ("freeze", "subtitle_inventory"):
            rows = c.execute(
                "SELECT detail FROM corpus_attempt WHERE video_id='aaaaaaaaaaa'"
                " AND stage=?", (stage,)).fetchall()
            for r in rows:
                assert "TOPSECRET123" not in (r["detail"] or "")
                assert "abcdefgh" not in (r["detail"] or "")
                assert "signature=" not in (r["detail"] or "")
        c.close()
    finally:
        if old is None:
            os.environ.pop("HOUCHEN_DATA_ROOT", None)
        else:
            os.environ["HOUCHEN_DATA_ROOT"] = old


# ---------------------------------------------------------------------------
# P1-2: dry-run zero change (fetch / catalog / preflight, on a fresh root)
# ---------------------------------------------------------------------------

def test_dry_run_zero_filesystem_change(tmp_path):
    """fetch-captions / catalog / preflight --dry-run must not create dirs, DB
    or files (P1-2). The tree snapshot includes directories, so even an empty
    created dir would be caught."""
    data_root = tmp_path / "root"
    scen = os.path.join(str(tmp_path), "scen")
    write_scenario(scen, [
        version_call(),          # catalog dry-run version probe
        version_call(),          # preflight dry-run version probe
        playlist_call([]), playlist_call([]), playlist_call([]),
    ])
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "houchen_fixtures", "fake_ytdlp.py")
    before = _tree_state(str(data_root))
    assert before == {}  # fresh root does not exist yet

    env = dict(os.environ)
    env["HOUCHEN_DATA_ROOT"] = str(data_root)
    env["FAKE_YTDLP_SCENARIO"] = scen
    cmds = [
        [SCRIPT, "--data-root", str(data_root),
         "fetch-captions", "--dry-run"],
        [SCRIPT, "--data-root", str(data_root),
         "catalog", "--dry-run", "--runner", runner],
        [SCRIPT, "--data-root", str(data_root),
         "preflight", "--dry-run", "--runner", runner],
    ]
    for cmd in cmds:
        r = subprocess.run([sys.executable] + cmd,
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, (cmd, r.stderr)
        after = _tree_state(str(data_root))
        assert after == before, (cmd, sorted(set(after) ^ set(before)))


def test_dry_run_zero_change_on_existing_root(tmp_path):
    """Dry-run on an ALREADY-INITIALIZED root must not modify anything either."""
    data_root = tmp_path / "root"
    scen = os.path.join(str(tmp_path), "scen")
    write_scenario(scen, [
        version_call(),          # preflight (init)
        version_call(),          # catalog (init)
        playlist_call([{"id": "aaaaaaaaaaa", "title": "v"}]),
        playlist_call([]), playlist_call([]),
        version_call(),          # fetch (init)
        info_call({"subtitles": {"zh-Hans": [{"ext": "vtt"}]}}),
        download_call(),
        version_call(),          # catalog --dry-run
        version_call(),          # preflight --dry-run
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "houchen_fixtures", "fake_ytdlp.py")
    env = dict(os.environ)
    env["HOUCHEN_DATA_ROOT"] = str(data_root)
    env["FAKE_YTDLP_SCENARIO"] = scen

    # Initialize: catalog + freeze one video (real writes, expected).
    for cmd in (["preflight", "--runner", runner],
                ["catalog", "--runner", runner],
                ["fetch-captions", "--runner", runner]):
        r = subprocess.run(
            [sys.executable, SCRIPT, "--data-root", str(data_root)] + cmd,
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, (cmd, r.stderr)

    before = _tree_state(str(data_root))
    for cmd in (["catalog", "--dry-run", "--runner", runner],
                ["preflight", "--dry-run", "--runner", runner],
                ["fetch-captions", "--dry-run"]):
        r = subprocess.run(
            [sys.executable, SCRIPT, "--data-root", str(data_root)] + cmd,
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, (cmd, r.stderr)
        assert _tree_state(str(data_root)) == before


# ---------------------------------------------------------------------------
# P1-6: full PR-1 chain via REAL CLI subprocess + disk research DB leaves the
# macro tree byte-identical.
# ---------------------------------------------------------------------------

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _protected_snapshot():
    """File listing + size + mtime + SHA for every protected macro path, plus
    the default research root (to prove an overridden root leaves it alone)."""
    targets = [
        macro_paths.STORE_DB,
        getattr(macro_paths, "INSIGHT_DIR", os.path.join(_REPO, "data", "insights")),
        getattr(macro_paths, "SNAPS", os.path.join(_REPO, "data", "snapshots")),
        os.path.join(_REPO, "data", "state.json"),
        os.path.join(_REPO, "data", "ledger.sqlite"),
        os.path.join(_REPO, "data", "macro.db"),
        os.path.join(_REPO, "config"),
        os.path.join(_REPO, "logs"),
        os.path.join(_REPO, "data", "houchen"),
    ]
    snap = {}
    for t in targets:
        if os.path.isfile(t):
            snap[t] = ("file", os.path.getsize(t), os.stat(t).st_mtime_ns)
        elif os.path.isdir(t):
            snap[t + "/"] = "dir"
            for dirpath, dirnames, filenames in os.walk(t):
                for name in sorted(dirnames):
                    snap[os.path.join(dirpath, name) + "/"] = "dir"
                for f in sorted(filenames):
                    full = os.path.join(dirpath, f)
                    snap[full] = ("file", os.path.getsize(full),
                                  os.stat(full).st_mtime_ns)
        else:
            snap[t] = "absent"
    return snap


def test_full_pr1_cli_run_leaves_macro_unchanged(tmp_path):
    """P1-6: a real CLI chain (preflight → catalog → fetch → rerun → status →
    coverage) with a DISK research DB and the canonical fake runner leaves
    every protected macro path byte- and mtime-identical."""
    data_root = tmp_path / "research_root"
    scen = os.path.join(str(tmp_path), "scen")
    write_scenario(scen, [
        version_call(),                      # preflight
        version_call(),                      # catalog
        playlist_call([{"id": "aaaaaaaaaaa", "title": "v"}]),
        playlist_call([]),
        playlist_call([]),
        version_call(),                      # fetch
        info_call({"subtitles": {"zh-Hans": [{"ext": "vtt"}]}}),
        download_call(),
        version_call(),                      # rerun (empty scope)
    ], subs={"zh-Hans": ("vtt", VTT_BODY)})
    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "houchen_fixtures", "fake_ytdlp.py")

    before = _protected_snapshot()

    env = dict(os.environ)
    env["HOUCHEN_DATA_ROOT"] = str(data_root)
    env["FAKE_YTDLP_SCENARIO"] = scen
    cmds = [
        ["preflight", "--runner", runner],
        ["catalog", "--runner", runner],
        ["fetch-captions", "--runner", runner],
        ["fetch-captions", "--runner", runner],   # rerun: frozen → no-op
        ["status"],
        ["coverage"],
    ]
    for cmd in cmds:
        r = subprocess.run(
            [sys.executable, SCRIPT, "--data-root", str(data_root)] + cmd,
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, (cmd, r.stderr)

    # The research DB + raw caption exist under the temp root.
    assert (data_root / "houchen.sqlite3").is_file()
    assert any(data_root.joinpath("raw", "captions").rglob("*.vtt"))
    # ... and every protected macro path is unchanged.
    assert _protected_snapshot() == before


# ---------------------------------------------------------------------------
# Import-graph isolation (unchanged)
# ---------------------------------------------------------------------------

def test_research_modules_do_not_import_macro_coupled_modules():
    import importlib
    forbidden = ("store", "insight_provider", "insight_validate",
                 "insight_render", "insight_runner", "insight_publisher",
                 "insight_context", "vault_writer", "ledger", "migrations",
                 "notify", "readings_cache", "detector", "stats",
                 "cn_parsers", "jp_parsers", "de_parsers", "fetcher")
    for mod_name in ("houchen_paths", "houchen_schema", "houchen_migrations",
                     "houchen_store", "houchen_acquisition", "houchen_runner",
                     "houchen_status"):
        mod = importlib.import_module(mod_name)
        src = getattr(mod, "__file__", "")
        if not src:
            continue
        with open(src, encoding="utf-8") as f:
            text = f.read()
        cleaned = "\n".join(l for l in text.splitlines()
                            if not l.lstrip().startswith("#"))
        for f_mod in forbidden:
            assert f"import {f_mod}" not in cleaned
            assert f"from {f_mod}" not in cleaned


def test_research_db_path_independent():
    assert os.path.realpath(houchen_paths.sqlite_path()) != \
        os.path.realpath(macro_paths.STORE_DB)
