import os
import sys
import tempfile
import sqlite3
import shutil
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scripts.backup.backup_manager import BackupManager, BackupMetadata
from scripts.backup.snapshot_manager import SnapshotManager, SnapshotMetadata
from scripts.backup.retention_policy import RetentionPolicy, RetentionRule
from scripts.recovery.restore_manager import RestoreManager, RestoreResult
from scripts.health.health_snapshot import HealthSnapshot, HealthMetrics


class TestBackupManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"
        self.backup_dir = Path(self.temp_dir) / "backups"
        self.backup_dir.mkdir()
        
        conn = sqlite3.connect(str(self.test_db))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test (name) VALUES ('test1')")
        conn.execute("INSERT INTO test (name) VALUES ('test2')")
        conn.commit()
        conn.close()
        
        self.manager = BackupManager(
            backup_dir=self.backup_dir,
            db_path=self.test_db,
            retention_days=7
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_full_backup(self):
        metadata = self.manager.create_full_backup(tags=["test"])
        
        self.assertIsNotNone(metadata.backup_id)
        self.assertTrue(metadata.backup_id.startswith("full_"))
        self.assertEqual(metadata.backup_type, "full")
        self.assertTrue(Path(metadata.backup_path).exists())
        self.assertGreater(metadata.size_bytes, 0)
        self.assertIsNotNone(metadata.checksum)
        self.assertIn("test", metadata.tags)

    def test_list_backups(self):
        self.manager.create_full_backup()
        self.manager.create_full_backup()
        
        backups = self.manager.list_backups()
        self.assertEqual(len(backups), 2)

    def test_list_backups_by_type(self):
        self.manager.create_full_backup()
        
        full_backups = self.manager.list_backups(backup_type="full")
        incr_backups = self.manager.list_backups(backup_type="incremental")
        
        self.assertEqual(len(full_backups), 1)
        self.assertEqual(len(incr_backups), 0)

    def test_verify_backup(self):
        metadata = self.manager.create_full_backup()
        
        result = self.manager.verify_backup(metadata.backup_id)
        self.assertTrue(result)

    def test_delete_backup(self):
        metadata = self.manager.create_full_backup()
        
        result = self.manager.delete_backup(metadata.backup_id)
        self.assertTrue(result)
        
        backups = self.manager.list_backups()
        self.assertEqual(len(backups), 0)

    def test_get_backup_stats(self):
        self.manager.create_full_backup()
        
        stats = self.manager.get_backup_stats()
        
        self.assertEqual(stats["total_backups"], 1)
        self.assertGreater(stats["total_size_bytes"], 0)
        self.assertIn("full", stats["by_type"])


class TestSnapshotManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"
        self.snapshot_dir = Path(self.temp_dir) / "snapshots"
        self.snapshot_dir.mkdir()
        
        conn = sqlite3.connect(str(self.test_db))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test (name) VALUES ('test1')")
        conn.commit()
        conn.close()
        
        self.manager = SnapshotManager(
            snapshot_dir=self.snapshot_dir,
            db_path=self.test_db
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_base_snapshot(self):
        metadata = self.manager.create_base_snapshot()
        
        self.assertIsNotNone(metadata.snapshot_id)
        self.assertTrue(metadata.snapshot_id.startswith("base_"))
        self.assertEqual(metadata.snapshot_type, "base")
        self.assertTrue(Path(metadata.snapshot_path).exists())

    def test_list_snapshots(self):
        self.manager.create_base_snapshot()
        
        snapshots = self.manager.list_snapshots()
        self.assertEqual(len(snapshots), 1)

    def test_verify_snapshot(self):
        metadata = self.manager.create_base_snapshot()
        
        result = self.manager.verify_snapshot(metadata.snapshot_id)
        self.assertTrue(result)

    def test_get_snapshot_stats(self):
        self.manager.create_base_snapshot()
        
        stats = self.manager.get_snapshot_stats()
        
        self.assertEqual(stats["total_snapshots"], 1)
        self.assertEqual(stats["total_chains"], 1)


class TestRetentionPolicy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.policy = RetentionPolicy(retention_days=30)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_should_delete_old_backup(self):
        old_backup = BackupMetadata(
            backup_id="test1",
            backup_path="/tmp/test.db",
            source_db_path="/tmp/test.db",
            timestamp=(datetime.utcnow() - timedelta(days=45)).isoformat() + "Z",
            size_bytes=1000,
            checksum="abc123",
            backup_type="full",
            retention_days=30
        )
        
        result = self.policy.should_delete(old_backup)
        self.assertTrue(result)

    def test_should_not_delete_recent_backup(self):
        recent_backup = BackupMetadata(
            backup_id="test2",
            backup_path="/tmp/test.db",
            source_db_path="/tmp/test.db",
            timestamp=datetime.utcnow().isoformat() + "Z",
            size_bytes=1000,
            checksum="abc123",
            backup_type="full",
            retention_days=30
        )
        
        result = self.policy.should_delete(recent_backup)
        self.assertFalse(result)

    def test_add_rule(self):
        new_rule = RetentionRule(
            rule_id="custom",
            backup_type="full",
            min_count=10,
            max_age_days=60,
            priority=50
        )
        
        self.policy.add_rule(new_rule)
        
        rule_ids = [r.rule_id for r in self.policy.rules]
        self.assertIn("custom", rule_ids)

    def test_calculate_retention_schedule(self):
        schedule = self.policy.calculate_retention_schedule()
        
        self.assertEqual(schedule["retention_days"], 30)
        self.assertGreater(len(schedule["rules"]), 0)


class TestRestoreManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"
        self.backup_dir = Path(self.temp_dir) / "backups"
        self.backup_dir.mkdir()
        
        conn = sqlite3.connect(str(self.test_db))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test (name) VALUES ('test1')")
        conn.commit()
        conn.close()
        
        self.manager = RestoreManager(
            backup_dir=self.backup_dir,
            target_db_path=self.test_db
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_restore_from_backup(self):
        backup_manager = BackupManager(
            backup_dir=self.backup_dir,
            db_path=self.test_db
        )
        backup_meta = backup_manager.create_full_backup()
        
        restore_result = self.manager.restore_from_backup(backup_meta.backup_id)
        
        self.assertTrue(restore_result.success)
        self.assertEqual(restore_result.tables_restored, 1)
        self.assertGreater(restore_result.records_restored, 0)

    def test_restore_history(self):
        backup_manager = BackupManager(
            backup_dir=self.backup_dir,
            db_path=self.test_db
        )
        backup_meta = backup_manager.create_full_backup()
        
        self.manager.restore_from_backup(backup_meta.backup_id)
        
        history = self.manager.get_restore_history()
        self.assertGreater(len(history), 0)


class TestHealthSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"
        self.backup_dir = Path(self.temp_dir) / "backups"
        self.snapshot_dir = Path(self.temp_dir) / "snapshots"
        self.backup_dir.mkdir()
        self.snapshot_dir.mkdir()
        
        conn = sqlite3.connect(str(self.test_db))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test (name) VALUES ('test1')")
        conn.commit()
        conn.close()
        
        self.snapshot = HealthSnapshot(
            db_path=self.test_db,
            backup_dir=self.backup_dir,
            snapshot_dir=self.snapshot_dir
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_collect_database_metrics(self):
        metrics = self.snapshot.collect_database_metrics()
        
        self.assertTrue(metrics["exists"])
        self.assertGreater(metrics["size_bytes"], 0)
        self.assertGreater(len(metrics["tables"]), 0)

    def test_collect_backup_metrics(self):
        metrics = self.snapshot.collect_backup_metrics()
        
        self.assertIn("total_backups", metrics)
        self.assertIn("issues", metrics)

    def test_create_health_snapshot(self):
        health = self.snapshot.create_health_snapshot()
        
        self.assertIsNotNone(health.timestamp)
        self.assertIn(health.overall_status, ["healthy", "degraded", "unhealthy"])
        self.assertIsNotNone(health.database)

    def test_check_health(self):
        self.snapshot.create_health_snapshot()
        
        health_check = self.snapshot.check_health()
        
        self.assertIn("status", health_check)


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = Path(self.temp_dir) / "test.db"
        self.backup_dir = Path(self.temp_dir) / "backups"
        self.snapshot_dir = Path(self.temp_dir) / "snapshots"
        self.backup_dir.mkdir()
        self.snapshot_dir.mkdir()
        
        conn = sqlite3.connect(str(self.test_db))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT)")
        conn.execute("INSERT INTO users (name) VALUES ('Alice')")
        conn.execute("INSERT INTO posts (user_id, title) VALUES (1, 'Hello World')")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_backup_restore_cycle(self):
        backup_manager = BackupManager(
            backup_dir=self.backup_dir,
            db_path=self.test_db,
            retention_days=30
        )
        
        backup_meta = backup_manager.create_full_backup(tags=["integration-test"])
        
        self.assertTrue(backup_manager.verify_backup(backup_meta.backup_id))
        
        restore_manager = RestoreManager(
            backup_dir=self.backup_dir,
            target_db_path=self.test_db
        )
        
        target_path = Path(self.temp_dir) / "restored.db"
        result = restore_manager.restore_from_backup(
            backup_meta.backup_id,
            target_path=target_path
        )
        
        self.assertTrue(result.success)
        self.assertTrue(target_path.exists())
        
        conn = sqlite3.connect(str(target_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()
        
        table_names = [t[0] for t in tables]
        self.assertIn("users", table_names)
        self.assertIn("posts", table_names)

    def test_health_snapshot_after_backup(self):
        backup_manager = BackupManager(
            backup_dir=self.backup_dir,
            db_path=self.test_db
        )
        backup_manager.create_full_backup()
        
        health_snapshot = HealthSnapshot(
            db_path=self.test_db,
            backup_dir=self.backup_dir,
            snapshot_dir=self.snapshot_dir
        )
        
        health = health_snapshot.create_health_snapshot()
        
        self.assertEqual(health.backups["total_backups"], 1)
        self.assertEqual(health.overall_status, "healthy")


if __name__ == "__main__":
    unittest.main()
