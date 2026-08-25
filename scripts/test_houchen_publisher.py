"""PR-4 Phase 1 — Publisher tests (brief §11).

Covers the PUT → GET → SHA protocol via the `VaultWriter` injection
point, plus the publish ledger (`publish_record`) state machine:

  1. Happy path: PUT → GET → SHA matches → `publish_record.status='published'`.
  2. Idempotency: re-publishing an already-published page is a no-op
     (no extra PUT/GET).
  3. SHA mismatch: `get_pipeline` returns bytes whose SHA differs →
     `publish_record.status='failed'`, `error_class='readback_mismatch'`.
  4. PUT failure: `put_pipeline` raises → `error_class='put_failed'`.
  5. GET error: `get_pipeline` raises → `error_class='readback_failed'`.
  6. GET returns None: → `error_class='readback_missing'`.
  7. Already-published row short-circuits BEFORE PUT/GET.
  8. `DryRunVaultWriter` records calls but never raises / never stores.
  9. `export_obsidian_index` emits a JSON registry over rendered_page.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "houchen_fixtures"))

import houchen_migrations  # noqa: E402
import houchen_paths  # noqa: E402
import houchen_publish_paths  # noqa: E402
import houchen_publisher  # noqa: E402
import houchen_render  # noqa: E402
import houchen_runner  # noqa: E402

from fake_vault_writer import FakeVaultWriter  # noqa: E402
from sample_pages import make_video_page  # noqa: E402


def _fresh_db_with_publish() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    houchen_migrations.ensure_schema(c)
    return c


def _seed_rendered_page(tmp_dir, conn, *, kind="video", page_key="vid_aaaaaaaaaaa",
                        page_obj=None) -> str:
    """Render one page via the runner, write the file, and return the
    rendered_page_id. The rendered_page row is recorded.

    The caller owns the env var — we leave HOUCHEN_DATA_ROOT set to
    `tmp_dir` so subsequent calls (publish_with_path, _publish_with_
    explicit_path) can resolve the render file. `tearDown` MUST clear it.
    """
    if page_obj is None:
        page_obj = make_video_page()
    os.environ["HOUCHEN_DATA_ROOT"] = tmp_dir
    houchen_paths.verify_data_root()
    summary = houchen_runner.run_render(
        conn, kind=kind, page_key=page_key, page_obj=page_obj)
    return summary["rendered_page_id"]


def _clear_data_root() -> None:
    os.environ.pop("HOUCHEN_DATA_ROOT", None)


class TestVaultWriterInjections(unittest.TestCase):
    def test_dry_run_writer_records_calls(self):
        w = houchen_publisher.DryRunVaultWriter()
        w.put_pipeline("x/y.md", "hello")
        w.get_pipeline("x/y.md")
        self.assertEqual(len(w.calls), 2)
        self.assertEqual(w.calls[0][0], "put")
        self.assertEqual(w.calls[1][0], "get")

    def test_dry_run_writer_does_not_store(self):
        w = houchen_publisher.DryRunVaultWriter()
        w.put_pipeline("x/y.md", "hello")
        # get_pipeline returns None because we don't store (per the
        # protocol contract: GET returns None when path is unknown).
        self.assertIsNone(w.get_pipeline("x/y.md"))

    def test_fake_writer_happy_path(self):
        w = FakeVaultWriter()
        w.put_pipeline("p", "hello")
        self.assertEqual(w.stored_content("p"), "hello")
        self.assertEqual(w.last_put_sha("p"),
                         houchen_publisher._sha256_text("hello"))
        self.assertEqual(w.get_pipeline("p"), "hello")

    def test_fake_writer_simulate_put_error(self):
        w = FakeVaultWriter()
        w.simulate_put_error()
        with self.assertRaises(RuntimeError):
            w.put_pipeline("p", "x")

    def test_fake_writer_simulate_get_error(self):
        w = FakeVaultWriter()
        w.put_pipeline("p", "x")
        w.simulate_get_error()
        with self.assertRaises(RuntimeError):
            w.get_pipeline("p")

    def test_fake_writer_simulate_get_returns_none(self):
        w = FakeVaultWriter()
        w.put_pipeline("p", "x")
        w.simulate_get_returns_none()
        self.assertIsNone(w.get_pipeline("p"))

    def test_fake_writer_simulate_get_sha_mismatch(self):
        w = FakeVaultWriter()
        w.put_pipeline("p", "hello")
        w.simulate_get_sha_mismatch()
        fetched = w.get_pipeline("p")
        # Returns tampered bytes (different SHA than the put sha).
        self.assertIsNotNone(fetched)
        self.assertNotEqual(
            houchen_publisher._sha256_text(fetched),
            w.last_put_sha("p"))


class TestPublisherHappyPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = _fresh_db_with_publish()
        self.page_id = _seed_rendered_page(self.tmp.name, self.c)

    def tearDown(self):
        self.c.close()
        _clear_data_root()
        self.tmp.cleanup()

    def test_publish_page_succeeds(self):
        w = FakeVaultWriter()
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path="Research/世界苦茶/video/vid_aaaaaaaaaaa.md",
            vault_writer=w, actor="test")
        self.assertTrue(result.published)
        self.assertEqual(len(w.calls), 2)
        # publish_record advanced
        self.assertTrue(houchen_publisher.is_published(
            self.c, self.page_id,
            "Research/世界苦茶/video/vid_aaaaaaaaaaa.md"))

    def test_already_published_is_noop(self):
        w = FakeVaultWriter()
        vpath = "Research/世界苦茶/video/vid_aaaaaaaaaaa.md"
        houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=vpath, vault_writer=w, actor="test")
        n_calls = len(w.calls)
        # Second call is a no-op when render SHA unchanged.
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=vpath, vault_writer=w, actor="test")
        self.assertTrue(result.published)
        self.assertEqual(len(w.calls), n_calls)

    def test_republish_when_render_sha_changes(self):
        import hashlib
        w = FakeVaultWriter()
        vpath = "Research/世界苦茶/video/vid_aaaaaaaaaaa.md"
        houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=vpath, vault_writer=w, actor="test")
        n_calls = len(w.calls)
        row = self.c.execute(
            "SELECT page_kind, page_key, template_version FROM rendered_page"
            " WHERE rendered_page_id=?",
            (self.page_id,)).fetchone()
        local_path = houchen_publish_paths.render_page_path(
            row[2], row[0], row[1])
        new_content = "# re-rendered\n\nupdated body\n"
        new_sha = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        with open(local_path, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        self.c.execute(
            "UPDATE rendered_page SET render_sha256=? WHERE rendered_page_id=?",
            (new_sha, self.page_id))
        self.c.commit()
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=vpath, vault_writer=w, actor="test")
        self.assertTrue(result.published)
        self.assertGreater(len(w.calls), n_calls)


class TestPublisherFailureModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = _fresh_db_with_publish()
        self.page_id = _seed_rendered_page(self.tmp.name, self.c)
        self.vpath = "Research/世界苦茶/video/vid_aaaaaaaaaaa.md"

    def tearDown(self):
        self.c.close()
        _clear_data_root()
        self.tmp.cleanup()

    def test_put_failure_records_failed(self):
        w = FakeVaultWriter()
        w.simulate_put_error()
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=self.vpath, vault_writer=w, actor="test")
        self.assertFalse(result.published)
        self.assertEqual(result.error_class, "put_failed")
        self.assertFalse(houchen_publisher.is_published(
            self.c, self.page_id, self.vpath))
        self.assertEqual(houchen_publisher.count_failed(self.c), 1)

    def test_get_failure_records_failed(self):
        w = FakeVaultWriter()
        w.simulate_get_error()
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=self.vpath, vault_writer=w, actor="test")
        self.assertFalse(result.published)
        self.assertEqual(result.error_class, "readback_failed")

    def test_get_returns_none_records_failed(self):
        w = FakeVaultWriter()
        w.simulate_get_returns_none()
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=self.vpath, vault_writer=w, actor="test")
        self.assertEqual(result.error_class, "readback_missing")

    def test_get_sha_mismatch_records_failed(self):
        w = FakeVaultWriter()
        w.simulate_get_sha_mismatch()
        result = houchen_runner.publish_with_path(
            conn=self.c, page_id=self.page_id,
            vault_path=self.vpath, vault_writer=w, actor="test")
        self.assertEqual(result.error_class, "readback_mismatch")


class TestPublishCounters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = _fresh_db_with_publish()

    def tearDown(self):
        self.c.close()
        _clear_data_root()
        self.tmp.cleanup()

    def test_counts_empty(self):
        self.assertEqual(houchen_publisher.count_published(self.c), 0)
        self.assertEqual(houchen_publisher.count_failed(self.c), 0)

    def test_counts_one_published(self):
        page_id = _seed_rendered_page(self.tmp.name, self.c)
        w = FakeVaultWriter()
        houchen_runner.publish_with_path(
            conn=self.c, page_id=page_id,
            vault_path="Research/v.md", vault_writer=w, actor="t")
        self.assertEqual(houchen_publisher.count_published(self.c), 1)
        self.assertEqual(houchen_publisher.count_failed(self.c), 0)


class TestExportObsidianIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = _fresh_db_with_publish()

    def tearDown(self):
        self.c.close()
        _clear_data_root()
        self.tmp.cleanup()

    def test_export_with_no_pages_writes_empty_registry(self):
        out = os.path.join(self.tmp.name, "obsidian_index.json")
        houchen_publisher.export_obsidian_index(self.c, out_path=out)
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["pages"], [])
        self.assertEqual(data["schema_version"], 4)

    def test_export_includes_rendered_page_and_publish_status(self):
        page_id = _seed_rendered_page(self.tmp.name, self.c)
        w = FakeVaultWriter()
        houchen_runner.publish_with_path(
            conn=self.c, page_id=page_id, vault_path="Research/v.md",
            vault_writer=w, actor="t")
        out = os.path.join(self.tmp.name, "obsidian_index.json")
        houchen_publisher.export_obsidian_index(self.c, out_path=out)
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["pages"]), 1)
        self.assertEqual(data["pages"][0]["status"], "published")


class TestVaultPathComposition(unittest.TestCase):
    def test_default_prefix(self):
        p = houchen_publish_paths.vault_path_for(
            "video", "abc", houchen_publish_paths.DEFAULT_VAULT_PREFIX)
        self.assertEqual(p, "Research/世界苦茶/video/abc.md")

    def test_custom_prefix_normalizes_trailing_slash(self):
        p = houchen_publish_paths.vault_path_for("video", "abc", "Custom/")
        self.assertEqual(p, "Custom/video/abc.md")

    def test_invalid_prefix_rejected(self):
        with self.assertRaises(ValueError):
            houchen_publish_paths.vault_path_for("video", "abc", "")
        with self.assertRaises(ValueError):
            houchen_publish_paths.vault_path_for("video", "abc", "../escape/")


class TestObsidianLocalRestWriter(unittest.TestCase):
    def test_put_get_round_trip(self):
        import unittest.mock as mock

        writer = houchen_publisher.ObsidianLocalRestWriter(
            base_url="https://127.0.0.1:27124",
            api_token="test-token",
            timeout=5.0,
        )
        with mock.patch("requests.put") as put_mock, \
                mock.patch("requests.get") as get_mock:
            put_resp = mock.Mock()
            put_resp.raise_for_status = mock.Mock()
            put_mock.return_value = put_resp
            get_resp = mock.Mock()
            get_resp.status_code = 200
            get_resp.text = "hello vault"
            get_resp.raise_for_status = mock.Mock()
            get_mock.return_value = get_resp

            writer.put_pipeline("Research/世界苦茶/video/x.md", "hello vault")
            text = writer.get_pipeline("Research/世界苦茶/video/x.md")

        self.assertEqual(text, "hello vault")
        put_mock.assert_called_once()
        get_mock.assert_called_once()
        put_url = put_mock.call_args[0][0]
        self.assertIn("/vault/", put_url)
        self.assertIn("Research", put_url)

    def test_get_returns_none_on_404(self):
        import unittest.mock as mock

        writer = houchen_publisher.ObsidianLocalRestWriter(
            base_url="https://127.0.0.1:27124",
            api_token="test-token",
        )
        with mock.patch("requests.get") as get_mock:
            get_resp = mock.Mock()
            get_resp.status_code = 404
            get_mock.return_value = get_resp
            self.assertIsNone(writer.get_pipeline("missing.md"))