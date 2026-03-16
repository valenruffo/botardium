"""
Tests for Job Runtime (Phase 4)
================================
Covers job creation, lease acquisition, idempotency, recovery, and progress tracking.
"""

import unittest
import tempfile
import os
import threading
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from scripts.job_runtime import (
    JobRuntime,
    JobStatus,
    JobType,
    JobRecord,
    get_job_runtime,
    managed_job,
    JOB_LEASE_TIMEOUT_SECONDS,
)


class TestJobRuntime(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_jobs.db"
        self.runtime = JobRuntime(db_path=self.db_path)
        self.worker_id = "test_worker_1"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_job(self):
        job_id = "test_job_001"
        job = self.runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={"lead_ids": [1, 2, 3], "message": "Hello"},
        )
        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, job_id)
        self.assertEqual(job.status, JobStatus.PENDING.value)
        self.assertEqual(job.progress, 0.0)

    def test_get_job(self):
        job_id = "test_job_002"
        self.runtime.create_job(job_id, JobType.SCRAPE_LEADS.value, 1, {"hashtag": "#test"})
        retrieved = self.runtime.get_job(job_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.job_id, job_id)

    def test_idempotency_key_prevents_duplicate(self):
        idempotency_key = self.runtime.generate_idempotency_key("outreach", 1, "2024-01-01")
        
        job1 = self.runtime.create_job(
            job_id="job_1",
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={"test": "data"},
            idempotency_key=idempotency_key,
        )
        
        job2 = self.runtime.create_job(
            job_id="job_2",
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={"test": "different"},
            idempotency_key=idempotency_key,
        )
        
        self.assertEqual(job1.job_id, job2.job_id)
        self.assertEqual(job1.job_id, "job_1")

    def test_try_acquire_lease(self):
        job_id = "test_job_003"
        self.runtime.create_job(job_id, JobType.CAMPAIGN_WARMUP.value, 1, {})
        
        acquired = self.runtime.try_acquire_lease(job_id, self.worker_id)
        self.assertTrue(acquired)
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.RUNNING.value)
        self.assertEqual(job.leased_by, self.worker_id)

    def test_lease_blocks_other_worker(self):
        job_id = "test_job_004"
        self.runtime.create_job(job_id, JobType.ACCOUNT_WARMUP.value, 1, {})
        
        self.runtime.try_acquire_lease(job_id, "worker_a")
        acquired_by_b = self.runtime.try_acquire_lease(job_id, "worker_b")
        
        self.assertFalse(acquired_by_b)

    def test_release_lease(self):
        job_id = "test_job_005"
        self.runtime.create_job(job_id, JobType.MESSAGE_OUTREACH.value, 1, {})
        
        self.runtime.try_acquire_lease(job_id, self.worker_id)
        self.runtime.release_lease(job_id, self.worker_id)
        
        job = self.runtime.get_job(job_id)
        self.assertIsNone(job.leased_by)
        self.assertIsNone(job.lease_expires_at)

    def test_update_progress(self):
        job_id = "test_job_006"
        self.runtime.create_job(job_id, JobType.SCRAPE_LEADS.value, 1, {})
        
        self.runtime.update_progress(job_id, 0.5, checkpoint="page_10")
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.progress, 0.5)
        self.assertEqual(job.checkpoint, "page_10")

    def test_complete_job(self):
        job_id = "test_job_007"
        self.runtime.create_job(job_id, JobType.MESSAGE_OUTREACH.value, 1, {})
        
        self.runtime.complete_job(job_id, result={"sent": 5, "failed": 0})
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED.value)
        self.assertEqual(job.progress, 1.0)
        self.assertIsNotNone(job.completed_at)

    def test_fail_job(self):
        job_id = "test_job_008"
        self.runtime.create_job(job_id, JobType.SCRAPE_LEADS.value, 1, {})
        
        self.runtime.fail_job(job_id, "Instagram rate limit exceeded")
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED.value)
        self.assertEqual(job.error, "Instagram rate limit exceeded")

    def test_cancel_job(self):
        job_id = "test_job_009"
        self.runtime.create_job(job_id, JobType.CAMPAIGN_WARMUP.value, 1, {})
        
        self.runtime.cancel_job(job_id)
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.CANCELLED.value)

    def test_list_jobs_by_status(self):
        workspace_id = 1
        self.runtime.create_job("job_a", JobType.MESSAGE_OUTREACH.value, workspace_id, {})
        self.runtime.create_job("job_b", JobType.MESSAGE_OUTREACH.value, workspace_id, {})
        self.runtime.create_job("job_c", JobType.MESSAGE_OUTREACH.value, workspace_id, {})
        
        self.runtime.complete_job("job_a")
        self.runtime.fail_job("job_c", "test failure reason")
        
        pending = self.runtime.list_jobs(workspace_id, status=JobStatus.PENDING.value)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].job_id, "job_b")
        
        completed = self.runtime.list_jobs(workspace_id, status=JobStatus.COMPLETED.value)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].job_id, "job_a")

    def test_recover_orphaned_jobs(self):
        job_id = "test_job_010"
        self.runtime.create_job(job_id, JobType.SCRAPE_LEADS.value, 1, {})
        
        with self.runtime._get_connection() as conn:
            cursor = conn.cursor()
            past_time = (datetime.now() - timedelta(seconds=JOB_LEASE_TIMEOUT_SECONDS * 2)).isoformat()
            cursor.execute("""
                UPDATE jobs SET status = ?, lease_expires_at = ?, leased_by = ?
                WHERE job_id = ?
            """, (JobStatus.RUNNING.value, past_time, "dead_worker", job_id))
            conn.commit()
        
        recovered = self.runtime.recover_orphaned_jobs("new_worker")
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].job_id, job_id)
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.leased_by, "new_worker")

    def test_managed_job_context(self):
        job_id = "test_job_011"
        self.runtime.create_job(job_id, JobType.MESSAGE_OUTREACH.value, 1, {})
        
        with managed_job(job_id, "managed_worker", self.runtime) as ctx:
            ctx.update_progress(0.75, checkpoint="lead_50")
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.progress, 0.75)
        self.assertEqual(job.checkpoint, "lead_50")

    def test_managed_job_raises_on_failure(self):
        job_id = "test_job_012"
        self.runtime.create_job(job_id, JobType.SCRAPE_LEADS.value, 1, {})
        
        with self.assertRaises(ValueError):
            with managed_job(job_id, "error_worker", self.runtime) as ctx:
                raise ValueError("Test error")
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED.value)
        self.assertEqual(job.error, "Test error")

    def test_generate_idempotency_key_deterministic(self):
        key1 = self.runtime.generate_idempotency_key("outreach", 123, "test_message")
        key2 = self.runtime.generate_idempotency_key("outreach", 123, "test_message")
        self.assertEqual(key1, key2)
        
        key3 = self.runtime.generate_idempotency_key("outreach", 123, "different_message")
        self.assertNotEqual(key1, key3)

    def test_concurrent_lease_acquisition(self):
        job_id = "test_job_013"
        self.runtime.create_job(job_id, JobType.CAMPAIGN_WARMUP.value, 1, {})
        
        results = []
        
        def try_acquire(worker):
            r = self.runtime.try_acquire_lease(job_id, worker)
            results.append((worker, r))
        
        t1 = threading.Thread(target=try_acquire, args=("worker_a",))
        t2 = threading.Thread(target=try_acquire, args=("worker_b",))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        successes = [r for _, r in results]
        self.assertEqual(successes.count(True), 1)

    def test_cleanup_old_jobs(self):
        workspace_id = 1
        
        with self.runtime._get_connection() as conn:
            cursor = conn.cursor()
            old_time = (datetime.now() - timedelta(days=10)).isoformat()
            old_created = (datetime.now() - timedelta(days=10)).isoformat()
            
            for i in range(3):
                cursor.execute("""
                    INSERT INTO jobs (job_id, job_type, workspace_id, status, payload, completed_at, created_at)
                    VALUES (?, ?, ?, ?, '{}', ?, ?)
                """, (f"old_job_{i}", JobType.MESSAGE_OUTREACH.value, workspace_id, JobStatus.COMPLETED.value, old_time, old_created))
            
            cursor.execute("""
                INSERT INTO jobs (job_id, job_type, workspace_id, status, payload, completed_at, created_at)
                VALUES (?, ?, ?, ?, '{}', ?, ?)
            """, (f"recent_job", JobType.MESSAGE_OUTREACH.value, workspace_id, JobStatus.COMPLETED.value, datetime.now().isoformat(), datetime.now().isoformat()))
            conn.commit()
        
        deleted = self.runtime.cleanup_old_jobs(max_age_days=7)
        
        remaining = self.runtime.list_jobs(workspace_id, status=JobStatus.COMPLETED.value)
        self.assertEqual(deleted, 3)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].job_id, "recent_job")


class TestJobRuntimeSingleton(unittest.TestCase):
    def test_singleton_returns_same_instance(self):
        runtime1 = get_job_runtime()
        runtime2 = get_job_runtime()
        self.assertIs(runtime1, runtime2)


if __name__ == "__main__":
    unittest.main()
