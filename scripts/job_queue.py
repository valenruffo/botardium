"""
Botardium Core — Job Queue Distribution System
===============================================
Distributed job queue with worker pool, dead letter queue, and metrics.

This module provides:
- WorkerPool: register workers, heartbeats, job assignment
- JobQueue: enqueue/dequeue jobs, requeue abandoned, stats
- DeadLetterQueue: failed job handling with retry logic
- SQLite-backed with WAL mode for concurrency
"""

import os
import sqlite3
import json
import logging
import threading
import time
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
from uuid import uuid4

from scripts.runtime_paths import DB_DIR
from scripts.observabilidad.metrics_collector import MetricsCollector

logger = logging.getLogger("botardium.job_queue")

DB_DIR.mkdir(parents=True, exist_ok=True)
JOB_QUEUE_DB = DB_DIR / "job_queue.db"

WORKER_HEARTBEAT_TIMEOUT_SECONDS = 60
ABANDONED_JOB_THRESHOLD_SECONDS = 300
MAX_DLQ_RETRIES = 3
DLQ_RETRY_DELAY_SECONDS = 300


class QueueStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class Worker:
    worker_id: str
    worker_type: str
    capabilities: List[str]
    status: str
    current_job_id: Optional[str]
    registered_at: str
    last_heartbeat: str
    job_count: int


@dataclass
class QueuedJob:
    job_id: str
    job_type: str
    workspace_id: int
    payload: Dict[str, Any]
    priority: int
    status: str
    assigned_worker: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    attempts: int
    error: Optional[str]


@dataclass
class DeadLetterJob:
    dlq_id: str
    original_job_id: str
    job_type: str
    workspace_id: int
    payload: Dict[str, Any]
    error: str
    retry_count: int
    created_at: str
    last_retry_at: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class JobQueueDB:
    def __init__(self, db_path: Path = JOB_QUEUE_DB):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    worker_type TEXT NOT NULL,
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'idle',
                    current_job_id TEXT,
                    registered_at TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL,
                    job_count INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_queue (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    workspace_id INTEGER NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    priority INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    assigned_worker TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    attempts INTEGER DEFAULT 0,
                    error TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letter_queue (
                    dlq_id TEXT PRIMARY KEY,
                    original_job_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    workspace_id INTEGER NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_retry_at TEXT
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_priority ON job_queue(priority DESC, created_at ASC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_workspace ON job_queue(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dlq_retry ON dead_letter_queue(retry_count, created_at)")
            
            conn.commit()
    
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


class WorkerPool:
    def __init__(self, db: Optional[JobQueueDB] = None, metrics: Optional[MetricsCollector] = None):
        self.db = db or JobQueueDB()
        self.metrics = metrics
    
    def register_worker(
        self,
        worker_id: str,
        worker_type: str = "generic",
        capabilities: Optional[List[str]] = None
    ) -> Worker:
        now = _now_iso()
        capabilities = capabilities or []
        
        with self.db._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO workers 
                (worker_id, worker_type, capabilities, status, registered_at, last_heartbeat, job_count)
                VALUES (?, ?, ?, 'idle', ?, ?, 0)
            """, (worker_id, worker_type, json.dumps(capabilities), now, now))
            conn.commit()
        
        logger.info(f"Worker {worker_id} registered with type {worker_type}")
        
        if self.metrics:
            self.metrics.incr("workers.registered")
            self.metrics.gauge("workers.active", float(len(self.get_available_workers())))
        
        return self.get_worker(worker_id)
    
    def heartbeat(self, worker_id: str) -> bool:
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE workers 
                SET last_heartbeat = ?, status = 'idle', current_job_id = NULL
                WHERE worker_id = ? 
                AND (? - last_heartbeat) < ?
            """, (now, worker_id, now, WORKER_HEARTBEAT_TIMEOUT_SECONDS * 2))
            conn.commit()
            
            if cursor.rowcount > 0:
                if self.metrics:
                    self.metrics.incr("workers.heartbeat")
                return True
            return False
    
    def get_available_workers(self, worker_type: Optional[str] = None) -> List[Worker]:
        now = _now_dt()
        cutoff = now - timedelta(seconds=WORKER_HEARTBEAT_TIMEOUT_SECONDS)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            if worker_type:
                cursor.execute("""
                    SELECT * FROM workers 
                    WHERE status = 'idle' 
                    AND last_heartbeat >= ?
                    AND worker_type = ?
                    ORDER BY job_count ASC
                """, (cutoff_str, worker_type))
            else:
                cursor.execute("""
                    SELECT * FROM workers 
                    WHERE status = 'idle' 
                    AND last_heartbeat >= ?
                    ORDER BY job_count ASC
                """, (cutoff_str,))
            
            rows = cursor.fetchall()
            
        workers = []
        for row in rows:
            workers.append(Worker(
                worker_id=row["worker_id"],
                worker_type=row["worker_type"],
                capabilities=json.loads(row["capabilities"]),
                status=row["status"],
                current_job_id=row["current_job_id"],
                registered_at=row["registered_at"],
                last_heartbeat=row["last_heartbeat"],
                job_count=row["job_count"]
            ))
        
        return workers
    
    def assign_job(self, worker_id: str, job_id: str) -> bool:
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE workers 
                SET status = 'busy', current_job_id = ?, job_count = job_count + 1
                WHERE worker_id = ? AND status = 'idle'
            """, (job_id, worker_id))
            
            if cursor.rowcount == 0:
                return False
            
            cursor.execute("""
                UPDATE job_queue 
                SET status = 'assigned', assigned_worker = ?, started_at = ?
                WHERE job_id = ?
            """, (worker_id, now, job_id))
            
            conn.commit()
        
        logger.info(f"Assigned job {job_id} to worker {worker_id}")
        
        if self.metrics:
            self.metrics.incr("jobs.dispatched")
            self.metrics.gauge("workers.active", float(len(self.get_available_workers())))
        
        return True
    
    def release_worker(self, worker_id: str):
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE workers 
                SET status = 'idle', current_job_id = NULL
                WHERE worker_id = ?
            """, (worker_id,))
            conn.commit()
        
        if self.metrics:
            self.metrics.gauge("workers.active", float(len(self.get_available_workers())))
    
    def get_worker(self, worker_id: str) -> Optional[Worker]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,))
            row = cursor.fetchone()
            
            if row:
                return Worker(
                    worker_id=row["worker_id"],
                    worker_type=row["worker_type"],
                    capabilities=json.loads(row["capabilities"]),
                    status=row["status"],
                    current_job_id=row["current_job_id"],
                    registered_at=row["registered_at"],
                    last_heartbeat=row["last_heartbeat"],
                    job_count=row["job_count"]
                )
        return None
    
    def cleanup_stale_workers(self, max_age_seconds: int = WORKER_HEARTBEAT_TIMEOUT_SECONDS * 3) -> int:
        cutoff = _now_dt() - timedelta(seconds=max_age_seconds)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM workers 
                WHERE last_heartbeat < ? AND status = 'idle'
            """, (cutoff_str,))
            deleted = cursor.rowcount
            conn.commit()
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} stale workers")
        
        return deleted


class JobQueue:
    def __init__(self, db: Optional[JobQueueDB] = None, metrics: Optional[MetricsCollector] = None):
        self.db = db or JobQueueDB()
        self.metrics = metrics
    
    def enqueue(
        self,
        job_id: str,
        job_type: str,
        workspace_id: int,
        payload: Dict[str, Any],
        priority: int = 0
    ) -> QueuedJob:
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            conn.execute("""
                INSERT INTO job_queue 
                (job_id, job_type, workspace_id, payload, priority, status, created_at, attempts)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, 0)
            """, (job_id, job_type, workspace_id, json.dumps(payload), priority, now))
            conn.commit()
        
        logger.info(f"Enqueued job {job_id} of type {job_type}")
        
        if self.metrics:
            self.metrics.incr("jobs.queued")
        
        return self.get_job(job_id)
    
    def dequeue(self, worker_id: str) -> Optional[QueuedJob]:
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM job_queue 
                WHERE status = 'pending' 
                ORDER BY priority DESC, created_at ASC 
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            
            if not row:
                return None
            
            job_id = row["job_id"]
            
            cursor.execute("""
                UPDATE job_queue 
                SET status = 'running', assigned_worker = ?, started_at = ?
                WHERE job_id = ? AND status = 'pending'
            """, (worker_id, now, job_id))
            
            if cursor.rowcount == 0:
                return None
            
            conn.commit()
        
        logger.info(f"Dequeued job {job_id} for worker {worker_id}")
        
        if self.metrics:
            self.metrics.incr("jobs.dispatched")
        
        return self.get_job(job_id)
    
    def mark_complete(self, job_id: str, result: Optional[Dict[str, Any]] = None):
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            conn.execute("""
                UPDATE job_queue 
                SET status = 'completed', completed_at = ?
                WHERE job_id = ?
            """, (now, job_id))
            conn.commit()
        
        logger.info(f"Job {job_id} marked complete")
        
        if self.metrics:
            self.metrics.incr("jobs.completed")
    
    def mark_failed(self, job_id: str, error: str):
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE job_queue 
                SET status = 'failed', error = ?, attempts = attempts + 1
                WHERE job_id = ?
            """, (error, job_id))
            conn.commit()
        
        logger.error(f"Job {job_id} failed: {error}")
        
        if self.metrics:
            self.metrics.incr("jobs.failed")
    
    def requeue_abandoned(self) -> int:
        now = _now_dt()
        cutoff = now - timedelta(seconds=ABANDONED_JOB_THRESHOLD_SECONDS)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE job_queue 
                SET status = 'pending', assigned_worker = NULL, started_at = NULL, attempts = attempts + 1
                WHERE status = 'assigned' 
                AND started_at < ?
            """, (cutoff_str,))
            
            requeued = cursor.rowcount
            conn.commit()
        
        if requeued > 0:
            logger.info(f"Requeued {requeued} abandoned jobs")
        
        if self.metrics:
            self.metrics.incr("jobs.requeued", float(requeued))
        
        return requeued
    
    def get_job(self, job_id: str) -> Optional[QueuedJob]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM job_queue WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            
            if row:
                return QueuedJob(
                    job_id=row["job_id"],
                    job_type=row["job_type"],
                    workspace_id=row["workspace_id"],
                    payload=json.loads(row["payload"]),
                    priority=row["priority"],
                    status=row["status"],
                    assigned_worker=row["assigned_worker"],
                    created_at=row["created_at"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    attempts=row["attempts"],
                    error=row["error"]
                )
        return None
    
    def get_queue_stats(self) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM job_queue 
                GROUP BY status
            """)
            
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
            
            cursor.execute("SELECT COUNT(*) as total FROM job_queue")
            total = cursor.fetchone()["total"]
            
            cursor.execute("""
                SELECT AVG(completed_at - started_at) as avg_duration
                FROM job_queue 
                WHERE status = 'completed' 
                AND completed_at IS NOT NULL 
                AND started_at IS NOT NULL
            """)
            avg_duration_row = cursor.fetchone()
            avg_duration = avg_duration_row["avg_duration"] if avg_duration_row else None
        
        stats = {
            "total": total,
            "by_status": status_counts,
            "pending": status_counts.get("pending", 0),
            "running": status_counts.get("running", 0),
            "assigned": status_counts.get("assigned", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "avg_duration_seconds": avg_duration
        }
        
        if self.metrics:
            self.metrics.gauge("jobs.queued", float(stats["pending"]))
        
        return stats
    
    def get_jobs_by_workspace(self, workspace_id: int, status: Optional[str] = None) -> List[QueuedJob]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            if status:
                cursor.execute("""
                    SELECT * FROM job_queue 
                    WHERE workspace_id = ? AND status = ?
                    ORDER BY created_at DESC
                """, (workspace_id, status))
            else:
                cursor.execute("""
                    SELECT * FROM job_queue 
                    WHERE workspace_id = ?
                    ORDER BY created_at DESC
                """, (workspace_id,))
            
            rows = cursor.fetchall()
        
        jobs = []
        for row in rows:
            jobs.append(QueuedJob(
                job_id=row["job_id"],
                job_type=row["job_type"],
                workspace_id=row["workspace_id"],
                payload=json.loads(row["payload"]),
                priority=row["priority"],
                status=row["status"],
                assigned_worker=row["assigned_worker"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                attempts=row["attempts"],
                error=row["error"]
            ))
        
        return jobs


class DeadLetterQueue:
    def __init__(self, db: Optional[JobQueueDB] = None, metrics: Optional[MetricsCollector] = None):
        self.db = db or JobQueueDB()
        self.metrics = metrics
    
    def add_to_dlq(
        self,
        original_job_id: str,
        job_type: str,
        workspace_id: int,
        payload: Dict[str, Any],
        error: str
    ) -> DeadLetterJob:
        dlq_id = f"dlq_{uuid4().hex[:12]}"
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            conn.execute("""
                INSERT INTO dead_letter_queue 
                (dlq_id, original_job_id, job_type, workspace_id, payload, error, retry_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (dlq_id, original_job_id, job_type, workspace_id, json.dumps(payload), error, now))
            
            conn.execute("""
                UPDATE job_queue 
                SET status = 'dead_letter'
                WHERE job_id = ?
            """, (original_job_id,))
            
            conn.commit()
        
        logger.warning(f"Job {original_job_id} moved to DLQ: {error}")
        
        if self.metrics:
            self.metrics.incr("jobs.dead_letter")
        
        return self.get_dlq_job(dlq_id)
    
    def get_retryable(self, max_retries: int = MAX_DLQ_RETRIES) -> List[DeadLetterJob]:
        now = _now_dt()
        cutoff = now - timedelta(seconds=DLQ_RETRY_DELAY_SECONDS)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM dead_letter_queue 
                WHERE retry_count < ?
                AND (last_retry_at IS NULL OR last_retry_at < ?)
                ORDER BY created_at ASC
            """, (max_retries, cutoff_str))
            
            rows = cursor.fetchall()
        
        jobs = []
        for row in rows:
            jobs.append(DeadLetterJob(
                dlq_id=row["dlq_id"],
                original_job_id=row["original_job_id"],
                job_type=row["job_type"],
                workspace_id=row["workspace_id"],
                payload=json.loads(row["payload"]),
                error=row["error"],
                retry_count=row["retry_count"],
                created_at=row["created_at"],
                last_retry_at=row["last_retry_at"]
            ))
        
        return jobs
    
    def retry_from_dlq(self, dlq_id: str) -> bool:
        now = _now_iso()
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE dead_letter_queue 
                SET retry_count = retry_count + 1, last_retry_at = ?
                WHERE dlq_id = ?
            """, (now, dlq_id))
            
            if cursor.rowcount == 0:
                return False
            
            cursor.execute("""
                SELECT original_job_id FROM dead_letter_queue 
                WHERE dlq_id = ?
            """, (dlq_id,))
            row = cursor.fetchone()
            
            if row:
                cursor.execute("""
                    UPDATE job_queue 
                    SET status = 'pending', attempts = 0, error = NULL
                    WHERE job_id = ?
                """, (row["original_job_id"],))
            
            conn.commit()
        
        logger.info(f"Retrying DLQ entry {dlq_id}")
        
        if self.metrics:
            self.metrics.incr("jobs.retry_from_dlq")
        
        return True
    
    def purge(self, dlq_id: str) -> bool:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM dead_letter_queue WHERE dlq_id = ?", (dlq_id,))
            
            deleted = cursor.rowcount > 0
            conn.commit()
        
        return deleted
    
    def get_dlq_job(self, dlq_id: str) -> Optional[DeadLetterJob]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM dead_letter_queue WHERE dlq_id = ?", (dlq_id,))
            row = cursor.fetchone()
            
            if row:
                return DeadLetterJob(
                    dlq_id=row["dlq_id"],
                    original_job_id=row["original_job_id"],
                    job_type=row["job_type"],
                    workspace_id=row["workspace_id"],
                    payload=json.loads(row["payload"]),
                    error=row["error"],
                    retry_count=row["retry_count"],
                    created_at=row["created_at"],
                    last_retry_at=row["last_retry_at"]
                )
        return None
    
    def get_dlq_stats(self) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as total FROM dead_letter_queue")
            total = cursor.fetchone()["total"]
            
            cursor.execute("""
                SELECT COUNT(*) as retryable 
                FROM dead_letter_queue 
                WHERE retry_count < ?
            """, (MAX_DLQ_RETRIES,))
            retryable = cursor.fetchone()["retryable"]
            
            cursor.execute("SELECT SUM(retry_count) as total_retries FROM dead_letter_queue")
            total_retries = cursor.fetchone()["total_retries"] or 0
        
        return {
            "total": total,
            "retryable": retryable,
            "total_retries": total_retries
        }


_global_pool: Optional[WorkerPool] = None
_global_queue: Optional[JobQueue] = None
_global_dlq: Optional[DeadLetterQueue] = None
_lock = threading.Lock()


def get_worker_pool() -> WorkerPool:
    global _global_pool
    if _global_pool is None:
        with _lock:
            if _global_pool is None:
                _global_pool = WorkerPool()
    return _global_pool


def get_job_queue() -> JobQueue:
    global _global_queue
    if _global_queue is None:
        with _lock:
            if _global_queue is None:
                _global_queue = JobQueue()
    return _global_queue


def get_dead_letter_queue() -> DeadLetterQueue:
    global _global_dlq
    if _global_dlq is None:
        with _lock:
            if _global_dlq is None:
                _global_dlq = DeadLetterQueue()
    return _global_dlq
