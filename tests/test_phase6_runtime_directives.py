import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock, patch

from scripts import lead_scraper, outreach_manager


class TestPhase6RuntimeDirectives(unittest.TestCase):
    def test_scraper_humanized_wait_uses_randomized_range(self):
        async def run_case():
            with patch("scripts.lead_scraper.random.uniform", return_value=2.75) as uniform_mock, patch("scripts.lead_scraper.asyncio.sleep", new=AsyncMock()) as sleep_mock:
                delay = await lead_scraper._humanized_wait(2.0, 4.0, "test scraper wait")
            self.assertEqual(delay, 2.75)
            uniform_mock.assert_called_once_with(2.0, 4.0)
            sleep_mock.assert_awaited_once_with(2.75)

        asyncio.run(run_case())

    def test_outreach_humanized_wait_uses_randomized_range(self):
        async def run_case():
            with patch("scripts.outreach_manager.random.uniform", return_value=1.25) as uniform_mock, patch("scripts.outreach_manager.asyncio.sleep", new=AsyncMock()) as sleep_mock:
                delay = await outreach_manager._humanized_wait(1.0, 2.0, "test outreach wait")
            self.assertEqual(delay, 1.25)
            uniform_mock.assert_called_once_with(1.0, 2.0)
            sleep_mock.assert_awaited_once_with(1.25)

        asyncio.run(run_case())

    def test_scraper_capture_runtime_evidence_writes_metadata_and_screenshot(self):
        async def run_case(tmp_dir: str):
            page = AsyncMock()
            type(page).url = PropertyMock(return_value="https://www.instagram.com/test/")
            page.title.return_value = "Instagram"
            page.screenshot.return_value = None

            with patch.object(lead_scraper, "RUNTIME_EVIDENCE_DIR", Path(tmp_dir)):
                evidence = await lead_scraper._capture_runtime_evidence(
                    page,
                    "unit_test_stage",
                    RuntimeError("selector failed"),
                    selector="div[role=button]",
                    extra={"username": "demo"},
                )

            self.assertEqual(evidence["flow"], "scraper")
            self.assertEqual(evidence["stage"], "unit_test_stage")
            self.assertEqual(evidence["selector"], "div[role=button]")
            self.assertEqual(evidence["extra"]["username"], "demo")
            metadata_files = list(Path(tmp_dir).glob("scraper_unit_test_stage_*.json"))
            self.assertEqual(len(metadata_files), 1)
            payload = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["error"], "selector failed")
            page.screenshot.assert_awaited_once()

        with tempfile.TemporaryDirectory() as tmp_dir:
            asyncio.run(run_case(tmp_dir))

    def test_outreach_capture_runtime_evidence_writes_metadata_and_screenshot(self):
        async def run_case(tmp_dir: str):
            page = AsyncMock()
            type(page).url = PropertyMock(return_value="https://www.instagram.com/demo/")
            page.title.return_value = "DM Composer"
            page.screenshot.return_value = None

            with patch.object(outreach_manager, "RUNTIME_EVIDENCE_DIR", Path(tmp_dir)):
                evidence = await outreach_manager._capture_outreach_evidence(
                    page,
                    "composer_failure",
                    RuntimeError("button missing"),
                    selector="message_button",
                    extra={"username": "demo"},
                )

            self.assertEqual(evidence["flow"], "outreach")
            self.assertEqual(evidence["stage"], "composer_failure")
            metadata_files = list(Path(tmp_dir).glob("outreach_composer_failure_*.json"))
            self.assertEqual(len(metadata_files), 1)
            payload = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["error"], "button missing")
            page.screenshot.assert_awaited_once()

        with tempfile.TemporaryDirectory() as tmp_dir:
            asyncio.run(run_case(tmp_dir))


if __name__ == "__main__":
    unittest.main()
