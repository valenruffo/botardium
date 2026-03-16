"""
Botardium Core — Session Pooling & Multi-Instance Coordination
==============================================================
Distributed session management with instance registry, health routing,
and distributed locking for coordinated multi-instance operation.

This module provides:
- SessionPool: Instagram session checkout/checkin with state management
- InstanceRegistry: Instance registration with heartbeats and health status
- DistributedLock: Reentrant distributed locking mechanism
- HealthRouter: Route requests to healthy instances
- SQLite-backed with WAL mode for concurrency
"""

import os
import sqlite3
import json
import logging
import threading
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
from uuid import uuid4
from contextlib import contextmanager

from scripts.runtime_paths import DB_DIR

logger = logging.getLogger("botardium.session_pool")

DB_DIR.mkdir(parents=True, exist_ok=True)
SESSION_POOL_DB = DB_DIR / "session_pool.db"

INSTANCE_HEARTBEAT_TIMEOUT_SECONDS = 60
LOCK_ACQUIRE_TIMEOUT_SECONDS = 30
LOCK_MAX_RETRY_COUNT = 3
SESSION_MAX_CONCURRENT_USAGE = 3
HEALTH_CHECK_INTERVAL_SECONDS = 30


class SessionStatus(str, Enum):
    AVAILABLE = "available"
    CHECKED_OUT = "checked_out"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    ROTATING = "rotating"


class InstanceStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


class LockStatus(str, Enum):
    ACQUIRED = "acquired"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass
class InstagramSession:
    session_id: str
    username: str
    session_cookie: str
    status: str
    instance_id: Optional[str]
    checked_out_at: Optional[str]
    checkin_deadline: Optional[str]
    last_used_at: Optional[str]
    usage_count: int
    success_count: int
    failure_count: int
    created_at: str
    updated_at: str


@dataclass
class Instance:
    instance_id: str
    instance_type: str
    hostname: str
    ip_address: Optional[str]
    status: str
    capabilities: List[str]
    current_sessions: int
    max_sessions: int
    registered_at: str
    last_heartbeat: str
    health_score: float


@dataclass
class DistributedLockData:
    lock_id: str
    resource_name: str
    instance_id: str
    owner_id: str
    status: str
    acquire_token: str
    acquire_count: int
    acquired_at: Optional[str]
    expires_at: Optional[str]
    released_at: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class SessionPoolDB:
    def __init__(self, db_path: Path = SESSION_POOL_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS instagram_sessions (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    session_cookie TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    instance_id TEXT,
                    checked_out_at TEXT,
                    checkin_deadline TEXT,
                    last_used_at TEXT,
                    usage_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS instance_registry (
                    instance_id TEXT PRIMARY KEY,
                    instance_type TEXT NOT NULL,
                    hostname TEXT,
                    ip_address TEXT,
                    status TEXT NOT NULL DEFAULT 'healthy',
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    current_sessions INTEGER DEFAULT 0,
                    max_sessions INTEGER DEFAULT 10,
                    registered_at TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL,
                    health_score REAL DEFAULT 100.0
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS distributed_locks (
                    lock_id TEXT PRIMARY KEY,
                    resource_name TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'acquired',
                    acquire_token TEXT NOT NULL,
                    acquire_count INTEGER DEFAULT 1,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    released_at TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_health_log (
                    log_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON instagram_sessions(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_instance ON instagram_sessions(instance_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instances_status ON instance_registry(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instances_heartbeat ON instance_registry(last_heartbeat)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_locks_resource ON distributed_locks(resource_name, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_locks_expires ON distributed_locks(expires_at)")

            conn.commit()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def close_all_connections(self):
        pass


class SessionPool:
    def __init__(self, db: Optional[SessionPoolDB] = None):
        self.db = db or SessionPoolDB()
        self._local = threading.local()

    def register_session(
        self,
        session_id: str,
        username: str,
        session_cookie: str
    ) -> InstagramSession:
        now = _now_iso()

        with self.db._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO instagram_sessions 
                (session_id, username, session_cookie, status, usage_count, success_count, failure_count, created_at, updated_at)
                VALUES (?, ?, ?, 'available', 0, 0, 0, ?, ?)
            """, (session_id, username, session_cookie, now, now))
            conn.commit()

        logger.info(f"Session {session_id} registered for user {username}")

        return self.get_session(session_id)

    def checkout_session(
        self,
        instance_id: str,
        max_duration_seconds: int = 300
    ) -> Optional[InstagramSession]:
        now = _now_dt()
        now_iso = _now_iso()
        deadline = now + timedelta(seconds=max_duration_seconds)
        deadline_iso = deadline.strftime("%Y-%m-%d %H:%M:%S")

        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM instagram_sessions 
                WHERE status = 'available' 
                AND (instance_id IS NULL OR instance_id = ?)
                AND (checkin_deadline IS NULL OR checkin_deadline < ?)
                ORDER BY usage_count ASC, last_used_at ASC
                LIMIT 1
            """, (instance_id, now_iso))

            row = cursor.fetchone()

            if not row:
                return None

            session_id = row["session_id"]

            cursor.execute("""
                UPDATE instagram_sessions 
                SET status = 'checked_out', 
                    instance_id = ?, 
                    checked_out_at = ?, 
                    checkin_deadline = ?,
                    usage_count = usage_count + 1,
                    updated_at = ?
                WHERE session_id = ? AND status = 'available'
            """, (instance_id, now_iso, deadline_iso, now_iso, session_id))

            if cursor.rowcount == 0:
                return None

            conn.commit()

        logger.info(f"Session {session_id} checked out by instance {instance_id}")

        return self.get_session(session_id)

    def checkin_session(
        self,
        session_id: str,
        success: bool = True
    ) -> Optional[InstagramSession]:
        now_iso = _now_iso()

        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            if success:
                cursor.execute("""
                    UPDATE instagram_sessions 
                    SET status = 'available',
                        instance_id = NULL,
                        checked_out_at = NULL,
                        checkin_deadline = NULL,
                        last_used_at = ?,
                        success_count = success_count + 1,
                        updated_at = ?
                    WHERE session_id = ?
                """, (now_iso, now_iso, session_id))
            else:
                cursor.execute("""
                    UPDATE instagram_sessions 
                    SET status = 'available',
                        instance_id = NULL,
                        checked_out_at = NULL,
                        checkin_deadline = NULL,
                        last_used_at = ?,
                        failure_count = failure_count + 1,
                        updated_at = ?
                    WHERE session_id = ?
                """, (now_iso, now_iso, session_id))

            conn.commit()

        logger.info(f"Session {session_id} checked in (success={success})")

        return self.get_session(session_id)

    def mark_session_expired(self, session_id: str) -> bool:
        now_iso = _now_iso()

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instagram_sessions 
                SET status = 'expired', updated_at = ?
                WHERE session_id = ?
            """, (now_iso, session_id))
            conn.commit()

            return cursor.rowcount > 0

    def get_session(self, session_id: str) -> Optional[InstagramSession]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM instagram_sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()

            if row:
                return InstagramSession(
                    session_id=row["session_id"],
                    username=row["username"],
                    session_cookie=row["session_cookie"],
                    status=row["status"],
                    instance_id=row["instance_id"],
                    checked_out_at=row["checked_out_at"],
                    checkin_deadline=row["checkin_deadline"],
                    last_used_at=row["last_used_at"],
                    usage_count=row["usage_count"],
                    success_count=row["success_count"],
                    failure_count=row["failure_count"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
        return None

    def get_available_sessions(self) -> List[InstagramSession]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM instagram_sessions 
                WHERE status = 'available'
                ORDER BY usage_count ASC
            """)
            rows = cursor.fetchall()

        sessions = []
        for row in rows:
            sessions.append(InstagramSession(
                session_id=row["session_id"],
                username=row["username"],
                session_cookie=row["session_cookie"],
                status=row["status"],
                instance_id=row["instance_id"],
                checked_out_at=row["checked_out_at"],
                checkin_deadline=row["checkin_deadline"],
                last_used_at=row["last_used_at"],
                usage_count=row["usage_count"],
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            ))
        return sessions

    def get_sessions_by_instance(self, instance_id: str) -> List[InstagramSession]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM instagram_sessions 
                WHERE instance_id = ?
                ORDER BY checked_out_at ASC
            """, (instance_id,))
            rows = cursor.fetchall()

        sessions = []
        for row in rows:
            sessions.append(InstagramSession(
                session_id=row["session_id"],
                username=row["username"],
                session_cookie=row["session_cookie"],
                status=row["status"],
                instance_id=row["instance_id"],
                checked_out_at=row["checked_out_at"],
                checkin_deadline=row["checkin_deadline"],
                last_used_at=row["last_used_at"],
                usage_count=row["usage_count"],
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            ))
        return sessions

    def get_pool_stats(self) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM instagram_sessions 
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as total FROM instagram_sessions")
            total = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT AVG(CAST(success_count AS REAL) / NULLIF(usage_count, 0)) as avg_success_rate
                FROM instagram_sessions 
                WHERE usage_count > 0
            """)
            avg_success_row = cursor.fetchone()
            avg_success_rate = avg_success_row["avg_success_rate"] if avg_success_row and avg_success_row["avg_success_rate"] else None

        return {
            "total": total,
            "available": status_counts.get("available", 0),
            "checked_out": status_counts.get("checked_out", 0),
            "expired": status_counts.get("expired", 0),
            "suspended": status_counts.get("suspended", 0),
            "rotating": status_counts.get("rotating", 0),
            "avg_success_rate": avg_success_rate
        }

    def cleanup_stale_checkouts(self, max_age_seconds: int = 600) -> int:
        now = _now_dt()
        cutoff = now - timedelta(seconds=max_age_seconds)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instagram_sessions 
                SET status = 'available',
                    instance_id = NULL,
                    checked_out_at = NULL,
                    checkin_deadline = NULL,
                    failure_count = failure_count + 1,
                    updated_at = ?
                WHERE status = 'checked_out' 
                AND checkin_deadline < ?
            """, (_now_iso(), cutoff_str))

            cleaned = cursor.rowcount
            conn.commit()

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} stale session checkouts")

        return cleaned


class InstanceRegistry:
    def __init__(self, db: Optional[SessionPoolDB] = None):
        self.db = db or SessionPoolDB()

    def register_instance(
        self,
        instance_id: str,
        instance_type: str = "worker",
        hostname: Optional[str] = None,
        ip_address: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        max_sessions: int = 10
    ) -> Instance:
        now = _now_iso()
        capabilities = capabilities or []

        with self.db._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO instance_registry 
                (instance_id, instance_type, hostname, ip_address, status, capabilities, max_sessions, registered_at, last_heartbeat)
                VALUES (?, ?, ?, ?, 'healthy', ?, ?, ?, ?)
            """, (instance_id, instance_type, hostname, ip_address, json.dumps(capabilities), max_sessions, now, now))
            conn.commit()

        logger.info(f"Instance {instance_id} registered as {instance_type}")

        return self.get_instance(instance_id)

    def heartbeat(self, instance_id: str) -> bool:
        now_iso = _now_iso()

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instance_registry 
                SET last_heartbeat = ?, status = 'healthy'
                WHERE instance_id = ?
            """, (now_iso, instance_id))
            conn.commit()

            return cursor.rowcount > 0

    def update_health_score(self, instance_id: str, health_score: float) -> bool:
        now_iso = _now_iso()
        health_score = max(0.0, min(100.0, health_score))

        if health_score >= 70:
            status = "healthy"
        elif health_score >= 40:
            status = "degraded"
        else:
            status = "unhealthy"

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instance_registry 
                SET health_score = ?, status = ?, last_heartbeat = ?
                WHERE instance_id = ?
            """, (health_score, status, now_iso, instance_id))
            conn.commit()

            return cursor.rowcount > 0

    def get_instance(self, instance_id: str) -> Optional[Instance]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM instance_registry WHERE instance_id = ?", (instance_id,))
            row = cursor.fetchone()

            if row:
                return Instance(
                    instance_id=row["instance_id"],
                    instance_type=row["instance_type"],
                    hostname=row["hostname"],
                    ip_address=row["ip_address"],
                    status=row["status"],
                    capabilities=json.loads(row["capabilities"]),
                    current_sessions=row["current_sessions"],
                    max_sessions=row["max_sessions"],
                    registered_at=row["registered_at"],
                    last_heartbeat=row["last_heartbeat"],
                    health_score=row["health_score"]
                )
        return None

    def get_healthy_instances(
        self,
        instance_type: Optional[str] = None,
        min_health_score: float = 40.0
    ) -> List[Instance]:
        now = _now_dt()
        cutoff = now - timedelta(seconds=INSTANCE_HEARTBEAT_TIMEOUT_SECONDS)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            if instance_type:
                cursor.execute("""
                    SELECT * FROM instance_registry 
                    WHERE status != 'offline'
                    AND last_heartbeat >= ?
                    AND health_score >= ?
                    AND instance_type = ?
                    AND current_sessions < max_sessions
                    ORDER BY health_score DESC, current_sessions ASC
                """, (cutoff_str, min_health_score, instance_type))
            else:
                cursor.execute("""
                    SELECT * FROM instance_registry 
                    WHERE status != 'offline'
                    AND last_heartbeat >= ?
                    AND health_score >= ?
                    AND current_sessions < max_sessions
                    ORDER BY health_score DESC, current_sessions ASC
                """, (cutoff_str, min_health_score))

            rows = cursor.fetchall()

        instances = []
        for row in rows:
            instances.append(Instance(
                instance_id=row["instance_id"],
                instance_type=row["instance_type"],
                hostname=row["hostname"],
                ip_address=row["ip_address"],
                status=row["status"],
                capabilities=json.loads(row["capabilities"]),
                current_sessions=row["current_sessions"],
                max_sessions=row["max_sessions"],
                registered_at=row["registered_at"],
                last_heartbeat=row["last_heartbeat"],
                health_score=row["health_score"]
            ))
        return instances

    def update_session_count(self, instance_id: str, delta: int) -> bool:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instance_registry 
                SET current_sessions = current_sessions + ?
                WHERE instance_id = ?
            """, (delta, instance_id))
            conn.commit()

            return cursor.rowcount > 0

    def mark_instance_offline(self, instance_id: str) -> bool:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instance_registry 
                SET status = 'offline'
                WHERE instance_id = ?
            """, (instance_id,))
            conn.commit()

            return cursor.rowcount > 0

    def cleanup_stale_instances(self, max_age_seconds: int = INSTANCE_HEARTBEAT_TIMEOUT_SECONDS * 3) -> int:
        cutoff = _now_dt() - timedelta(seconds=max_age_seconds)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE instance_registry 
                SET status = 'offline'
                WHERE last_heartbeat < ?
                AND status != 'offline'
            """, (cutoff_str,))

            updated = cursor.rowcount
            conn.commit()

        if updated > 0:
            logger.info(f"Marked {updated} instances as offline")

        return updated

    def get_registry_stats(self) -> Dict[str, Any]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT status, COUNT(*) as count 
                FROM instance_registry 
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as total FROM instance_registry")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT AVG(health_score) as avg_health FROM instance_registry")
            avg_health_row = cursor.fetchone()
            avg_health = avg_health_row["avg_health"] if avg_health_row and avg_health_row["avg_health"] else None

        return {
            "total": total,
            "healthy": status_counts.get("healthy", 0),
            "degraded": status_counts.get("degraded", 0),
            "unhealthy": status_counts.get("unhealthy", 0),
            "offline": status_counts.get("offline", 0),
            "avg_health_score": avg_health
        }


class DistributedLock:
    def __init__(self, db: Optional[SessionPoolDB] = None):
        self.db = db or SessionPoolDB()

    def acquire_lock(
        self,
        resource_name: str,
        instance_id: str,
        owner_id: str,
        ttl_seconds: int = 300
    ) -> Optional[DistributedLockData]:
        now = _now_dt()
        now_iso = _now_iso()
        expires = now + timedelta(seconds=ttl_seconds)
        expires_iso = expires.strftime("%Y-%m-%d %H:%M:%S")
        acquire_token = hashlib.sha256(f"{resource_name}:{instance_id}:{owner_id}:{now_iso}".encode()).hexdigest()[:16]

        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM distributed_locks 
                WHERE resource_name = ? 
                AND status = 'acquired'
                AND expires_at > ?
            """, (resource_name, now_iso))

            existing = cursor.fetchone()

            if existing:
                if existing["instance_id"] == instance_id and existing["owner_id"] == owner_id:
                    cursor.execute("""
                        UPDATE distributed_locks 
                        SET acquire_count = acquire_count + 1,
                            expires_at = ?,
                            status = 'acquired'
                        WHERE lock_id = ?
                    """, (expires_iso, existing["lock_id"]))
                    conn.commit()

                    logger.info(f"Reentrant lock acquired on {resource_name} by {owner_id}")
                    return self.get_lock(existing["lock_id"])
                return None

            lock_id = f"lock_{uuid4().hex[:12]}"

            cursor.execute("""
                INSERT INTO distributed_locks 
                (lock_id, resource_name, instance_id, owner_id, status, acquire_token, acquire_count, acquired_at, expires_at)
                VALUES (?, ?, ?, ?, 'acquired', ?, 1, ?, ?)
            """, (lock_id, resource_name, instance_id, owner_id, acquire_token, now_iso, expires_iso))
            conn.commit()

        logger.info(f"Lock acquired on {resource_name} by {owner_id}")

        return self.get_lock(lock_id)

    def release_lock(
        self,
        resource_name: str,
        instance_id: str,
        owner_id: str
    ) -> bool:
        now_iso = _now_iso()

        with self.db._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE distributed_locks 
                SET status = 'released', 
                    released_at = ?,
                    acquire_count = acquire_count - 1
                WHERE resource_name = ?
                AND instance_id = ?
                AND owner_id = ?
                AND status = 'acquired'
                AND acquire_count <= 1
            """, (now_iso, resource_name, instance_id, owner_id))

            if cursor.rowcount > 0:
                cursor.execute("""
                    DELETE FROM distributed_locks 
                    WHERE resource_name = ?
                    AND status = 'released'
                    AND acquire_count <= 0
                """, (resource_name,))
                conn.commit()

                logger.info(f"Lock released on {resource_name} by {owner_id}")
                return True

            cursor.execute("""
                UPDATE distributed_locks 
                SET acquire_count = acquire_count - 1
                WHERE resource_name = ?
                AND instance_id = ?
                AND owner_id = ?
                AND status = 'acquired'
            """, (resource_name, instance_id, owner_id))
            conn.commit()

            logger.info(f"Reentrant lock decremented on {resource_name} by {owner_id}")
            return True

    def get_active_lock(self, resource_name: str) -> Optional[DistributedLockData]:
        now_iso = _now_iso()

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM distributed_locks 
                WHERE resource_name = ? 
                AND status = 'acquired'
                AND expires_at > ?
            """, (resource_name, now_iso))
            row = cursor.fetchone()

            if row:
                return DistributedLockData(
                    lock_id=row["lock_id"],
                    resource_name=row["resource_name"],
                    instance_id=row["instance_id"],
                    owner_id=row["owner_id"],
                    status=row["status"],
                    acquire_token=row["acquire_token"],
                    acquire_count=row["acquire_count"],
                    acquired_at=row["acquired_at"],
                    expires_at=row["expires_at"],
                    released_at=row["released_at"]
                )
        return None

    def get_lock(self, lock_id: str) -> Optional[DistributedLockData]:
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM distributed_locks WHERE lock_id = ?", (lock_id,))
            row = cursor.fetchone()

            if row:
                return DistributedLockData(
                    lock_id=row["lock_id"],
                    resource_name=row["resource_name"],
                    instance_id=row["instance_id"],
                    owner_id=row["owner_id"],
                    status=row["status"],
                    acquire_token=row["acquire_token"],
                    acquire_count=row["acquire_count"],
                    acquired_at=row["acquired_at"],
                    expires_at=row["expires_at"],
                    released_at=row["released_at"]
                )
        return None

    def cleanup_expired_locks(self) -> int:
        now_iso = _now_iso()

        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE distributed_locks 
                SET status = 'expired'
                WHERE status = 'acquired'
                AND expires_at < ?
            """, (now_iso,))

            expired = cursor.rowcount

            cursor.execute("""
                DELETE FROM distributed_locks 
                WHERE status IN ('released', 'expired')
            """)
            conn.commit()

        if expired > 0:
            logger.info(f"Cleaned up {expired} expired locks")

        return expired

    @contextmanager
    def lock(self, resource_name: str, instance_id: str, owner_id: str, ttl_seconds: int = 300):
        lock_obj = self.acquire_lock(resource_name, instance_id, owner_id, ttl_seconds)
        if not lock_obj:
            raise RuntimeError(f"Could not acquire lock on {resource_name}")
        try:
            yield lock_obj
        finally:
            self.release_lock(resource_name, instance_id, owner_id)


class HealthRouter:
    def __init__(
        self,
        session_pool: Optional[SessionPool] = None,
        instance_registry: Optional[InstanceRegistry] = None
    ):
        self.session_pool = session_pool or SessionPool()
        self.instance_registry = instance_registry or InstanceRegistry()

    def route_to_healthy_instance(
        self,
        instance_type: Optional[str] = None,
        min_health_score: float = 40.0
    ) -> Optional[Instance]:
        instances = self.instance_registry.get_healthy_instances(
            instance_type=instance_type,
            min_health_score=min_health_score
        )

        if not instances:
            return None

        return random.choice(instances)

    def route_session(
        self,
        instance_id: Optional[str] = None,
        instance_type: Optional[str] = None,
        min_health_score: float = 40.0
    ) -> Optional[InstagramSession]:
        if instance_id:
            session = self.session_pool.checkout_session(instance_id)
            if session:
                return session

        if instance_type:
            healthy_instances = self.instance_registry.get_healthy_instances(
                instance_type=instance_type,
                min_health_score=min_health_score
            )

            for inst in healthy_instances:
                session = self.session_pool.checkout_session(inst.instance_id)
                if session:
                    return session

        return self.session_pool.checkout_session(instance_id or "default")

    def get_health_summary(self) -> Dict[str, Any]:
        pool_stats = self.session_pool.get_pool_stats()
        registry_stats = self.instance_registry.get_registry_stats()

        return {
            "sessions": pool_stats,
            "instances": registry_stats,
            "timestamp": _now_iso()
        }

    def perform_health_checks(self) -> Dict[str, int]:
        cleaned_sessions = self.session_pool.cleanup_stale_checkouts()
        cleaned_instances = self.instance_registry.cleanup_stale_instances()
        cleaned_locks = self.cleanup_expired_locks()

        return {
            "sessions_cleaned": cleaned_sessions,
            "instances_marked_offline": cleaned_instances,
            "locks_cleaned": cleaned_locks
        }

    def cleanup_expired_locks(self) -> int:
        db = SessionPoolDB()
        lock_manager = DistributedLock(db)
        return lock_manager.cleanup_expired_locks()


_global_session_pool: Optional[SessionPool] = None
_global_instance_registry: Optional[InstanceRegistry] = None
_global_distributed_lock: Optional[DistributedLock] = None
_global_health_router: Optional[HealthRouter] = None
_lock = threading.Lock()


def get_session_pool() -> SessionPool:
    global _global_session_pool
    if _global_session_pool is None:
        with _lock:
            if _global_session_pool is None:
                _global_session_pool = SessionPool()
    return _global_session_pool


def get_instance_registry() -> InstanceRegistry:
    global _global_instance_registry
    if _global_instance_registry is None:
        with _lock:
            if _global_instance_registry is None:
                _global_instance_registry = InstanceRegistry()
    return _global_instance_registry


def get_distributed_lock() -> DistributedLock:
    global _global_distributed_lock
    if _global_distributed_lock is None:
        with _lock:
            if _global_distributed_lock is None:
                _global_distributed_lock = DistributedLock()
    return _global_distributed_lock


def get_health_router() -> HealthRouter:
    global _global_health_router
    if _global_health_router is None:
        with _lock:
            if _global_health_router is None:
                _global_health_router = HealthRouter()
    return _global_health_router
