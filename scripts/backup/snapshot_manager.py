import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("botardium.snapshot")


@dataclass
class SnapshotMetadata:
    snapshot_id: str
    snapshot_path: str
    timestamp: str
    snapshot_type: str
    size_bytes: int
    record_count: int
    checksum: str
    parent_snapshot_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SnapshotChain:
    chain_id: str
    base_snapshot_id: str
    snapshots: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    is_complete: bool = False


class SnapshotManager:
    def __init__(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Path] = None
    ):
        from scripts.runtime_paths import DB_PATH, TMP_DIR
        self.db_path = db_path or DB_PATH
        self.snapshot_dir = snapshot_dir or (TMP_DIR / "snapshots")
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.chains_path = self.snapshot_dir / "chains.json"
        self._chains: Optional[List[SnapshotChain]] = None

    def _calculate_checksum(self, file_path: Path) -> str:
        import hashlib
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _load_chains(self) -> List[SnapshotChain]:
        if self._chains is not None:
            return self._chains
        if self.chains_path.exists():
            with open(self.chains_path, "r") as f:
                data = json.load(f)
                self._chains = [SnapshotChain(**chain) for chain in data]
        else:
            self._chains = []
        return self._chains

    def _save_chains(self) -> None:
        if self._chains is None:
            return
        chains_data = [asdict(chain) for chain in self._chains]
        with open(self.chains_path, "w") as f:
            json.dump(chains_data, f, indent=2)

    def _get_record_count(self, db_path: Path) -> int:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]
        conn.close()
        return table_count

    def create_base_snapshot(self, metadata: Optional[Dict[str, Any]] = None) -> SnapshotMetadata:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        timestamp = datetime.utcnow()
        snapshot_id = f"base_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        snapshot_filename = f"{snapshot_id}.db"
        snapshot_path = self.snapshot_dir / snapshot_filename

        import shutil
        shutil.copy2(str(self.db_path), str(snapshot_path))

        size_bytes = snapshot_path.stat().st_size
        checksum = self._calculate_checksum(snapshot_path)
        record_count = self._get_record_count(snapshot_path)

        meta = SnapshotMetadata(
            snapshot_id=snapshot_id,
            snapshot_path=str(snapshot_path),
            timestamp=timestamp.isoformat() + "Z",
            snapshot_type="base",
            size_bytes=size_bytes,
            record_count=record_count,
            checksum=checksum,
            parent_snapshot_id=None,
            metadata=metadata or {}
        )

        chain = SnapshotChain(
            chain_id=f"chain_{snapshot_id}",
            base_snapshot_id=snapshot_id,
            snapshots=[snapshot_id]
        )
        chains = self._load_chains()
        chains.append(chain)
        self._chains = chains
        self._save_chains()

        self._save_snapshot_metadata(meta)

        logger.info(f"Created base snapshot: {snapshot_id}")
        return meta

    def create_incremental_snapshot(
        self,
        parent_snapshot_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SnapshotMetadata:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        chains = self._load_chains()
        parent_chain = None
        for chain in chains:
            if parent_snapshot_id in chain.snapshots:
                parent_chain = chain
                break

        if not parent_chain:
            raise ValueError(f"Parent snapshot not found: {parent_snapshot_id}")

        timestamp = datetime.utcnow()
        snapshot_id = f"incr_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        snapshot_filename = f"{snapshot_id}.db"
        snapshot_path = self.snapshot_dir / snapshot_filename

        import shutil
        parent_path = self.snapshot_dir / f"{parent_snapshot_id}.db"
        shutil.copy2(str(parent_path), str(snapshot_path))

        import sqlite3
        parent_conn = sqlite3.connect(str(parent_path))
        snapshot_conn = sqlite3.connect(str(snapshot_path))
        try:
            parent_conn.backup(snapshot_conn)
        finally:
            parent_conn.close()
            snapshot_conn.close()

        size_bytes = snapshot_path.stat().st_size
        checksum = self._calculate_checksum(snapshot_path)
        record_count = self._get_record_count(snapshot_path)

        meta = SnapshotMetadata(
            snapshot_id=snapshot_id,
            snapshot_path=str(snapshot_path),
            timestamp=timestamp.isoformat() + "Z",
            snapshot_type="incremental",
            size_bytes=size_bytes,
            record_count=record_count,
            checksum=checksum,
            parent_snapshot_id=parent_snapshot_id,
            metadata=metadata or {}
        )

        parent_chain.snapshots.append(snapshot_id)
        self._save_chains()
        self._save_snapshot_metadata(meta)

        logger.info(f"Created incremental snapshot: {snapshot_id} (parent: {parent_snapshot_id})")
        return meta

    def _save_snapshot_metadata(self, meta: SnapshotMetadata) -> None:
        meta_path = self.snapshot_dir / f"{meta.snapshot_id}_meta.json"
        with open(meta_path, "w") as f:
            json.dump(asdict(meta), f, indent=2)

    def get_snapshot(self, snapshot_id: str) -> Optional[SnapshotMetadata]:
        meta_path = self.snapshot_dir / f"{snapshot_id}_meta.json"
        if not meta_path.exists():
            return None
        with open(meta_path, "r") as f:
            data = json.load(f)
            return SnapshotMetadata(**data)

    def list_snapshots(self, snapshot_type: Optional[str] = None) -> List[SnapshotMetadata]:
        snapshots = []
        for meta_file in self.snapshot_dir.glob("*_meta.json"):
            with open(meta_file, "r") as f:
                data = json.load(f)
                if snapshot_type is None or data["snapshot_type"] == snapshot_type:
                    snapshots.append(SnapshotMetadata(**data))
        return sorted(snapshots, key=lambda x: x.timestamp, reverse=True)

    def get_chain(self, chain_id: str) -> Optional[SnapshotChain]:
        chains = self._load_chains()
        return next((c for c in chains if c.chain_id == chain_id), None)

    def get_latest_chain(self) -> Optional[SnapshotChain]:
        chains = self._load_chains()
        if not chains:
            return None
        return max(chains, key=lambda c: c.created_at)

    def verify_snapshot(self, snapshot_id: str) -> bool:
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            return False

        snapshot_path = Path(snapshot.snapshot_path)
        if not snapshot_path.exists():
            logger.error(f"Snapshot file missing: {snapshot_path}")
            return False

        current_checksum = self._calculate_checksum(snapshot_path)
        if current_checksum != snapshot.checksum:
            logger.error(f"Snapshot checksum mismatch")
            return False

        try:
            import sqlite3
            conn = sqlite3.connect(str(snapshot_path))
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            conn.close()
        except Exception as e:
            logger.error(f"Snapshot integrity check failed: {e}")
            return False

        logger.info(f"Snapshot verified: {snapshot_id}")
        return True

    def delete_snapshot(self, snapshot_id: str) -> bool:
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            return False

        snapshot_path = Path(snapshot.snapshot_path)
        if snapshot_path.exists():
            snapshot_path.unlink()

        meta_path = self.snapshot_dir / f"{snapshot_id}_meta.json"
        if meta_path.exists():
            meta_path.unlink()

        chains = self._load_chains()
        for chain in chains:
            if snapshot_id in chain.snapshots:
                chain.snapshots = [s for s in chain.snapshots if s != snapshot_id]
        self._save_chains()

        logger.info(f"Deleted snapshot: {snapshot_id}")
        return True

    def get_snapshot_stats(self) -> Dict[str, Any]:
        snapshots = self.list_snapshots()
        chains = self._load_chains()

        total_size = sum(s.size_bytes for s in snapshots)
        by_type = {}
        for s in snapshots:
            by_type[s.snapshot_type] = by_type.get(s.snapshot_type, 0) + 1

        return {
            "total_snapshots": len(snapshots),
            "total_chains": len(chains),
            "total_size_bytes": total_size,
            "by_type": by_type,
            "oldest": min((s.timestamp for s in snapshots), default=None),
            "newest": max((s.timestamp for s in snapshots), default=None)
        }
