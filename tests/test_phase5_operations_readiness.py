import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import healthcheck_local, main, smoke_test, start_local_stack


class Phase5OperationsReadinessTests(unittest.TestCase):
    def test_health_payload_requires_startup_completion_and_path_convergence(self):
        with patch.object(main, "verify_path_convergence", return_value={"converged": True, "db_exists": True}), \
             patch.object(main, "_current_app_version", return_value="1.1.0"):
            main.STARTUP_STATE.update({"completed": False, "error": None, "last_started_at": "now"})

            payload = main._health_payload()

        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["checks"]["startup_completed"])

    def test_health_payload_reports_ready_when_startup_and_paths_are_ok(self):
        with patch.object(main, "verify_path_convergence", return_value={"converged": True, "db_exists": True}), \
             patch.object(main, "_current_app_version", return_value="1.1.0"):
            main.STARTUP_STATE.update({"completed": True, "error": None, "last_started_at": "now"})

            payload = main._health_payload(include_discovery=True)

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["ready"])
        self.assertIn("discovery", payload)

    def test_healthcheck_local_uses_health_payload_readiness(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps({"ready": True, "status": "ok"}).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False

        with patch("scripts.healthcheck_local.urllib.request.urlopen", return_value=response):
            result = healthcheck_local.check_json_url("http://127.0.0.1:8000/health")

        self.assertTrue(result["ok"])
        self.assertTrue(result["ready"])
        self.assertEqual(result["payload"]["status"], "ok")

    def test_start_local_stack_uses_vite_dev_and_waits_for_readiness(self):
        with patch.object(start_local_stack, "_spawn") as spawn, \
             patch.object(start_local_stack, "_wait_for", side_effect=[True, True]), \
             patch.object(start_local_stack, "_launcher_log"), \
             patch("scripts.start_local_stack.subprocess.run") as run_stop:
            result = start_local_stack.main()

        self.assertEqual(result, 0)
        run_stop.assert_called_once()
        backend_command = spawn.call_args_list[0].args[0]
        frontend_command = spawn.call_args_list[1].args[0]
        self.assertEqual(backend_command[:3], [start_local_stack.sys.executable, "-m", "uvicorn"])
        self.assertEqual(frontend_command[:3], [start_local_stack._npm_command(), "run", "dev"])
        self.assertIn("--host", frontend_command)
        self.assertIn("3000", frontend_command)

    def test_smoke_test_runtime_contract_matches_vite_and_tauri(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            package_json = root / "botardium-panel" / "web" / "package.json"
            tauri_json = root / "botardium-panel" / "web" / "src-tauri" / "tauri.conf.json"
            package_json.parent.mkdir(parents=True, exist_ok=True)
            tauri_json.parent.mkdir(parents=True, exist_ok=True)
            package_json.write_text(json.dumps({
                "scripts": {
                    "dev": "vite",
                    "dev:desktop": "npm run backend:build && vite",
                }
            }), encoding="utf-8")
            tauri_json.write_text(json.dumps({
                "build": {
                    "devUrl": "http://localhost:3000",
                    "beforeDevCommand": "npm run dev:desktop",
                }
            }), encoding="utf-8")

            with patch.object(smoke_test, "WEB_PACKAGE_JSON", package_json), \
                 patch.object(smoke_test, "TAURI_CONFIG_JSON", tauri_json):
                checks = smoke_test.check_runtime_contract()

        self.assertTrue(all(ok for _, ok, _ in checks))


if __name__ == "__main__":
    unittest.main()
