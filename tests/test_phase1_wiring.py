import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts import main, runtime_config


class Phase1WiringTests(unittest.TestCase):
    def setUp(self):
        main.CAMPAIGN_STORE.clear()
        main.MESSAGE_JOB_STORE.clear()

    def tearDown(self):
        main.CAMPAIGN_STORE.clear()
        main.MESSAGE_JOB_STORE.clear()

    def test_startup_event_migrates_legacy_workspace_ai_secrets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                conn = sqlite3.connect(db_path)
                conn.execute(
                    "INSERT INTO users (email, password_hash, full_name, workspace_name, workspace_slug, is_workspace, google_api_key, openai_api_key) VALUES (?, '', ?, ?, ?, 1, ?, ?)",
                    (
                        "demo@botardium.local",
                        "Demo Workspace",
                        "Demo Workspace",
                        "demo-workspace",
                        "g-legacy",
                        "o-legacy",
                    ),
                )
                conn.commit()
                conn.close()

                main.startup_event()

                conn = sqlite3.connect(db_path)
                row = conn.execute(
                    "SELECT google_api_key, openai_api_key FROM users WHERE workspace_slug = ?",
                    ("demo-workspace",),
                ).fetchone()
                conn.close()

                resolved = runtime_config.get_workspace_ai_config(1)

            self.assertEqual(row[0], "")
            self.assertEqual(row[1], "")
            self.assertEqual(resolved["google_api_key"], "g-legacy")
            self.assertEqual(resolved["openai_api_key"], "o-legacy")

    def test_export_route_omits_credentials_and_writes_notice(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (email, password_hash, full_name, workspace_name, workspace_slug, is_workspace) VALUES (?, ?, ?, ?, ?, 1)",
                    (
                        "demo@botardium.local",
                        "hashed-secret",
                        "Demo Workspace",
                        "Demo Workspace",
                        "demo-workspace",
                    ),
                )
                workspace_id = int(cursor.lastrowid)
                cursor.execute(
                    "INSERT INTO ig_accounts (user_id, ig_username, ig_password) VALUES (?, ?, ?)",
                    (workspace_id, "demo_account", "super-secret"),
                )
                conn.commit()
                conn.close()

                with TestClient(main.app) as client:
                    response = client.post(f"/api/workspaces/{workspace_id}/export")

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                archive_path = Path(payload["path"])
                self.assertTrue(archive_path.exists())
                self.assertIn("credentials", payload["omitted_data_classes"])

                with zipfile.ZipFile(archive_path, "r") as archive:
                    workspace_payload = json.loads(archive.read("workspace.json").decode("utf-8"))
                    notice_payload = json.loads(archive.read("export_notice.json").decode("utf-8"))

            self.assertNotIn("password_hash", workspace_payload["workspace"])
            self.assertNotIn("ig_password", workspace_payload["ig_accounts"][0])
            self.assertEqual(notice_payload["omitted_data_classes"], payload["omitted_data_classes"])

    def test_import_route_rejects_sensitive_archives(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"
            archive_path = root / "legacy-workspace.zip"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(
                        "workspace.json",
                        json.dumps(
                            {
                                "workspace": {
                                    "workspace_name": "Imported Workspace",
                                    "openai_api_key": "o-secret",
                                }
                            }
                        ),
                    )
                    archive.writestr("sessions/demo/storage_state.json", "{}")

                with TestClient(main.app) as client:
                    response = client.post(
                        "/api/workspaces/import",
                        json={"zip_path": str(archive_path)},
                    )

            self.assertEqual(response.status_code, 400)
            detail = response.json()["detail"]
            self.assertEqual(set(detail["prohibited_content_classes"]), {"ai_keys", "session_material"})

    def _runtime_patches(self, root: Path, db_path: Path, runtime_secrets_path: Path) -> ExitStack:
        downloads_dir = root / "downloads"
        exports_dir = root / ".tmp" / "workspace_exports"
        imports_dir = root / ".tmp" / "workspace_imports"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        exports_dir.mkdir(parents=True, exist_ok=True)
        imports_dir.mkdir(parents=True, exist_ok=True)
        runtime_secrets_path.parent.mkdir(parents=True, exist_ok=True)

        stack = ExitStack()
        stack.enter_context(patch.object(main, "DB_PATH", db_path))
        stack.enter_context(patch.object(main, "EXPORTS_TMP_DIR", exports_dir))
        stack.enter_context(patch.object(main, "IMPORTS_TMP_DIR", imports_dir))
        stack.enter_context(patch.object(main, "_downloads_dir", return_value=downloads_dir))
        stack.enter_context(patch.object(runtime_config, "RUNTIME_SECRETS_PATH", runtime_secrets_path))
        return stack


if __name__ == "__main__":
    unittest.main()
