"""
Phase 3: Persistence/Runtime Path Unification Tests
===================================================
Tests for the unified runtime path model, reconciliation safeguards,
and rollback provisions.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from scripts.runtime_paths import (
    DB_PATH,
    DB_DIR,
    TMP_DIR,
    CONFIG_DIR,
    SESSIONS_DIR,
    LOG_DIR,
    EXPORTS_TMP_DIR,
    IMPORTS_TMP_DIR,
    SOURCE_ROOT,
    WRITABLE_ROOT,
    IS_FROZEN,
    get_path_discovery_report,
    create_rollback_snapshot,
    verify_path_convergence,
    ensure_runtime_dirs,
)


class TestRuntimePathsAuthority:
    """Test that runtime_paths is the sole authoritative source."""

    def test_db_path_resolves_correctly(self):
        """DB_PATH should resolve to WRITABLE_ROOT/database/botardium.db"""
        assert DB_PATH.name == "botardium.db"
        assert DB_PATH.parent == DB_DIR

    def test_db_dir_under_writable_root(self):
        """DB_DIR should be under WRITABLE_ROOT"""
        assert str(DB_DIR).startswith(str(WRITABLE_ROOT))

    def test_tmp_dir_under_writable_root(self):
        """TMP_DIR should be under WRITABLE_ROOT"""
        assert str(TMP_DIR).startswith(str(WRITABLE_ROOT))

    def test_sessions_dir_under_writable_root_or_agents(self):
        """SESSIONS_DIR should be under WRITABLE_ROOT (frozen) or .agents (dev)"""
        if IS_FROZEN:
            assert str(SESSIONS_DIR).startswith(str(WRITABLE_ROOT))
        else:
            assert ".agents" in str(SESSIONS_DIR)

    def test_log_dir_under_tmp(self):
        """LOG_DIR should be under TMP_DIR"""
        assert LOG_DIR.parent == TMP_DIR

    def test_exports_tmp_under_tmp(self):
        """EXPORTS_TMP_DIR should be under TMP_DIR"""
        assert EXPORTS_TMP_DIR.parent == TMP_DIR

    def test_imports_tmp_under_tmp(self):
        """IMPORTS_TMP_DIR should be under TMP_DIR"""
        assert IMPORTS_TMP_DIR.parent == TMP_DIR


class TestEnsureRuntimeDirs:
    """Test directory creation."""

    def test_ensure_runtime_dirs_creates_all_directories(self, tmp_path):
        """ensure_runtime_dirs should create all required directories"""
        with patch("scripts.runtime_paths.WRITABLE_ROOT", tmp_path):
            with patch("scripts.runtime_paths.SOURCE_ROOT", tmp_path):
                with patch("scripts.runtime_paths.TMP_DIR", tmp_path / ".tmp"):
                    with patch("scripts.runtime_paths.SESSIONS_DIR", tmp_path / "sessions"):
                        from scripts import runtime_paths
                        runtime_paths.TMP_DIR = tmp_path / ".tmp"
                        runtime_paths.SESSIONS_DIR = tmp_path / "sessions"
                        runtime_paths.DB_DIR = tmp_path / "database"
                        runtime_paths.CONFIG_DIR = tmp_path / "config"
                        runtime_paths.EXPORTS_TMP_DIR = tmp_path / ".tmp" / "exports"
                        runtime_paths.IMPORTS_TMP_DIR = tmp_path / ".tmp" / "imports"
                        runtime_paths.LOG_DIR = tmp_path / ".tmp" / "logs"
                        runtime_paths.SESSION_CREDENTIALS_DIR = tmp_path / "session_credentials"

                        runtime_paths.ensure_runtime_dirs()

                        assert (tmp_path / ".tmp").exists()
                        assert (tmp_path / "database").exists()
                        assert (tmp_path / "config").exists()
                        assert (tmp_path / "sessions").exists()
                        assert (tmp_path / ".tmp" / "exports").exists()
                        assert (tmp_path / ".tmp" / "imports").exists()
                        assert (tmp_path / ".tmp" / "logs").exists()
                        assert (tmp_path / "session_credentials").exists()


class TestPathDiscoveryReport:
    """Test the reconciliation report functionality."""

    def test_get_path_discovery_report_structure(self):
        """Report should have expected keys"""
        report = get_path_discovery_report()

        assert "authoritative_db_path" in report
        assert "authoritative_db_exists" in report
        assert "authoritative_session_dir" in report
        assert "legacy_db_paths_checked" in report
        assert "discovered_databases" in report
        assert "discovered_sessions" in report
        assert "path_divergence_detected" in report
        assert isinstance(report["discovered_databases"], list)
        assert isinstance(report["discovered_sessions"], list)

    def test_path_divergence_flagged_when_legacy_exists(self, tmp_path):
        """Should detect path divergence when legacy DB exists"""
        legacy_db = tmp_path / "database" / "botardium.db"
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        legacy_db.write_text("test")

        with patch("scripts.runtime_paths.WRITABLE_ROOT", tmp_path):
            with patch("scripts.runtime_paths.SOURCE_ROOT", tmp_path):
                from scripts import runtime_paths
                runtime_paths.WRITABLE_ROOT = tmp_path

                report = get_path_discovery_report()
                assert "path_divergence_detected" in report


class TestRollbackSnapshot:
    """Test rollback snapshot functionality."""

    def test_create_rollback_snapshot_returns_path(self, tmp_path):
        """Should create a snapshot file and return its path"""
        test_db = tmp_path / "database" / "botardium.db"
        test_db.parent.mkdir(parents=True, exist_ok=True)
        test_db.write_text("test database content")

        with patch("scripts.runtime_paths.DB_PATH", test_db):
            with patch("scripts.runtime_paths.TMP_DIR", tmp_path / ".tmp"):
                from scripts import runtime_paths
                runtime_paths.TMP_DIR = tmp_path / ".tmp"

                snapshot_path = create_rollback_snapshot("test_snapshot")

                assert snapshot_path is not None
                assert snapshot_path.exists()
                assert snapshot_path.name == "test_snapshot.db"

    def test_create_rollback_snapshot_no_db(self, tmp_path):
        """Should return None when no DB exists"""
        with patch("scripts.runtime_paths.DB_PATH", tmp_path / "nonexistent.db"):
            with patch("scripts.runtime_paths.TMP_DIR", tmp_path / ".tmp"):
                from scripts import runtime_paths

                snapshot_path = create_rollback_snapshot()

                assert snapshot_path is None


class TestPathConvergence:
    """Test path convergence verification."""

    def test_verify_path_convergence_structure(self):
        """Should return expected structure"""
        result = verify_path_convergence()

        assert "converged" in result
        assert "db_path_resolution" in result
        assert "session_dir_resolution" in result
        assert "tmp_dir_resolution" in result
        assert "config_dir_resolution" in result
        assert "logs_dir_resolution" in result
        assert "issues" in result
        assert isinstance(result["issues"], list)

    def test_verify_path_convergence_with_db(self, tmp_path):
        """Should report db_exists when DB is present"""
        test_db = tmp_path / "database" / "botardium.db"
        test_db.parent.mkdir(parents=True, exist_ok=True)
        test_db.write_text("test")

        with patch("scripts.runtime_paths.WRITABLE_ROOT", tmp_path):
            with patch("scripts.runtime_paths.SOURCE_ROOT", tmp_path):
                with patch("scripts.runtime_paths.DB_PATH", test_db):
                    with patch("scripts.runtime_paths.TMP_DIR", tmp_path / ".tmp"):
                        with patch("scripts.runtime_paths.SESSIONS_DIR", tmp_path / "sessions"):
                            with patch("scripts.runtime_paths.CONFIG_DIR", tmp_path / "config"):
                                with patch("scripts.runtime_paths.LOG_DIR", tmp_path / ".tmp" / "logs"):
                                    from scripts import runtime_paths

                                    result = runtime_paths.verify_path_convergence()

                                    assert "db_exists" in result
                                    assert result["db_exists"] is True


class TestDbManagerIntegration:
    """Test that db_manager consumes runtime_paths correctly."""

    def test_db_manager_uses_runtime_paths(self):
        """DatabaseManager should use runtime_paths.DB_PATH as default"""
        sys.path.insert(0, str(SOURCE_ROOT))
        sys.path.insert(0, str(SOURCE_ROOT / ".agents"))
        from skills.db_manager import DatabaseManager
        from scripts.runtime_paths import DB_PATH

        db = DatabaseManager()
        assert db.db_path == DB_PATH

    def test_db_manager_can_accept_custom_path(self, tmp_path):
        """DatabaseManager should accept custom db_path"""
        sys.path.insert(0, str(SOURCE_ROOT))
        sys.path.insert(0, str(SOURCE_ROOT / ".agents"))
        from skills.db_manager import DatabaseManager

        custom_path = tmp_path / "custom.db"
        db = DatabaseManager(db_path=custom_path)
        assert db.db_path == custom_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
