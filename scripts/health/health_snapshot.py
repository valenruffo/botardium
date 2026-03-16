import os
import json
import sqlite3
import logging
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("botardium.health_snapshot")


@dataclass
class HealthMetrics:
    timestamp: str
    system: Dict[str, Any]
    database: Dict[str, Any]
    backups: Dict[str, Any]
    snapshots: Dict[str, Any]
    overall_status: str
    issues: List[str] = field(default_factory=list)


class HealthSnapshot:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        snapshot_dir: Optional[Path] = None
    ):
        from scripts.runtime_paths import DB_PATH, TMP_DIR
        self.db_path = db_path or DB_PATH
        self.backup_dir = backup_dir or (TMP_DIR / "backups")
        self.snapshot_dir = snapshot_dir or (TMP_DIR / "snapshots")
        self.health_dir = TMP_DIR / "health"
        self.health_dir.mkdir(parents=True, exist_ok=True)

    def collect_system_metrics(self) -> Dict[str, Any]:
        metrics = {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "python_version": platform.python_version(),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        try:
            import psutil
            metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            metrics["memory_percent"] = psutil.virtual_memory().percent
            metrics["disk_usage_percent"] = psutil.disk_usage('/').percent
        except ImportError:
            logger.debug("psutil not available, skipping system metrics")

        return metrics

    def collect_database_metrics(self) -> Dict[str, Any]:
        metrics = {
            "exists": False,
            "size_bytes": 0,
            "tables": [],
            "total_records": 0,
            "wal_mode": False,
            "page_count": 0,
            "page_size": 0,
            "issues": []
        }

        if not self.db_path.exists():
            metrics["issues"].append("Database file does not exist")
            return metrics

        metrics["exists"] = True
        metrics["size_bytes"] = self.db_path.stat().st_size

        try:
            conn = sqlite3.connect(str(self.db_path))
            
            cursor = conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            metrics["wal_mode"] = journal_mode.lower() == "wal"

            cursor = conn.execute("PRAGMA page_count")
            metrics["page_count"] = cursor.fetchone()[0]

            cursor = conn.execute("PRAGMA page_size")
            metrics["page_size"] = cursor.fetchone()[0]

            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for (table_name,) in tables:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                metrics["tables"].append({
                    "name": table_name,
                    "count": count
                })
                metrics["total_records"] += count

            conn.close()
        except Exception as e:
            metrics["issues"].append(f"Error reading database: {str(e)}")

        return metrics

    def collect_backup_metrics(self) -> Dict[str, Any]:
        metrics = {
            "total_backups": 0,
            "total_size_bytes": 0,
            "by_type": {},
            "latest_backup": None,
            "oldest_backup": None,
            "issues": []
        }

        manifest_path = self.backup_dir / "manifest.json"
        if not manifest_path.exists():
            metrics["issues"].append("No backup manifest found")
            return metrics

        try:
            with open(manifest_path, "r") as f:
                data = json.load(f)
                backups = data.get("backups", [])
                
                metrics["total_backups"] = len(backups)
                metrics["total_size_bytes"] = sum(b.get("size_bytes", 0) for b in backups)

                by_type = {}
                for b in backups:
                    btype = b.get("backup_type", "unknown")
                    by_type[btype] = by_type.get(btype, 0) + 1
                metrics["by_type"] = by_type

                if backups:
                    sorted_backups = sorted(backups, key=lambda x: x.get("timestamp", ""))
                    metrics["oldest_backup"] = sorted_backups[0].get("backup_id")
                    metrics["latest_backup"] = sorted_backups[-1].get("backup_id")
        except Exception as e:
            metrics["issues"].append(f"Error reading backup manifest: {str(e)}")

        return metrics

    def collect_snapshot_metrics(self) -> Dict[str, Any]:
        metrics = {
            "total_snapshots": 0,
            "total_chains": 0,
            "total_size_bytes": 0,
            "latest_snapshot": None,
            "issues": []
        }

        chains_path = self.snapshot_dir / "chains.json"
        if not chains_path.exists():
            metrics["no_snapshots"] = True
            return metrics

        try:
            with open(chains_path, "r") as f:
                chains = json.load(f)
                metrics["total_chains"] = len(chains)
                metrics["total_snapshots"] = sum(len(c.get("snapshots", [])) for c in chains)

                snapshot_files = list(self.snapshot_dir.glob("*.db"))
                metrics["total_size_bytes"] = sum(f.stat().st_size for f in snapshot_files)

                snapshot_metas = list(self.snapshot_dir.glob("*_meta.json"))
                if snapshot_metas:
                    latest = max(snapshot_metas, key=lambda p: p.stat().st_mtime)
                    with open(latest, "r") as sf:
                        meta = json.load(sf)
                        metrics["latest_snapshot"] = meta.get("snapshot_id")
        except Exception as e:
            metrics["issues"].append(f"Error reading snapshot data: {str(e)}")

        return metrics

    def create_health_snapshot(self) -> HealthMetrics:
        system = self.collect_system_metrics()
        database = self.collect_database_metrics()
        backups = self.collect_backup_metrics()
        snapshots = self.collect_snapshot_metrics()

        issues = []
        
        if database.get("issues"):
            issues.extend(database["issues"])
        
        if backups.get("issues"):
            issues.extend(backups["issues"])
        
        if self.snapshot_dir.exists() and snapshots.get("issues"):
            issues.extend(snapshots["issues"])
        
        if not database["exists"]:
            issues.append("Database does not exist")
        
        if database.get("size_bytes", 0) == 0:
            issues.append("Database is empty")

        if not backups.get("total_backups", 0):
            issues.append("No backups exist")

        overall_status = "healthy"
        if len(issues) > 0:
            overall_status = "degraded"
        if len(issues) > 3:
            overall_status = "unhealthy"

        metrics = HealthMetrics(
            timestamp=datetime.utcnow().isoformat() + "Z",
            system=system,
            database=database,
            backups=backups,
            snapshots=snapshots,
            overall_status=overall_status,
            issues=issues
        )

        self._save_snapshot(metrics)

        logger.info(f"Health snapshot created: {overall_status}")
        return metrics

    def _save_snapshot(self, metrics: HealthMetrics) -> None:
        snapshot_id = f"health_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        snapshot_path = self.health_dir / f"{snapshot_id}.json"
        
        with open(snapshot_path, "w") as f:
            json.dump(asdict(metrics), f, indent=2)

    def get_latest_health_snapshot(self) -> Optional[HealthMetrics]:
        snapshot_files = sorted(
            self.health_dir.glob("health_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        if not snapshot_files:
            return None

        with open(snapshot_files[0], "r") as f:
            data = json.load(f)
            return HealthMetrics(**data)

    def get_health_history(self, limit: int = 10) -> List[HealthMetrics]:
        snapshot_files = sorted(
            self.health_dir.glob("health_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:limit]

        snapshots = []
        for sf in snapshot_files:
            with open(sf, "r") as f:
                data = json.load(f)
                snapshots.append(HealthMetrics(**data))

        return snapshots

    def get_health_trends(self, days: int = 7) -> Dict[str, Any]:
        import time
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_timestamp = cutoff.timestamp()
        
        snapshot_files = [
            f for f in self.health_dir.glob("health_*.json")
            if f.stat().st_mtime >= cutoff_timestamp
        ]
        
        snapshots = []
        for sf in sorted(snapshot_files, key=lambda p: p.stat().st_mtime):
            with open(sf, "r") as f:
                data = json.load(f)
                snapshots.append(HealthMetrics(**data))

        if not snapshots:
            return {"error": "No health snapshots found in time range"}

        statuses = [s.overall_status for s in snapshots]
        avg_db_size = sum(s.database.get("size_bytes", 0) for s in snapshots) / len(snapshots)
        total_backups = sum(s.backups.get("total_backups", 0) for s in snapshots) / len(snapshots)

        return {
            "period_days": days,
            "snapshot_count": len(snapshots),
            "status_distribution": {
                "healthy": statuses.count("healthy"),
                "degraded": statuses.count("degraded"),
                "unhealthy": statuses.count("unhealthy")
            },
            "average_db_size_bytes": avg_db_size,
            "average_backup_count": total_backups
        }

    def check_health(self) -> Dict[str, Any]:
        latest = self.get_latest_health_snapshot()
        
        if not latest:
            return {
                "status": "unknown",
                "message": "No health snapshot available"
            }

        return {
            "status": latest.overall_status,
            "timestamp": latest.timestamp,
            "issues": latest.issues,
            "database_size_bytes": latest.database.get("size_bytes", 0),
            "backup_count": latest.backups.get("total_backups", 0)
        }
