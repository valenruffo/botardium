"""
Tests for Phase 7: Job Queue Distribution System
================================================
Verifies worker pool, job queue, dead letter queue, and metrics integration.
"""

import unittest
import os
import sys
import json
import tempfile
import shutil
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.job_queue import (
    JobQueueDB,
    WorkerPool,
    JobQueue,
    DeadLetterQueue,
    QueueStatus,
    get_worker_pool,
    get_job_queue,
    get_dead_letter_queue,
    WORKER_HEARTBEAT_TIMEOUT_SECONDS,
    MAX_DLQ_RETRIES,
    DLQ_RETRY_DELAY_SECONDS,
)

from scripts.observabilidad.metrics_collector import MetricsCollector


class TestWorkerRegistration(unittest.TestCase):
    """Test worker registration and management."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_job_queue.db"
        self.db = JobQueueDB(self.db_path)
        self.metrics = MetricsCollector(str(Path(self.temp_dir) / "metrics.db"))
        self.pool = WorkerPool(self.db, self.metrics)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_worker_registration(self):
        """Worker can be registered successfully."""
        worker = self.pool.register_worker("worker-1", "scraper", ["instagram", "leads"])
        
        self.assertEqual(worker.worker_id, "worker-1")
        self.assertEqual(worker.worker_type, "scraper")
        self.assertEqual(worker.capabilities, ["instagram", "leads"])
        self.assertEqual(worker.status, "idle")
        self.assertEqual(worker.job_count, 0)
    
    def test_worker_registration_duplicate(self):
        """Re-registering worker updates existing record."""
        self.pool.register_worker("worker-1", "scraper", ["instagram"])
        worker = self.pool.register_worker("worker-1", "processor", ["leads"])
        
        self.assertEqual(worker.worker_type, "processor")
        self.assertEqual(worker.capabilities, ["leads"])
    
    def test_get_available_workers(self):
        """Can retrieve available workers."""
        self.pool.register_worker("worker-1", "scraper", ["instagram"])
        self.pool.register_worker("worker-2", "scraper", ["instagram"])
        
        workers = self.pool.get_available_workers()
        self.assertEqual(len(workers), 2)
    
    def test_get_available_workers_by_type(self):
        """Can filter workers by type."""
        self.pool.register_worker("worker-1", "scraper", ["instagram"])
        self.pool.register_worker("worker-2", "processor", ["leads"])
        
        scrapers = self.pool.get_available_workers("scraper")
        processors = self.pool.get_available_workers("processor")
        
        self.assertEqual(len(scrapers), 1)
        self.assertEqual(scrapers[0].worker_id, "worker-1")
        self.assertEqual(len(processors), 1)
        self.assertEqual(processors[0].worker_id, "worker-2")


class TestHeartbeat(unittest.TestCase):
    """Test worker heartbeat functionality."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_job_queue.db"
        self.db = JobQueueDB(self.db_path)
        self.metrics = MetricsCollector(str(Path(self.temp_dir) / "metrics.db"))
        self.pool = WorkerPool(self.db, self.metrics)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_heartbeat_updates_timestamp(self):
        """Heartbeat updates worker last_heartbeat."""
        self.pool.register_worker("worker-1", "scraper")
        
        time.sleep(0.1)
        result = self.pool.heartbeat("worker-1")
        
        self.assertTrue(result)
        worker = self.pool.get_worker("worker-1")
        self.assertIsNotNone(worker)
    
    def test_heartbeat_unknown_worker(self):
        """Heartbeat returns False for unknown worker."""
        result = self.pool.heartbeat("unknown-worker")
        self.assertFalse(result)
    
    def test_heartbeat_releases_completed_job(self):
        """Heartbeat releases worker when job is complete."""
        self.pool.register_worker("worker-1", "scraper")
        
        worker = self.pool.get_worker("worker-1")
        self.assertEqual(worker.status, "idle")
        
        self.pool.heartbeat("worker-1")
        
        worker = self.pool.get_worker("worker-1")
        self.assertEqual(worker.status, "idle")
    
    def test_cleanup_stale_workers(self):
        """Can cleanup workers that have not sent heartbeat."""
        self.pool.register_worker("worker-1", "scraper")
        
        deleted = self.pool.cleanup_stale_workers(max_age_seconds=1)
        
        self.assertGreaterEqual(deleted, 0)


class TestJobEnqueueAndDispatch(unittest.TestCase):
    """Test job enqueueing and dispatching."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_job_queue.db"
        self.db = JobQueueDB(self.db_path)
        self.metrics = MetricsCollector(str(Path(self.temp_dir) / "metrics.db"))
        self.pool = WorkerPool(self.db, self.metrics)
        self.queue = JobQueue(self.db, self.metrics)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_job_enqueue(self):
        """Can enqueue a job."""
        job = self.queue.enqueue(
            job_id="job-1",
            job_type="scrape_leads",
            workspace_id=1,
            payload={"query": "test"},
            priority=5
        )
        
        self.assertEqual(job.job_id, "job-1")
        self.assertEqual(job.job_type, "scrape_leads")
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.priority, 5)
    
    def test_job_enqueue_increments_metric(self):
        """Enqueueing job increments metrics."""
        initial_count = self.metrics.get_stats("jobs.queued")["count"]
        
        self.queue.enqueue(
            job_id="job-1",
            job_type="scrape_leads",
            workspace_id=1,
            payload={}
        )
        
        final_count = self.metrics.get_stats("jobs.queued")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_job_dequeue(self):
        """Can dequeue a job."""
        self.pool.register_worker("worker-1", "scraper")
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        
        job = self.queue.dequeue("worker-1")
        
        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, "job-1")
        self.assertEqual(job.status, "running")
    
    def test_job_dispatch_increments_metric(self):
        """Dispatching job increments metrics."""
        self.pool.register_worker("worker-1", "scraper")
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        
        initial_count = self.metrics.get_stats("jobs.dispatched")["count"]
        
        self.queue.dequeue("worker-1")
        
        final_count = self.metrics.get_stats("jobs.dispatched")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_job_priority_ordering(self):
        """Jobs are dequeued by priority."""
        self.pool.register_worker("worker-1", "scraper")
        
        self.queue.enqueue("job-low", "scrape_leads", 1, {}, priority=1)
        self.queue.enqueue("job-high", "scrape_leads", 1, {}, priority=10)
        
        job = self.queue.dequeue("worker-1")
        
        self.assertEqual(job.job_id, "job-high")
    
    def test_mark_complete(self):
        """Can mark job as complete."""
        self.pool.register_worker("worker-1", "scraper")
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.queue.dequeue("worker-1")
        
        self.queue.mark_complete("job-1")
        
        job = self.queue.get_job("job-1")
        self.assertEqual(job.status, "completed")
    
    def test_mark_failed(self):
        """Can mark job as failed."""
        self.pool.register_worker("worker-1", "scraper")
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.queue.dequeue("worker-1")
        
        self.queue.mark_failed("job-1", "Test error")
        
        job = self.queue.get_job("job-1")
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "Test error")
    
    def test_assign_job_to_worker(self):
        """Can assign job to worker."""
        self.pool.register_worker("worker-1", "scraper")
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        
        result = self.pool.assign_job("worker-1", "job-1")
        
        self.assertTrue(result)
        worker = self.pool.get_worker("worker-1")
        self.assertEqual(worker.current_job_id, "job-1")
    
    def test_release_worker(self):
        """Can release worker after job."""
        self.pool.register_worker("worker-1", "scraper")
        
        self.pool.release_worker("worker-1")
        
        worker = self.pool.get_worker("worker-1")
        self.assertEqual(worker.status, "idle")
    
    def test_queue_stats(self):
        """Can get queue statistics."""
        self.pool.register_worker("worker-1", "scraper")
        
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.queue.enqueue("job-2", "scrape_leads", 1, {})
        self.queue.dequeue("worker-1")
        
        stats = self.queue.get_queue_stats()
        
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["running"], 1)


class TestDeadLetterQueue(unittest.TestCase):
    """Test dead letter queue functionality."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_job_queue.db"
        self.db = JobQueueDB(self.db_path)
        self.metrics = MetricsCollector(str(Path(self.temp_dir) / "metrics.db"))
        self.queue = JobQueue(self.db, self.metrics)
        self.dlq = DeadLetterQueue(self.db, self.metrics)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_add_to_dlq(self):
        """Can add failed job to DLQ."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {"test": True})
        
        dlq_job = self.dlq.add_to_dlq(
            original_job_id="job-1",
            job_type="scrape_leads",
            workspace_id=1,
            payload={"test": True},
            error="Permanent failure"
        )
        
        self.assertIsNotNone(dlq_job)
        self.assertEqual(dlq_job.original_job_id, "job-1")
        self.assertEqual(dlq_job.retry_count, 0)
        self.assertEqual(dlq_job.error, "Permanent failure")
    
    def test_add_to_dlq_updates_job_status(self):
        """Adding to DLQ updates job status."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        job = self.queue.get_job("job-1")
        self.assertEqual(job.status, "dead_letter")
    
    def test_get_retryable(self):
        """Can get retryable DLQ jobs."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        retryable = self.dlq.get_retryable()
        
        self.assertEqual(len(retryable), 1)
    
    def test_retry_from_dlq(self):
        """Can retry job from DLQ."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        dlq_job = self.dlq.get_retryable()[0]
        result = self.dlq.retry_from_dlq(dlq_job.dlq_id)
        
        self.assertTrue(result)
        
        job = self.queue.get_job("job-1")
        self.assertEqual(job.status, "pending")
    
    def test_retry_increments_count(self):
        """Retrying increments retry count."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        dlq_job = self.dlq.get_retryable()[0]
        self.dlq.retry_from_dlq(dlq_job.dlq_id)
        
        dlq_job = self.dlq.get_dlq_job(dlq_job.dlq_id)
        self.assertEqual(dlq_job.retry_count, 1)
    
    def test_purge_dlq(self):
        """Can purge DLQ entry."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        dlq_job = self.dlq.get_retryable()[0]
        result = self.dlq.purge(dlq_job.dlq_id)
        
        self.assertTrue(result)
        
        purged_job = self.dlq.get_dlq_job(dlq_job.dlq_id)
        self.assertIsNone(purged_job)
    
    def test_dlq_stats(self):
        """Can get DLQ statistics."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        stats = self.dlq.get_dlq_stats()
        
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["retryable"], 1)


class TestMetricsIntegration(unittest.TestCase):
    """Test metrics integration with job queue."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_job_queue.db"
        self.metrics_db_path = str(Path(self.temp_dir) / "metrics.db")
        self.db = JobQueueDB(self.db_path)
        self.metrics = MetricsCollector(self.metrics_db_path)
        self.pool = WorkerPool(self.db, self.metrics)
        self.queue = JobQueue(self.db, self.metrics)
        self.dlq = DeadLetterQueue(self.db, self.metrics)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_workers_registered_metric(self):
        """Worker registration emits metric."""
        initial_count = self.metrics.get_stats("workers.registered")["count"]
        
        self.pool.register_worker("worker-1", "scraper")
        
        final_count = self.metrics.get_stats("workers.registered")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_heartbeat_metric(self):
        """Heartbeat emits metric."""
        self.pool.register_worker("worker-1", "scraper")
        
        initial_count = self.metrics.get_stats("workers.heartbeat")["count"]
        
        self.pool.heartbeat("worker-1")
        
        final_count = self.metrics.get_stats("workers.heartbeat")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_jobs_queued_metric(self):
        """Job enqueue emits metric."""
        initial_count = self.metrics.get_stats("jobs.queued")["count"]
        
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        
        final_count = self.metrics.get_stats("jobs.queued")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_jobs_dispatched_metric(self):
        """Job dispatch emits metric."""
        self.pool.register_worker("worker-1", "scraper")
        
        initial_count = self.metrics.get_stats("jobs.dispatched")["count"]
        
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.queue.dequeue("worker-1")
        
        final_count = self.metrics.get_stats("jobs.dispatched")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_workers_active_gauge(self):
        """Workers active gauge is updated."""
        self.pool.register_worker("worker-1", "scraper")
        self.pool.register_worker("worker-2", "scraper")
        
        gauges = self.metrics.get_all_gauges()
        
        self.assertIn("workers.active", gauges)
    
    def test_jobs_completed_metric(self):
        """Job completion emits metric."""
        self.pool.register_worker("worker-1", "scraper")
        
        initial_count = self.metrics.get_stats("jobs.completed")["count"]
        
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.queue.dequeue("worker-1")
        self.queue.mark_complete("job-1")
        
        final_count = self.metrics.get_stats("jobs.completed")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_jobs_failed_metric(self):
        """Job failure emits metric."""
        self.pool.register_worker("worker-1", "scraper")
        
        initial_count = self.metrics.get_stats("jobs.failed")["count"]
        
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        self.queue.dequeue("worker-1")
        self.queue.mark_failed("job-1", "Error")
        
        final_count = self.metrics.get_stats("jobs.failed")["count"]
        self.assertEqual(final_count, initial_count + 1)
    
    def test_dead_letter_metric(self):
        """DLQ addition emits metric."""
        self.queue.enqueue("job-1", "scrape_leads", 1, {})
        
        initial_count = self.metrics.get_stats("jobs.dead_letter")["count"]
        
        self.dlq.add_to_dlq("job-1", "scrape_leads", 1, {}, "Error")
        
        final_count = self.metrics.get_stats("jobs.dead_letter")["count"]
        self.assertEqual(final_count, initial_count + 1)


class TestGlobalInstances(unittest.TestCase):
    """Test global singleton instances."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_get_worker_pool_returns_instance(self):
        """get_worker_pool returns a WorkerPool instance."""
        pool = get_worker_pool()
        self.assertIsInstance(pool, WorkerPool)
    
    def test_get_job_queue_returns_instance(self):
        """get_job_queue returns a JobQueue instance."""
        queue = get_job_queue()
        self.assertIsInstance(queue, JobQueue)
    
    def test_get_dead_letter_queue_returns_instance(self):
        """get_dead_letter_queue returns a DeadLetterQueue instance."""
        dlq = get_dead_letter_queue()
        self.assertIsInstance(dlq, DeadLetterQueue)


if __name__ == "__main__":
    unittest.main()
