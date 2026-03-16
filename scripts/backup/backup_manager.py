import os
import shutil
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
import sqlite3
import time
import random

logger = logging.getLogger("botardium.backup")


@dataclass
class BackupMetadata:
    backup_id: str
    backup_path: str
    source_db_path: str
    timestamp: str
    size_bytes: int
    checksum: str
    backup_type: str
    incremental_from: Optional[str] = None
    retention_days: int = 30
    tags: List[str] = field(default_factory=list)


@dataclass
class BackupManifest:
    manifest_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    backups: List[BackupMetadata] = field(default_factory=list)


class BackupManager:
    def __init__(
        self,
        backup_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        retention_days: int = 30
    ):
        from scripts.runtime_paths import DB_PATH, TMP_DIR
        self.db_path = db_path or DB_PATH
        self.backup_dir = backup_dir or (TMP_DIR / "backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.manifest_path = self.backup_dir / "manifest.json"
        self._manifest: Optional[BackupManifest] = None

    def _calculate_checksum(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _humanize_delay(self) -> None:
        delay = random.uniform(0.5, 1.5)
        time.sleep(delay)

    def _load_manifest(self) -> BackupManifest:
        if self._manifest is not None:
            return self._manifest
        if self.manifest_path.exists():
            with open(self.manifest_path, "r") as f:
                data = json.load(f)
                backups = [BackupMetadata(**b) for b in data.get("backups", [])]
                self._manifest = BackupManifest(
                    manifest_version=data.get("manifest_version", "1.0"),
                    created_at=data.get("created_at", datetime.utcnow().isoformat()),
                    backups=backups
                )
        else:
            self._manifest = BackupManifest()
        return self._manifest

    def _save_manifest(self) -> None:
        if self._manifest is None:
            return
        manifest_data = {
            "manifest_version": self._manifest.manifest_version,
            "created_at": self._manifest.created_at,
            "backups": [asdict(b) for b in self._manifest.backups]
        }
        with open(self.manifest_path, "w") as f:
            json.dump(manifest_data, f, indent=2)

    def _get_connection(self, db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create_full_backup(self, tags: Optional[List[str]] = None) -> BackupMetadata:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        self._humanize_delay()

        timestamp = datetime.utcnow()
        backup_id = f"full_{timestamp.strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(str(timestamp).encode()).hexdigest()[:8]}"
        backup_filename = f"{backup_id}.db"
        backup_path = self.backup_dir / backup_filename

        shutil.copy2(str(self.db_path), str(backup_path))

        size_bytes = backup_path.stat().st_size
        checksum = self._calculate_checksum(backup_path)

        metadata = BackupMetadata(
            backup_id=backup_id,
            backup_path=str(backup_path),
            source_db_path=str(self.db_path),
            timestamp=timestamp.isoformat() + "Z",
            size_bytes=size_bytes,
            checksum=checksum,
            backup_type="full",
            retention_days=self.retention_days,
            tags=tags or []
        )

        manifest = self._load_manifest()
        manifest.backups.append(metadata)
        self._manifest = manifest
        self._save_manifest()

        logger.info(f"Created full backup: {backup_id} ({size_bytes} bytes)")
        return metadata

    def create_incremental_backup(self, base_backup_id: Optional[str] = None) -> BackupMetadata:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        manifest = self._load_manifest()
        
        if base_backup_id:
            base_backup = next((b for b in manifest.backups if b.backup_id == base_backup_id), None)
            if not base_backup:
                raise ValueError(f"Base backup not found: {base_backup_id}")
        else:
            full_backups = [b for b in manifest.backups if b.backup_type == "full"]
            if not full_backups:
                raise ValueError("No full backup found. Create a full backup first.")
            base_backup = full_backups[-1]

        self._humanize_delay()

        timestamp = datetime.utcnow()
        backup_id = f"incr_{timestamp.strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(str(timestamp).encode()).hexdigest()[:8]}"
        backup_filename = f"{backup_id}.db"
        backup_path = self.backup_dir / backup_filename

        shutil.copy2(base_backup.backup_path, backup_path)

        conn = self._get_connection(self.db_path)
        backup_conn = self._get_connection(backup_path)
        try:
            backup_conn.backup(conn, "main")
        finally:
            conn.close()
            backup_conn.close()

        backup_path.chmod(0o600)

        size_bytes = backup_path.stat().st_size
        checksum = self._calculate_checksum(backup_path)

        metadata = BackupMetadata(
            backup_id=backup_id,
            backup_path=str(backup_path),
            source_db_path=str(self.db_path),
            timestamp=timestamp.isoformat() + "Z",
            size_bytes=size_bytes,
            checksum=checksum,
            backup_type="incremental",
            incremental_from=base_backup.backup_id,
            retention_days=self.retention_days,
            tags=[]
        )

        manifest.backups.append(metadata)
        self._manifest = manifest
        self._save_manifest()

        logger.info(f"Created incremental backup: {backup_id} (from {base_backup.backup_id})")
        return metadata

    def list_backups(self, backup_type: Optional[str] = None) -> List[BackupMetadata]:
        manifest = self._load_manifest()
        backups = manifest.backups
        if backup_type:
            backups = [b for b in backups if b.backup_type == backup_type]
        return sorted(backups, key=lambda x: x.timestamp, reverse=True)

    def get_backup(self, backup_id: str) -> Optional[BackupMetadata]:
        manifest = self._load_manifest()
        return next((b for b in manifest.backups if b.backup_id == backup_id), None)

    def verify_backup(self, backup_id: str) -> bool:
        backup = self.get_backup(backup_id)
        if not backup:
            return False

        backup_path = Path(backup.backup_path)
        if not backup_path.exists():
            logger.error(f"Backup file missing: {backup_path}")
            return False

        current_checksum = self._calculate_checksum(backup_path)
        if current_checksum != backup.checksum:
            logger.error(f"Backup checksum mismatch: expected {backup.checksum}, got {current_checksum}")
            return False

        try:
            conn = sqlite3.connect(str(backup_path))
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            conn.close()
        except Exception as e:
            logger.error(f"Backup integrity check failed: {e}")
            return False

        logger.info(f"Backup verified: {backup_id}")
        return True

    def delete_backup(self, backup_id: str) -> bool:
        manifest = self._load_manifest()
        backup = self.get_backup(backup_id)
        if not backup:
            return False

        backup_path = Path(backup.backup_path)
        if backup_path.exists():
            backup_path.unlink()

        manifest.backups = [b for b in manifest.backups if b.backup_id != backup_id]
        self._manifest = manifest
        self._save_manifest()

        logger.info(f"Deleted backup: {backup_id}")
        return True

    def cleanup_old_backups(self) -> List[str]:
        from scripts.backup.retention_policy import RetentionPolicy
        
        policy = RetentionPolicy(retention_days=self.retention_days)
        manifest = self._load_manifest()
        
        to_delete = []
        for backup in manifest.backups:
            if policy.should_delete(backup):
                to_delete.append(backup.backup_id)
                backup_path = Path(backup.backup_path)
                if backup_path.exists():
                    backup_path.unlink()

        manifest.backups = [b for b in manifest.backups if b.backup_id not in to_delete]
        self._manifest = manifest
        self._save_manifest()

        logger.info(f"Cleaned up {len(to_delete)} old backups")
        return to_delete

    def get_backup_stats(self) -> Dict[str, Any]:
        manifest = self._load_manifest()
        backups = manifest.backups
        
        total_size = sum(b.size_bytes for b in backups)
        by_type = {}
        for b in backups:
            by_type[b.backup_type] = by_type.get(b.backup_type, 0) + 1

        return {
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "by_type": by_type,
            "oldest_backup": min((b.timestamp for b in backups), default=None),
            "newest_backup": max((b.timestamp for b in backups), default=None)
        }
