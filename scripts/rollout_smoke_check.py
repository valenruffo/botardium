import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple


def _json_request(url: str, *, method: str = "GET", payload: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None) -> Tuple[bool, Dict[str, Any]]:
    data = None
    final_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=final_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
        return True, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        detail: Dict[str, Any]
        try:
            detail = json.loads(body) if body else {}
        except json.JSONDecodeError:
            detail = {"detail": body or str(exc)}
        detail.setdefault("status_code", exc.code)
        return False, detail
    except Exception as exc:
        return False, {"detail": str(exc)}


def run_rollout_smoke_check(base_url: str, workspace_id: int | None = None) -> Dict[str, Any]:
    normalized_base = base_url.rstrip("/")
    result: Dict[str, Any] = {
        "base_url": normalized_base,
        "checks": {},
        "ok": False,
    }

    health_ok, health_payload = _json_request(f"{normalized_base}/health")
    result["checks"]["health"] = {"ok": health_ok and bool(health_payload.get("ready")), "payload": health_payload}

    rollout_ok, rollout_payload = _json_request(f"{normalized_base}/api/ops/rollout")
    result["checks"]["rollout"] = {"ok": rollout_ok, "payload": rollout_payload}

    if workspace_id is not None:
        login_ok, login_payload = _json_request(
            f"{normalized_base}/api/auth/login",
            method="POST",
            payload={"workspace_id": int(workspace_id)},
        )
        result["checks"]["login"] = {"ok": login_ok, "payload": login_payload}
        token = str(login_payload.get("auth", {}).get("token") or "")
        if token:
            auth_headers = {"Authorization": f"Bearer {token}"}
            session_ok, session_payload = _json_request(
                f"{normalized_base}/api/auth/session",
                headers=auth_headers,
            )
            jobs_ok, jobs_payload = _json_request(
                f"{normalized_base}/api/messages/jobs?workspace_id={int(workspace_id)}",
                headers=auth_headers,
            )
            result["checks"]["session"] = {"ok": session_ok, "payload": session_payload}
            result["checks"]["job_polling"] = {"ok": jobs_ok and isinstance(jobs_payload.get("jobs"), list), "payload": jobs_payload}

    result["ok"] = all(check.get("ok") for check in result["checks"].values())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rollout smoke checks for Botardium")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace-id", type=int, default=None)
    args = parser.parse_args()

    result = run_rollout_smoke_check(args.base_url, args.workspace_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
