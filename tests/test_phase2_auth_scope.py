import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts import main, runtime_config


class Phase2AuthScopeTests(unittest.TestCase):
    def setUp(self):
        main.CAMPAIGN_STORE.clear()
        main.MESSAGE_JOB_STORE.clear()
        main.CAMPAIGN_TASKS.clear()
        main.ACCOUNT_WARMUP_TASKS.clear()

    def tearDown(self):
        main.CAMPAIGN_STORE.clear()
        main.MESSAGE_JOB_STORE.clear()
        main.CAMPAIGN_TASKS.clear()
        main.ACCOUNT_WARMUP_TASKS.clear()

    def test_login_session_returns_signed_workspace_scope(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                workspace_id = self._insert_workspace(db_path, "Demo Workspace", "demo-workspace")

                with TestClient(main.app) as client:
                    login_response = client.post("/api/auth/login", json={"workspace_id": workspace_id})
                    self.assertEqual(login_response.status_code, 200)
                    auth_payload = login_response.json()["auth"]

                    session_response = client.get(
                        "/api/auth/session",
                        headers=self._auth_headers(auth_payload["token"]),
                    )

            self.assertEqual(session_response.status_code, 200)
            session_payload = session_response.json()
            self.assertEqual(session_payload["workspace_id"], workspace_id)
            self.assertEqual(session_payload["workspace_slug"], "demo-workspace")
            self.assertEqual(session_payload["workspace_name"], "Demo Workspace")

    def test_in_scope_mutation_persists_audit_event(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                workspace_a = self._insert_workspace(db_path, "Workspace A", "workspace-a")
                lead_a = self._insert_lead(db_path, workspace_a, "lead_a")
                token_a = self._login_token(workspace_a)

                with TestClient(main.app) as client:
                    response = client.post(
                        "/api/leads/bulk-status",
                        headers=self._auth_headers(token_a),
                        json={"ids": [lead_a], "status": "Listo para contactar"},
                    )

                self.assertEqual(response.status_code, 200)

                conn = sqlite3.connect(db_path)
                lead_status = conn.execute("SELECT status FROM leads WHERE id = ?", (lead_a,)).fetchone()[0]
                audit_row = conn.execute(
                    "SELECT workspace_id, actor_id, action, outcome FROM audit_events WHERE action = ? ORDER BY id DESC LIMIT 1",
                    ("lead.bulk_status",),
                ).fetchone()
                conn.close()

            self.assertEqual(lead_status, "Listo para contactar")
            self.assertIsNotNone(audit_row)
            self.assertEqual(audit_row[0], workspace_a)
            self.assertEqual(audit_row[1], f"local-workspace:{workspace_a}")
            self.assertEqual(audit_row[2], "lead.bulk_status")
            self.assertEqual(audit_row[3], "allowed")

    def test_cross_workspace_mutation_is_denied_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                workspace_a = self._insert_workspace(db_path, "Workspace A", "workspace-a")
                workspace_b = self._insert_workspace(db_path, "Workspace B", "workspace-b")
                lead_b = self._insert_lead(db_path, workspace_b, "lead_b")
                token_a = self._login_token(workspace_a)

                with TestClient(main.app) as client:
                    response = client.post(
                        "/api/leads/bulk-status",
                        headers=self._auth_headers(token_a),
                        json={"ids": [lead_b], "status": "Listo para contactar"},
                    )

                self.assertEqual(response.status_code, 403)

                conn = sqlite3.connect(db_path)
                lead_status = conn.execute("SELECT status FROM leads WHERE id = ?", (lead_b,)).fetchone()[0]
                audit_row = conn.execute(
                    "SELECT workspace_id, action, outcome, detail FROM audit_events WHERE outcome = 'denied' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                conn.close()

            self.assertEqual(lead_status, "Pendiente")
            self.assertIsNotNone(audit_row)
            self.assertEqual(audit_row[0], workspace_a)
            self.assertEqual(audit_row[1], "lead.bulk_status")
            self.assertEqual(audit_row[2], "denied")
            self.assertIn("cross-workspace", audit_row[3])

    def test_workspace_delete_requires_authentication(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                workspace_a = self._insert_workspace(db_path, "Workspace A", "workspace-a")
                self._insert_workspace(db_path, "Workspace B", "workspace-b")

                with TestClient(main.app) as client:
                    response = client.delete(f"/api/workspaces/{workspace_a}")

            self.assertEqual(response.status_code, 401)

    def test_workspace_delete_cross_workspace_is_denied_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                workspace_a = self._insert_workspace(db_path, "Workspace A", "workspace-a")
                workspace_b = self._insert_workspace(db_path, "Workspace B", "workspace-b")
                token_a = self._login_token(workspace_a)

                with TestClient(main.app) as client:
                    response = client.delete(
                        f"/api/workspaces/{workspace_b}",
                        headers=self._auth_headers(token_a),
                    )

                self.assertEqual(response.status_code, 403)

                conn = sqlite3.connect(db_path)
                workspace_b_row = conn.execute("SELECT id FROM users WHERE id = ?", (workspace_b,)).fetchone()
                audit_row = conn.execute(
                    "SELECT workspace_id, action, outcome, detail FROM audit_events WHERE action = ? ORDER BY id DESC LIMIT 1",
                    ("workspace.delete",),
                ).fetchone()
                conn.close()

            self.assertIsNotNone(workspace_b_row)
            self.assertIsNotNone(audit_row)
            self.assertEqual(audit_row[0], workspace_a)
            self.assertEqual(audit_row[1], "workspace.delete")
            self.assertEqual(audit_row[2], "denied")
            self.assertIn("cross-workspace", audit_row[3])

    def test_workspace_delete_same_workspace_succeeds_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "database" / "botardium.db"
            runtime_secrets_path = root / "config" / "runtime_secrets.json"

            with self._runtime_patches(root, db_path, runtime_secrets_path):
                main.init_db()
                workspace_a = self._insert_workspace(db_path, "Workspace A", "workspace-a")
                self._insert_workspace(db_path, "Workspace B", "workspace-b")
                lead_a = self._insert_lead(db_path, workspace_a, "lead_a")
                token_a = self._login_token(workspace_a)

                with TestClient(main.app) as client:
                    response = client.delete(
                        f"/api/workspaces/{workspace_a}",
                        headers=self._auth_headers(token_a),
                    )

                self.assertEqual(response.status_code, 200)

                conn = sqlite3.connect(db_path)
                workspace_row = conn.execute("SELECT id FROM users WHERE id = ?", (workspace_a,)).fetchone()
                lead_row = conn.execute("SELECT id FROM leads WHERE id = ?", (lead_a,)).fetchone()
                audit_row = conn.execute(
                    "SELECT workspace_id, actor_id, action, outcome, resource_id FROM audit_events WHERE action = ? ORDER BY id DESC LIMIT 1",
                    ("workspace.delete",),
                ).fetchone()
                conn.close()

            self.assertIsNone(workspace_row)
            self.assertIsNone(lead_row)
            self.assertIsNotNone(audit_row)
            self.assertEqual(audit_row[0], workspace_a)
            self.assertEqual(audit_row[1], f"local-workspace:{workspace_a}")
            self.assertEqual(audit_row[2], "workspace.delete")
            self.assertEqual(audit_row[3], "allowed")
            self.assertEqual(audit_row[4], str(workspace_a))

    def _login_token(self, workspace_id: int) -> str:
        with TestClient(main.app) as client:
            response = client.post("/api/auth/login", json={"workspace_id": workspace_id})
        self.assertEqual(response.status_code, 200)
        return response.json()["auth"]["token"]

    def _insert_workspace(self, db_path: Path, name: str, slug: str) -> int:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, password_hash, full_name, workspace_name, workspace_slug, is_workspace) VALUES (?, '', ?, ?, ?, 1)",
            (f"{slug}@botardium.local", name, name, slug),
        )
        workspace_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return workspace_id

    def _insert_lead(self, db_path: Path, workspace_id: int, username: str) -> int:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO leads (username, ig_username, workspace_id, status, created_at) VALUES (?, ?, ?, 'Pendiente', datetime('now'))",
            (username, username, workspace_id),
        )
        lead_id = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return lead_id

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

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
        stack.enter_context(patch.dict(os.environ, {"BOTARDIUM_AUTH_SECRET": "phase2-test-secret"}, clear=False))
        return stack


if __name__ == "__main__":
    unittest.main()
