"""
Smoke Suite de Hashtags (regresion operativa)

Uso:
  python scripts/smoke_hashtag_suite.py --hashtags esteticasargentina clinicasesteticasargentina --limit 8

Opcional:
  python scripts/smoke_hashtag_suite.py --hashtags esteticasargentina --min-posts-seen 10 --min-accepted 1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scripts.runtime_paths import TMP_DIR, SOURCE_ROOT

STATUS_FILE = TMP_DIR / "scraper_status.json"
REPORT_FILE = TMP_DIR / "hashtag_smoke_report.json"
PROJECT_ROOT = SOURCE_ROOT


def _run_hashtag(query: str, limit: int, timeout: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "lead_scraper.py"),
        "--target",
        "hashtag",
        "--query",
        query,
        "--limit",
        str(limit),
    ]

    started_at = time.time()
    proc = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = round(time.time() - started_at, 2)

    status_payload: dict[str, Any] = {}
    if STATUS_FILE.exists():
        try:
            status_payload = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            status_payload = {}

    meta_raw = status_payload.get("meta")
    meta: dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
    rejected_raw = meta.get("rejected")
    rejected: dict[str, int] = rejected_raw if isinstance(rejected_raw, dict) else {}

    return {
        "query": query,
        "exit_code": proc.returncode,
        "elapsed_sec": elapsed,
        "status": str(status_payload.get("status") or "unknown"),
        "message": str(status_payload.get("message") or ""),
        "accepted_count": int(meta.get("accepted_count") or 0),
        "posts_seen": int(meta.get("posts_seen") or 0),
        "authors_seen": int(meta.get("authors_seen") or 0),
        "profile_errors": int(meta.get("profile_errors") or 0),
        "rejected": rejected,
        "stdout_tail": (proc.stdout or "")[-1500:],
        "stderr_tail": (proc.stderr or "")[-1500:],
    }


def _evaluate_case(case: dict[str, Any], min_posts_seen: int, min_accepted: int, min_qualified: int) -> tuple[bool, str]:
    if case["exit_code"] != 0:
        return False, "scraper_error"
    if case["status"] not in {"done", "running"}:
        return False, f"status_{case['status']}"
    if case["posts_seen"] < min_posts_seen:
        return False, "low_posts_seen"
    duplicate_count = int((case.get("rejected") or {}).get("duplicado") or 0)
    qualified = int(case.get("accepted_count") or 0) + duplicate_count
    if qualified < min_qualified:
        return False, "low_qualified"
    if case["accepted_count"] < min_accepted:
        return False, "low_accepted"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Suite de regresion para scraping por hashtags")
    parser.add_argument("--hashtags", nargs="+", required=True, help="Lista de hashtags sin #")
    parser.add_argument("--limit", type=int, default=8, help="Limite de scraping por hashtag")
    parser.add_argument("--timeout", type=int, default=240, help="Timeout por hashtag en segundos")
    parser.add_argument("--min-posts-seen", type=int, default=6, help="Minimo de posts vistos por hashtag")
    parser.add_argument("--min-accepted", type=int, default=0, help="Minimo de leads aceptados nuevos por hashtag")
    parser.add_argument("--min-qualified", type=int, default=1, help="Minimo de candidatos validos (aceptados + duplicados)")
    args = parser.parse_args()

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    print("=" * 68)
    print("Botardium - Smoke Suite Hashtags")
    print("=" * 68)

    for tag in args.hashtags:
        query = str(tag).replace("#", "").strip().lower()
        if not query:
            continue
        print(f"[RUN] #{query} ...")
        case = _run_hashtag(query=query, limit=max(1, args.limit), timeout=max(30, args.timeout))
        passed, reason = _evaluate_case(
            case,
            min_posts_seen=max(0, args.min_posts_seen),
            min_accepted=max(0, args.min_accepted),
            min_qualified=max(0, args.min_qualified),
        )
        case["passed"] = passed
        case["reason"] = reason
        cases.append(case)

        status_line = (
            f"  -> status={case['status']} accepted={case['accepted_count']} posts={case['posts_seen']} "
            f"authors={case['authors_seen']} rejected={case['rejected']}"
        )
        print(status_line)
        print(f"  -> {'PASS' if passed else 'FAIL'} ({reason}) en {case['elapsed_sec']}s")

        if not passed:
            failures.append(case)

    report = {
        "timestamp": int(time.time()),
        "config": {
            "hashtags": [str(tag).replace("#", "").strip().lower() for tag in args.hashtags],
            "limit": args.limit,
            "timeout": args.timeout,
            "min_posts_seen": args.min_posts_seen,
            "min_accepted": args.min_accepted,
            "min_qualified": args.min_qualified,
        },
        "cases": cases,
        "summary": {
            "total": len(cases),
            "passed": sum(1 for case in cases if case.get("passed")),
            "failed": len(failures),
        },
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    print("-" * 68)
    print(
        f"Resultado: {report['summary']['passed']}/{report['summary']['total']} PASS | "
        f"reporte: {REPORT_FILE}"
    )
    print("-" * 68)

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
