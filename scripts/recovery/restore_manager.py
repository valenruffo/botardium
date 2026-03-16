import os
import shutil
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("botardium.restore")


@dataclass
class RestorePoint:
    restore_id: str
    backup_id: str
    timestamp: str
    target_path: str
    status: str
    checksum_verified: bool = False


@dataclass
class RestoreResult:
    success: bool
    restore_id: str
    original_db_path: str
    restored_db_path: str
    backup_used: str
    tables_restored: int
    records_restored: int
    duration_seconds: float
    error_message: Optional[str] = None


class RestoreManager:
    def __init__(
        self,
        backup_dir: Optional[Path] = None,
        target_db_path: Optional[Path] = None
    ):
        from scripts.runtime_paths import DB_PATH, TMP_DIR
        self.backup_dir = backup_dir or (TMP_DIR / "backups")
        self.target_db_path = target_db_path or DB_PATH
        self.restore_history_path = TMP_DIR / "restore_history.json"
        self._restore_history: Optional[List[RestorePoint]] = None

    def _load_restore_history(self) -> List[RestorePoint]:
        if self._restore_history is not None:
            return self._restore_history
        if self.restore_history_path.exists():
            with open(self.restore_history_path, "r") as f:
                data = json.load(f)
                self._restore_history = [RestorePoint(**rp) for rp in data]
        else:
            self._restore_history = []
        return self._restore_history

    def _save_restore_history(self) -> None:
        if self._restore_history is None:
            return
        data = [asdict(rp) for rp in self._restore_history]
        with open(self.restore_history_path, "w") as f:
            json.dump(data, f, indent=2)

    def list_restore_points(self) -> List[RestorePoint]:
        return self._load_restore_history()

    def create_restore_point(self, backup_id: str) -> RestorePoint:
        if not self.target_db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.target_db_path}")

        timestamp = datetime.utcnow()
        restore_id = f"restore_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        restore_point = RestorePoint(
            restore_id=restore_id,
            backup_id=backup_id,
            timestamp=timestamp.isoformat() + "Z",
            target_path=str(self.target_db_path),
            status="pending"
        )

        history = self._load_restore_history()
        history.append(restore_point)
        self._save_restore_history()

        logger.info(f"Created restore point: {restore_id}")
        return restore_point

    def restore_from_backup(
        self,
        backup_id: str,
        target_path: Optional[Path] = None,
        verify_checksum: bool = True
    ) -> RestoreResult:
        from scripts.backup.backup_manager import BackupManager
        
        backup_manager = BackupManager(backup_dir=self.backup_dir)
        backup = backup_manager.get_backup(backup_id)
        
        if not backup:
            return RestoreResult(
                success=False,
                restore_id="",
                original_db_path=str(self.target_db_path),
                restored_db_path="",
                backup_used=backup_id,
                tables_restored=0,
                records_restored=0,
                duration_seconds=0,
                error_message=f"Backup not found: {backup_id}"
            )

        start_time = datetime.utcnow()
        
        if verify_checksum:
            if not backup_manager.verify_backup(backup_id):
                return RestoreResult(
                    success=False,
                    restore_id="",
                    original_db_path=str(self.target_db_path),
                    restored_db_path="",
                    backup_used=backup_id,
                    tables_restored=0,
                    records_restored=0,
                    duration_seconds=0,
                    error_message="Backup checksum verification failed"
                )

        backup_path = Path(backup.backup_path)
        target = target_path or self.target_db_path

        if target.exists():
            backup_copy = target.parent / f"{target.stem}_pre_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(str(target), str(backup_copy))
            logger.info(f"Created pre-restore backup at {backup_copy}")

        shutil.copy2(str(backup_path), str(target))

        tables_restored = 0
        records_restored = 0
        try:
            conn = sqlite3.connect(str(target))
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            tables_restored = len(tables)
            
            for (table_name,) in tables:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                records_restored += count
            
            conn.close()
        except Exception as e:
            logger.error(f"Error verifying restored database: {e}")

        duration = (datetime.utcnow() - start_time).total_seconds()

        restore_point = self.create_restore_point(backup_id)

        result = RestoreResult(
            success=True,
            restore_id=restore_point.restore_id,
            original_db_path=str(self.target_db_path),
            restored_db_path=str(target),
            backup_used=backup_id,
            tables_restored=tables_restored,
            records_restored=records_restored,
            duration_seconds=duration
        )

        logger.info(f"Restored database from {backup_id}: {tables_restored} tables, {records_restored} records")
        return result

    def restore_to_point_in_time(
        self,
        target_timestamp: datetime,
        target_path: Optional[Path] = None
    ) -> RestoreResult:
        from scripts.backup.backup_manager import BackupManager
        
        backup_manager = BackupManager(backup_dir=self.backup_dir)
        all_backups = backup_manager.list_backups()
        
        applicable_backups = [
            b for b in all_backups
            if datetime.fromisoformat(b.timestamp.replace("Z", "+00:00")) <= target_timestamp
        ]
        
        if not applicable_backups:
            return RestoreResult(
                success=False,
                restore_id="",
                original_db_path=str(self.target_db_path),
                restored_db_path="",
                backup_used="",
                tables_restored=0,
                records_restored=0,
                duration_seconds=0,
                error_message="No backup found before target timestamp"
            )

        applicable_backups.sort(key=lambda x: x.timestamp, reverse=True)
        target_backup = applicable_backups[0]

        return self.restore_from_backup(
            backup_id=target_backup.backup_id,
            target_path=target_path,
            verify_checksum=True
        )

    def restore_incremental_chain(
        self,
        base_backup_id: str,
        incremental_backup_ids: List[str],
        target_path: Optional[Path] = None
    ) -> RestoreResult:
        import sqlite3
        
        from scripts.backup.backup_manager import BackupManager
        backup_manager = BackupManager(backup_dir=self.backup_dir)
        
        base_backup = backup_manager.get_backup(base_backup_id)
        if not base_backup:
            return RestoreResult(
                success=False,
                restore_id="",
                original_db_path=str(self.target_db_path),
                restored_db_path="",
                backup_used=base_backup_id,
                tables_restored=0,
                records_restored=0,
                duration_seconds=0,
                error_message=f"Base backup not found: {base_backup_id}"
            )

        target = target_path or self.target_db_path
        
        shutil.copy2(base_backup.backup_path, str(target))

        for incr_id in incremental_backup_ids:
            incr_backup = backup_manager.get_backup(incr_id)
            if not incr_backup:
                logger.warning(f"Incremental backup not found: {incr_id}, skipping")
                continue
            
            base_conn = sqlite3.connect(str(target))
            incr_conn = sqlite3.connect(incr_backup.backup_path)
            try:
                incr_conn.backup(base_conn)
            finally:
                base_conn.close()
                incr_conn.close()

        tables_restored = 0
        records_restored = 0
        try:
            conn = sqlite3.connect(str(target))
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            tables_restored = len(tables)
            
            for (table_name,) in tables:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                records_restored += count
            
            conn.close()
        except Exception as e:
            logger.error(f"Error verifying restored database: {e}")

        restore_point = self.create_restore_point(incremental_backup_ids[-1] if incremental_backup_ids else base_backup_id)

        return RestoreResult(
            success=True,
            restore_id=restore_point.restore_id,
            original_db_path=str(self.target_db_path),
            restored_db_path=str(target),
            backup_used=f"{base_backup_id} + {len(incremental_backup_ids)} incrementals",
            tables_restored=tables_restored,
            records_restored=records_restored,
            duration_seconds=0
        )

    def get_restore_history(self) -> List[Dict[str, Any]]:
        history = self._load_restore_history()
        return [
            {
                "restore_id": rp.restore_id,
                "backup_id": rp.backup_id,
                "timestamp": rp.timestamp,
                "target_path": rp.target_path,
                "status": rp.status
            }
            for rp in history
        ]

    def verify_restore(self, db_path: Path) -> Dict[str, Any]:
        result = {
            "valid": False,
            "tables": [],
            "total_records": 0,
            "errors": []
        }

        if not db_path.exists():
            result["errors"].append(f"Database file not found: {db_path}")
            return result

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for (table_name,) in tables:
                result["tables"].append(table_name)
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                result["total_records"] += count

            conn.close()
            result["valid"] = True
        except Exception as e:
            result["errors"].append(str(e))

        return result


import json
