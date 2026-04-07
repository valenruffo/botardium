import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_save_and_resolve_workspace_ai_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_store = Path(tmp_dir) / "runtime_secrets.json"
            with patch.object(runtime_config, "RUNTIME_SECRETS_PATH", runtime_store):
                runtime_config.save_workspace_ai_config(7, google_api_key="g-key")
                resolved = runtime_config.get_workspace_ai_config(7)

        self.assertEqual(resolved["google_api_key"], "g-key")
        self.assertEqual(resolved, {"google_api_key": "g-key"})

    def test_migrate_runtime_ai_store_to_google_only_removes_openai_entries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_store = Path(tmp_dir) / "runtime_secrets.json"
            runtime_store.write_text(
                '{"version": 1, "workspaces": {"7": {"google_api_key": "g-key", "openai_api_key": "o-key"}, "8": {"openai_api_key": "o-only"}}}',
                encoding="utf-8",
            )
            with patch.object(runtime_config, "RUNTIME_SECRETS_PATH", runtime_store):
                migrated = runtime_config.migrate_runtime_ai_store_to_google_only()
                resolved = runtime_config.get_workspace_ai_config(7)
                raw_store = runtime_store.read_text(encoding="utf-8")

        self.assertEqual(migrated, 2)
        self.assertEqual(resolved, {"google_api_key": "g-key"})
        self.assertNotIn("openai_api_key", raw_store)

    def test_sanitize_workspace_export_payload_omits_sensitive_fields(self):
        payload = {
            "workspace": {
                "workspace_name": "Demo",
                "google_api_key": "g-secret",
                "openai_api_key": "o-secret",
                "password_hash": "hashed",
            },
            "ig_accounts": [
                {"id": 1, "ig_username": "demo", "ig_password": "super-secret"},
            ],
        }

        sanitized, omitted = runtime_config.sanitize_workspace_export_payload(payload)

        self.assertNotIn("google_api_key", sanitized["workspace"])
        self.assertNotIn("openai_api_key", sanitized["workspace"])
        self.assertNotIn("password_hash", sanitized["workspace"])
        self.assertNotIn("ig_password", sanitized["ig_accounts"][0])
        self.assertIn("ai_keys", omitted)
        self.assertIn("credentials", omitted)

    def test_detect_sensitive_import_content_flags_legacy_archives(self):
        payload = {
            "workspace": {"workspace_name": "Demo", "openai_api_key": "o-secret"},
            "ig_accounts": [{"id": 1, "ig_username": "demo", "ig_password": "secret"}],
        }

        violations = runtime_config.detect_sensitive_import_content(
            payload,
            archive_names=["workspace.json", "sessions/demo/storage_state.json"],
        )

        self.assertEqual(set(violations), {"ai_keys", "credentials", "session_material"})

    def test_migrate_legacy_workspace_ai_secrets_moves_db_values_to_runtime_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_store = Path(tmp_dir) / "runtime_secrets.json"
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, google_api_key TEXT, openai_api_key TEXT)"
            )
            conn.execute(
                "INSERT INTO users (id, google_api_key, openai_api_key) VALUES (1, 'g-legacy', 'o-legacy')"
            )
            with patch.object(runtime_config, "RUNTIME_SECRETS_PATH", runtime_store):
                migrated = runtime_config.migrate_legacy_workspace_ai_secrets(conn)
                conn.commit()
                resolved = runtime_config.get_workspace_ai_config(1)
                row = conn.execute(
                    "SELECT google_api_key, openai_api_key FROM users WHERE id = 1"
                ).fetchone()

        self.assertEqual(migrated, 1)
        self.assertEqual(resolved["google_api_key"], "g-legacy")
        self.assertEqual(resolved, {"google_api_key": "g-legacy"})
        self.assertEqual(row["google_api_key"], "")
        self.assertEqual(row["openai_api_key"], "")


if __name__ == "__main__":
    unittest.main()
