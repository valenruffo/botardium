"""
Botardium Core — Job Runtime
============================
Persistent job records with lease recovery and idempotency.

This module provides:
- Persisted job records in SQLite
- Lease-based locking for distributed-safe processing
- Idempotency key deduplication
- Progress checkpoints for resumable jobs
- Recovery scan for orphaned jobs on startup
"""

import os
import sqlite3
import json
import logging
import asyncio
import hashlib
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager

from scripts.runtime_paths import DB_PATH, DB_DIR, ensure_runtime_dirs

logger = logging.getLogger("botardium.job_runtime")

ensure_runtime_dirs()

JOB_LEASE_TIMEOUT_SECONDS = 300
JOB_EXPIRY_SECONDS = 86400 * 7


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    MESSAGE_OUTREACH = "message_outreach"
    CAMPAIGN_WARMUP = "campaign_warmup"
    SCRAPE_LEADS = "scrape_leads"
    ACCOUNT_WARMUP = "account_warmup"


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    workspace_id: int
    status: str
    idempotency_key: Optional[str]
    payload: Dict[str, Any]
    progress: float
    checkpoint: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    lease_expires_at: Optional[str]
    leased_by: Optional[str]
    error: Optional[str]
    result: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        return cls(**dict(row))


class JobRuntime:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path if db_path is not None else DB_PATH
        self._ensure_db()

    def _ensure_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    workspace_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    idempotency_key TEXT,
                    payload TEXT NOT NULL DEFAULT '{}',
                    progress REAL DEFAULT 0.0,
                    checkpoint TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    lease_expires_at TEXT,
                    leased_by TEXT,
                    error TEXT,
                    result TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_workspace ON jobs(workspace_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key)")
            conn.commit()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def generate_idempotency_key(self, *parts: str) -> str:
        combined = "|".join(str(p) for p in parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:32]

    def create_job(
        self,
        job_id: str,
        job_type: str,
        workspace_id: int,
        payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Optional[JobRecord]:
        now = datetime.now().isoformat()

        if idempotency_key:
            existing = self.get_job_by_idempotency_key(idempotency_key, workspace_id)
            if existing:
                logger.info(f"Duplicate job detected via idempotency key {idempotency_key}, returning existing job {existing.job_id}")
                return existing

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO jobs (job_id, job_type, workspace_id, status, idempotency_key, payload, progress, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0.0, ?)
            """, (job_id, job_type, workspace_id, JobStatus.PENDING.value, idempotency_key, json.dumps(payload), now))
            conn.commit()

        logger.info(f"Created job {job_id} of type {job_type} for workspace {workspace_id}")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return JobRecord.from_row(row)
        return None

    def get_job_by_idempotency_key(self, idempotency_key: str, workspace_id: int) -> Optional[JobRecord]:
        if not idempotency_key:
            return None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ? AND workspace_id = ?",
                (idempotency_key, workspace_id)
            )
            row = cursor.fetchone()
            if row:
                return JobRecord.from_row(row)
        return None

    def list_jobs(self, workspace_id: int, status: Optional[str] = None, limit: int = 100) -> List[JobRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM jobs WHERE workspace_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, status, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM jobs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, limit)
                )
            return [JobRecord.from_row(row) for row in cursor.fetchall()]

    def try_acquire_lease(self, job_id: str, worker_id: str) -> bool:
        now = datetime.now()
        lease_expires = now + timedelta(seconds=JOB_LEASE_TIMEOUT_SECONDS)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Job {job_id} not found for lease acquisition")
                return False

            current_status = row["status"]
            current_lease_expires = row["lease_expires_at"]

            if current_status == JobStatus.COMPLETED.value:
                logger.info(f"Job {job_id} already completed")
                return False

            if current_status == JobStatus.FAILED.value:
                allow_retry = row.get("error") and (now - datetime.fromisoformat(row["completed_at"])).total_seconds() > 300
                if not allow_retry:
                    logger.info(f"Job {job_id} failed and not eligible for retry")
                    return False

            if current_lease_expires:
                lease_expiry = datetime.fromisoformat(current_lease_expires)
                if lease_expiry > now:
                    if row["leased_by"] != worker_id:
                        logger.info(f"Job {job_id} leased by {row['leased_by']}, cannot acquire")
                        return False

            cursor.execute("""
                UPDATE jobs 
                SET status = ?, leased_by = ?, lease_expires_at = ?, started_at = COALESCE(started_at, ?)
                WHERE job_id = ? AND (lease_expires_at IS NULL OR lease_expires_at < ? OR leased_by = ?)
            """, (JobStatus.RUNNING.value, worker_id, lease_expires.isoformat(), now.isoformat(), job_id, now.isoformat(), worker_id))
            conn.commit()

            if cursor.rowcount > 0:
                logger.info(f"Worker {worker_id} acquired lease on job {job_id}")
                return True
            return False

    def release_lease(self, job_id: str, worker_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET lease_expires_at = NULL, leased_by = NULL
                WHERE job_id = ? AND leased_by = ?
            """, (job_id, worker_id))
            conn.commit()

    def update_progress(self, job_id: str, progress: float, checkpoint: Optional[str] = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if checkpoint:
                cursor.execute(
                    "UPDATE jobs SET progress = ?, checkpoint = ? WHERE job_id = ?",
                    (progress, checkpoint, job_id)
                )
            else:
                cursor.execute(
                    "UPDATE jobs SET progress = ? WHERE job_id = ?",
                    (progress, job_id)
                )
            conn.commit()

    def complete_job(self, job_id: str, result: Optional[Dict[str, Any]] = None):
        now = datetime.now().isoformat()
        result_json = json.dumps(result) if result else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, completed_at = ?, progress = 1.0, lease_expires_at = NULL, leased_by = NULL, result = ?
                WHERE job_id = ?
            """, (JobStatus.COMPLETED.value, now, result_json, job_id))
            conn.commit()
        logger.info(f"Job {job_id} completed with result: {result_json}")

    def fail_job(self, job_id: str, error: str):
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, completed_at = ?, error = ?, lease_expires_at = NULL, leased_by = NULL
                WHERE job_id = ?
            """, (JobStatus.FAILED.value, now, error, job_id))
            conn.commit()
        logger.error(f"Job {job_id} failed: {error}")

    def cancel_job(self, job_id: str):
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, completed_at = ?, lease_expires_at = NULL, leased_by = NULL
                WHERE job_id = ?
            """, (JobStatus.CANCELLED.value, now, job_id))
            conn.commit()
        logger.info(f"Job {job_id} cancelled")

    def recover_orphaned_jobs(self, worker_id: str) -> List[JobRecord]:
        now = datetime.now()
        recovered = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = ? 
                AND lease_expires_at IS NOT NULL 
                AND lease_expires_at < ?
            """, (JobStatus.RUNNING.value, now.isoformat()))
            
            for row in cursor.fetchall():
                job = JobRecord.from_row(row)
                if self.try_acquire_lease(job.job_id, worker_id):
                    recovered.append(job)
                    logger.info(f"Recovered orphaned job {job.job_id}")

        return recovered

    def scan_for_stale_jobs(self, max_age_seconds: int = JOB_LEASE_TIMEOUT_SECONDS * 2) -> List[JobRecord]:
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = ? 
                AND started_at IS NOT NULL 
                AND started_at < ?
            """, (JobStatus.RUNNING.value, cutoff.isoformat()))
            return [JobRecord.from_row(row) for row in cursor.fetchall()]

    def cleanup_old_jobs(self, max_age_days: int = 7):
        cutoff = datetime.now() - timedelta(days=max_age_days)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM jobs 
                WHERE status IN (?, ?, ?) 
                AND completed_at < ?
            """, (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value, cutoff.isoformat()))
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleaned up {deleted} old jobs")
            return deleted


_global_runtime: Optional[JobRuntime] = None
_runtime_lock = threading.Lock()


def get_job_runtime() -> JobRuntime:
    global _global_runtime
    if _global_runtime is None:
        with _runtime_lock:
            if _global_runtime is None:
                _global_runtime = JobRuntime()
    return _global_runtime


class JobContext:
    def __init__(self, job_runtime: JobRuntime, job_id: str, worker_id: str):
        self.job_runtime = job_runtime
        self.job_id = job_id
        self.worker_id = worker_id
        self._acquired = False

    def __enter__(self):
        if self.job_runtime.try_acquire_lease(self.job_id, self.worker_id):
            self._acquired = True
            return self
        raise RuntimeError(f"Could not acquire lease for job {self.job_id}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._acquired:
            self.job_runtime.release_lease(self.job_id, self.worker_id)
        return False

    def update_progress(self, progress: float, checkpoint: Optional[str] = None):
        self.job_runtime.update_progress(self.job_id, progress, checkpoint)

    def complete(self, result: Optional[Dict[str, Any]] = None):
        self.job_runtime.complete_job(self.job_id, result)

    def fail(self, error: str):
        self.job_runtime.fail_job(self.job_id, error)


@contextmanager
def managed_job(job_id: str, worker_id: str, job_runtime: Optional[JobRuntime] = None):
    runtime = job_runtime if job_runtime else get_job_runtime()
    ctx = JobContext(runtime, job_id, worker_id)
    try:
        with ctx:
            yield ctx
    except Exception as e:
        ctx.fail(str(e))
        raise
