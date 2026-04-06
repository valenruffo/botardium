import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import gc
import asyncio

from scripts import main
from scripts import lead_scraper
from scripts.job_runtime import JobRuntime, JobStatus, JobType


class Phase4RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self):
        main.MESSAGE_JOB_STORE.clear()
        main.OUTREACH_TASKS.clear()

    def tearDown(self):
        main.MESSAGE_JOB_STORE.clear()
        main.OUTREACH_TASKS.clear()

    def test_apply_outreach_progress_update_removes_reserved_lead_from_pending(self):
        job = {
            "id": "job-1",
            "workspace_id": 1,
            "kind": "outreach",
            "status": "running",
            "progress": 0,
            "prompt": "outreach-run",
            "created_at": 1,
            "current_action": "init",
            "total": 3,
            "processed": 0,
            "metrics": {"sent": 0, "errors": 0},
            "lead_ids_pending": [10, 11, 12],
            "limit": {"used": 4, "cap": 20, "pause_window_seconds": 60, "percent": 20},
        }

        main._apply_outreach_progress_update(
            job,
            {
                "status": "running",
                "progress": 33,
                "current_action": "Reserva durable creada para @lead11",
                "lead_id": 11,
                "drop_from_pending": True,
                "checkpoint": "reserved:11:lead11",
                "metrics": {"sent": 1},
            },
            initial_limit_used=4,
        )

        self.assertEqual(job["lead_ids_pending"], [10, 12])
        self.assertEqual(job["checkpoint"], "reserved:11:lead11")
        self.assertEqual(job["limit"]["used"], 5)

    def test_recover_durable_outreach_jobs_requeues_running_job(self):
        job = {
            "id": "job-recover",
            "workspace_id": 1,
            "kind": "outreach",
            "status": "running",
            "progress": 50,
            "prompt": "outreach-run",
            "created_at": 1,
            "current_action": "Procesando",
            "total": 4,
            "processed": 2,
            "metrics": {"sent": 1, "errors": 0},
            "lead_ids_pending": [30, 31],
        }
        main.MESSAGE_JOB_STORE[job["id"]] = job

        with patch("scripts.main._schedule_outreach_resume", return_value=True) as schedule_resume:
            resumed = main._recover_durable_outreach_jobs()

        self.assertEqual(resumed, ["job-recover"])
        self.assertEqual(job["status"], "queued")
        self.assertIn("ultimo checkpoint durable", job["current_action"])
        schedule_resume.assert_called_once()


class Phase4JobRuntimeReuseTests(unittest.TestCase):
    def test_create_job_returns_existing_job_id_record(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime = JobRuntime(db_path=Path(tmp_dir) / "jobs.db")
            first = runtime.create_job(
                job_id="same-job",
                job_type=JobType.MESSAGE_OUTREACH.value,
                workspace_id=1,
                payload={"lead_ids": [1, 2]},
                idempotency_key="first-key",
            )

            second = runtime.create_job(
                job_id="same-job",
                job_type=JobType.MESSAGE_OUTREACH.value,
                workspace_id=1,
                payload={"lead_ids": [2]},
                idempotency_key="second-key",
            )

            del runtime
            gc.collect()

        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(second.status, JobStatus.PENDING.value)

    def test_create_campaign_job_reuses_active_runtime_record(self):
        campaign = {
            "id": "campaign-1",
            "workspace_id": 1,
            "username": "demo_user",
            "warmup_minutes": 12,
            "execution_mode": "real",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime = JobRuntime(db_path=Path(tmp_dir) / "jobs.db")
            with patch("scripts.main.get_job_runtime", return_value=runtime), patch("scripts.main._persist_campaign"):
                first = main._create_campaign_job(campaign, "scrape")
                second = main._create_campaign_job(campaign, "scrape")
            del runtime
            gc.collect()

        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(campaign["scrape_job_id"], first.job_id)

    def test_recover_durable_campaign_jobs_requeues_running_scrape_job(self):
        campaign = {
            "id": "campaign-recover",
            "workspace_id": 1,
            "username": "demo_user",
            "status": "paused",
            "progress": 40,
            "current_action": "idle",
            "logs": [],
            "scrape_job_id": None,
            "warmup_job_id": None,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime = JobRuntime(db_path=Path(tmp_dir) / "jobs.db")
            job = runtime.create_job(
                job_id="scrape-job-1",
                job_type=JobType.SCRAPE_LEADS.value,
                workspace_id=1,
                payload={"campaign_id": campaign["id"], "action": "scrape"},
            )
            runtime.try_acquire_lease(job.job_id, "dead-worker")
            runtime.update_progress(job.job_id, 0.4, checkpoint="scrape:source:1:hashtag:test:4/10")
            campaign["scrape_job_id"] = job.job_id
            main.CAMPAIGN_STORE[campaign["id"]] = campaign

            try:
                with patch("scripts.main.get_job_runtime", return_value=runtime), patch("scripts.main._schedule_campaign_job", return_value=True):
                    resumed = main._recover_durable_campaign_jobs()
            finally:
                main.CAMPAIGN_STORE.clear()
                del runtime
                gc.collect()

        self.assertEqual(resumed, [job.job_id])
        self.assertEqual(campaign["status"], "running")
        self.assertIn("Reanudando scraping durable", campaign["current_action"])
        self.assertIn("scrape:source:1:hashtag:test:4/10", campaign["current_action"])


class Phase4ScraperDurabilityTests(unittest.TestCase):
    def test_enqueue_scraper_job_deduplicates_same_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime = JobRuntime(db_path=Path(tmp_dir) / "jobs.db")
            first = lead_scraper.enqueue_scraper_job("hashtag", "marketing", 25, username="demo", workspace_id=7, runtime=runtime)
            second = lead_scraper.enqueue_scraper_job("hashtag", "marketing", 25, username="demo", workspace_id=7, runtime=runtime)
            del runtime
            gc.collect()

        self.assertEqual(first.job_id, second.job_id)

    def test_resume_scraper_job_uses_persisted_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime = JobRuntime(db_path=Path(tmp_dir) / "jobs.db")
            job = runtime.create_job(
                job_id="scrape-resume-1",
                job_type=JobType.SCRAPE_LEADS.value,
                workspace_id=9,
                payload={
                    "target_type": "followers",
                    "query": "acme",
                    "limit": 15,
                    "username": "demo",
                    "filters": {"strict": True},
                    "campaign_id": "campaign-9",
                },
            )
            mock_run = AsyncMock(return_value={"accepted_count": 0})
            with patch("scripts.lead_scraper.run_scraper", mock_run):
                result = asyncio.run(lead_scraper.resume_scraper_job(job.job_id, runtime=runtime))
            del runtime
            gc.collect()

        self.assertEqual(result, {"accepted_count": 0})
        mock_run.assert_awaited_once_with(
            "followers",
            "acme",
            15,
            username="demo",
            filters={"strict": True},
            campaign_id="campaign-9",
            job_id="scrape-resume-1",
            workspace_id=9,
        )
