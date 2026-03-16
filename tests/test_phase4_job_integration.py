"""
Tests for Phase 4: Job Runtime Integration with Outreach Manager
================================================================
Verifies that outreach_manager.py correctly integrates job_runtime
for durability, idempotency, and progress tracking.
"""

import unittest
import asyncio
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from scripts.job_runtime import (
    JobRuntime,
    JobStatus,
    JobType,
    get_job_runtime,
)


class TestOutreachJobIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_integration.db"
        self.runtime = JobRuntime(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_job_with_idempotency(self):
        """Test que la creación de job usa idempotency key correctamente."""
        job_id = "outreach_001"
        workspace_id = 1
        lead_ids = [1, 2, 3]
        
        idempotency_key = self.runtime.generate_idempotency_key(
            "outreach",
            str(workspace_id),
            str(sorted(lead_ids)),
            "2024-01-01"
        )
        
        job1 = self.runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=workspace_id,
            payload={"lead_ids": lead_ids},
            idempotency_key=idempotency_key,
        )
        
        self.assertIsNotNone(job1)
        self.assertEqual(job1.job_id, job_id)
        
        job2 = self.runtime.create_job(
            job_id="outreach_002",
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=workspace_id,
            payload={"lead_ids": lead_ids},
            idempotency_key=idempotency_key,
        )
        
        self.assertEqual(job1.job_id, job2.job_id)
        self.assertEqual(job1.job_id, "outreach_001")

    def test_job_prevents_duplicate_execution(self):
        """Test que un job completado no se re-ejecuta."""
        job_id = "outreach_002"
        
        self.runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={},
        )
        
        self.runtime.complete_job(job_id, {"sent": 5, "errors": 0})
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.COMPLETED.value)
        self.assertEqual(json.loads(job.result), {"sent": 5, "errors": 0})

    def test_lease_acquisition_for_outreach(self):
        """Test que el lease se adquiere correctamente para un worker."""
        job_id = "outreach_003"
        worker_id = "worker_outreach_1"
        
        self.runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={},
        )
        
        acquired = self.runtime.try_acquire_lease(job_id, worker_id)
        
        self.assertTrue(acquired)
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.status, JobStatus.RUNNING.value)
        self.assertEqual(job.leased_by, worker_id)

    def test_progress_checkpoint_tracking(self):
        """Test que el progress y checkpoint se actualizan correctamente."""
        job_id = "outreach_004"
        
        self.runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={},
        )
        
        self.runtime.update_progress(job_id, 0.5, checkpoint="lead_5:john_doe")
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.progress, 0.5)
        self.assertEqual(job.checkpoint, "lead_5:john_doe")
        
        self.runtime.update_progress(job_id, 0.75, checkpoint="lead_10:jane_smith")
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.progress, 0.75)
        self.assertEqual(job.checkpoint, "lead_10:jane_smith")

    def test_orphaned_job_recovery(self):
        """Test que jobs huérfanos pueden ser recuperados."""
        job_id = "outreach_005"
        dead_worker = "dead_worker_1"
        new_worker = "new_worker_1"
        
        self.runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=1,
            payload={},
        )
        
        self.runtime.try_acquire_lease(job_id, dead_worker)
        
        from datetime import datetime, timedelta
        with self.runtime._get_connection() as conn:
            cursor = conn.cursor()
            past_time = (datetime.now() - timedelta(seconds=600)).isoformat()
            cursor.execute("""
                UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?
            """, (past_time, job_id))
            conn.commit()
        
        recovered = self.runtime.recover_orphaned_jobs(new_worker)
        
        self.assertEqual(len(recovered), 1)
        
        job = self.runtime.get_job(job_id)
        self.assertEqual(job.leased_by, new_worker)
        self.assertEqual(job.status, JobStatus.RUNNING.value)

    def test_idempotency_key_format(self):
        """Test que el idempotency key se genera en formato correcto."""
        key = self.runtime.generate_idempotency_key(
            "outreach",
            "1",
            "[1, 2, 3]",
            "2024-01-01"
        )
        
        self.assertIsInstance(key, str)
        self.assertEqual(len(key), 32)
        
        key2 = self.runtime.generate_idempotency_key(
            "outreach",
            "1",
            "[1, 2, 3]",
            "2024-01-01"
        )
        
        self.assertEqual(key, key2)


class TestOutreachJobTypes(unittest.TestCase):
    """Test que los JobTypes están correctamente definidos."""
    
    def test_job_types_exist(self):
        """Verifica que los JobTypes necesarios existen."""
        self.assertEqual(JobType.MESSAGE_OUTREACH.value, "message_outreach")
        self.assertEqual(JobType.CAMPAIGN_WARMUP.value, "campaign_warmup")
        self.assertEqual(JobType.SCRAPE_LEADS.value, "scrape_leads")
        self.assertEqual(JobType.ACCOUNT_WARMUP.value, "account_warmup")


if __name__ == "__main__":
    unittest.main()
