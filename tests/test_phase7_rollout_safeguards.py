import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from scripts import main, rollout_smoke_check, smoke_test
from scripts.rollout_flags import RolloutFlags, get_rollout_flags, latest_backup_snapshot


class _MockResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Phase7RolloutSafeguardsTests(unittest.TestCase):
    def test_rollout_flags_default_to_enforced_modes(self):
        with patch.dict("os.environ", {}, clear=False):
            flags = get_rollout_flags()

        self.assertEqual(flags.auth_mode, "enforce")
        self.assertEqual(flags.path_mode, "enforce")
        self.assertEqual(flags.durable_jobs_mode, "enforce")
        self.assertTrue(flags.require_backup_snapshot)

    def test_latest_backup_snapshot_returns_newest_db(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_root = Path(tmp_dir)
            older = snapshot_root / "older.db"
            newer = snapshot_root / "newer.db"
            older.write_text("old", encoding="utf-8")
            newer.write_text("new", encoding="utf-8")
            older.touch()
            newer.touch()

            snapshot = latest_backup_snapshot(snapshot_root)

        self.assertEqual(snapshot, newer)

    def test_health_payload_reports_rollout_and_backup_gate(self):
        flags = RolloutFlags(auth_mode="enforce", path_mode="enforce", durable_jobs_mode="enforce", require_backup_snapshot=True)
        with patch.object(main, "verify_path_convergence", return_value={"converged": True, "db_exists": True}), \
             patch.object(main, "_current_app_version", return_value="1.1.0"), \
             patch.object(main, "get_rollout_flags", return_value=flags), \
             patch.object(main, "latest_backup_snapshot", return_value=None):
            main.STARTUP_STATE.update({"completed": True, "error": None, "last_started_at": "now"})
            payload = main._health_payload()

        self.assertTrue(payload["ready"])
        self.assertFalse(payload["checks"]["backup_ready"])
        self.assertEqual(payload["rollout"]["path_mode"], "enforce")

    def test_health_payload_allows_shadow_path_mode_with_existing_db(self):
        flags = RolloutFlags(auth_mode="enforce", path_mode="shadow", durable_jobs_mode="shadow", require_backup_snapshot=False)
        with patch.object(main, "verify_path_convergence", return_value={"converged": False, "db_exists": True}), \
             patch.object(main, "_current_app_version", return_value="1.1.0"), \
             patch.object(main, "get_rollout_flags", return_value=flags), \
             patch.object(main, "latest_backup_snapshot", return_value=None):
            main.STARTUP_STATE.update({"completed": True, "error": None, "last_started_at": "now"})
            payload = main._health_payload()

        self.assertTrue(payload["ready"])
        self.assertIn("path_divergence_detected", payload["degraded_reasons"])

    def test_startup_skips_durable_recovery_in_shadow_mode(self):
        flags = RolloutFlags(auth_mode="enforce", path_mode="enforce", durable_jobs_mode="shadow", require_backup_snapshot=True)
        with patch.object(main, "get_rollout_flags", return_value=flags), \
             patch.object(main, "init_db"), \
             patch.object(main, "_connect_db") as connect_db, \
             patch.object(main, "migrate_legacy_workspace_ai_secrets"), \
             patch.object(main, "migrate_runtime_ai_store_to_google_only"), \
             patch.object(main, "_ensure_leads_workspace_safe_schema"), \
             patch.object(main, "_load_persisted_runtime_state"), \
             patch.object(main, "_recover_durable_outreach_jobs") as recover_outreach, \
             patch.object(main, "_recover_durable_campaign_jobs") as recover_campaigns, \
             patch.object(main, "cleanup_legacy_message_previews"), \
             patch.object(main, "load_bootstrap_env"):
            connect_db.return_value = type("Conn", (), {"commit": lambda self: None, "close": lambda self: None})()
            main.startup_event()

        recover_outreach.assert_not_called()
        recover_campaigns.assert_not_called()

    def test_require_actor_supports_shadow_mode_with_workspace_hint(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/messages/jobs",
            "headers": [],
            "query_string": b"workspace_id=7",
        }
        request = Request(scope)
        flags = RolloutFlags(auth_mode="shadow", path_mode="enforce", durable_jobs_mode="enforce", require_backup_snapshot=True)
        with patch.object(main, "get_rollout_flags", return_value=flags), \
             patch.object(main, "actor_from_request", side_effect=HTTPException(status_code=401, detail="missing")), \
             patch.object(main, "_workspace_record", return_value={"id": 7, "workspace_slug": "demo", "workspace_name": "Demo"}):
            actor = main._require_actor(request)

        self.assertEqual(actor.workspace_id, 7)
        self.assertEqual(actor.actor_id, "shadow-workspace:7")

    def test_rollout_smoke_check_covers_login_session_and_job_polling(self):
        responses = {
            "http://127.0.0.1:8000/health": _MockResponse({"ready": True, "status": "ok"}),
            "http://127.0.0.1:8000/api/ops/rollout": _MockResponse({"status": "ok"}),
            "http://127.0.0.1:8000/api/auth/login": _MockResponse({"auth": {"token": "abc"}}),
            "http://127.0.0.1:8000/api/auth/session": _MockResponse({"workspace_id": 3}),
            "http://127.0.0.1:8000/api/messages/jobs?workspace_id=3": _MockResponse({"jobs": []}),
        }

        def fake_urlopen(request, timeout=0):
            url = request.full_url if hasattr(request, "full_url") else request
            return responses[url]

        with patch("scripts.rollout_smoke_check.urllib.request.urlopen", side_effect=fake_urlopen):
            result = rollout_smoke_check.run_rollout_smoke_check("http://127.0.0.1:8000", 3)

        self.assertTrue(result["ok"])
        self.assertTrue(result["checks"]["job_polling"]["ok"])

    def test_panel_contract_keeps_token_and_job_polling_hooks(self):
        checks = smoke_test.check_panel_contract()
        failed = [name for name, ok, _ in checks if not ok]
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
