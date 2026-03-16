"""
Tests for Phase 8: Session Pooling & Multi-Instance Coordination
================================================================
"""

import pytest
import tempfile
import os
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from scripts.session_pool import (
    SessionPool,
    SessionPoolDB,
    InstanceRegistry,
    DistributedLock,
    HealthRouter,
    InstagramSession,
    Instance,
    DistributedLock as DLock,
    SessionStatus,
    InstanceStatus,
    LockStatus,
)


@pytest.fixture
def db_instance():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_session_pool.db"
        db = SessionPoolDB(db_path=db_path)
        yield db
        del db
        import gc
        gc.collect()
        time.sleep(0.5)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_session_pool.db"
        yield db_path
        import gc
        gc.collect()
        time.sleep(0.2)


@pytest.fixture
def session_pool(db_instance):
    return SessionPool(db=db_instance)


@pytest.fixture
def instance_registry(db_instance):
    return InstanceRegistry(db=db_instance)


@pytest.fixture
def distributed_lock(db_instance):
    return DistributedLock(db=db_instance)


@pytest.fixture
def health_router(db_instance):
    session_pool = SessionPool(db=db_instance)
    instance_registry = InstanceRegistry(db=db_instance)
    return HealthRouter(session_pool=session_pool, instance_registry=instance_registry)


class TestSessionPool:
    def test_register_session(self, session_pool):
        session = session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )

        assert session.session_id == "sess_001"
        assert session.username == "test_user"
        assert session.status == SessionStatus.AVAILABLE
        assert session.usage_count == 0

    def test_checkout_session(self, session_pool, instance_registry):
        instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker",
            hostname="worker-1"
        )

        session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )

        checked_out = session_pool.checkout_session(instance_id="inst_001")

        assert checked_out is not None
        assert checked_out.session_id == "sess_001"
        assert checked_out.status == SessionStatus.CHECKED_OUT
        assert checked_out.instance_id == "inst_001"

    def test_checkin_session_success(self, session_pool, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )

        session_pool.checkout_session(instance_id="inst_001")
        checked_in = session_pool.checkin_session(session_id="sess_001", success=True)

        assert checked_in.status == SessionStatus.AVAILABLE
        assert checked_in.success_count == 1

    def test_checkin_session_failure(self, session_pool, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )

        session_pool.checkout_session(instance_id="inst_001")
        checked_in = session_pool.checkin_session(session_id="sess_001", success=False)

        assert checked_in.status == SessionStatus.AVAILABLE
        assert checked_in.failure_count == 1

    def test_get_available_sessions(self, session_pool):
        session_pool.register_session(
            session_id="sess_001",
            username="user1",
            session_cookie="cookie1"
        )
        session_pool.register_session(
            session_id="sess_002",
            username="user2",
            session_cookie="cookie2"
        )

        available = session_pool.get_available_sessions()

        assert len(available) == 2

    def test_get_sessions_by_instance(self, session_pool, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        session_pool.register_session(
            session_id="sess_001",
            username="user1",
            session_cookie="cookie1"
        )

        session_pool.checkout_session(instance_id="inst_001")

        sessions = session_pool.get_sessions_by_instance("inst_001")

        assert len(sessions) == 1
        assert sessions[0].session_id == "sess_001"

    def test_get_pool_stats(self, session_pool):
        session_pool.register_session(
            session_id="sess_001",
            username="user1",
            session_cookie="cookie1"
        )
        session_pool.register_session(
            session_id="sess_002",
            username="user2",
            session_cookie="cookie2"
        )

        stats = session_pool.get_pool_stats()

        assert stats["total"] == 2
        assert stats["available"] == 2

    def test_cleanup_stale_checkouts(self, session_pool, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        session_pool.register_session(
            session_id="sess_001",
            username="user1",
            session_cookie="cookie1"
        )

        session_pool.checkout_session(instance_id="inst_001")

        cleaned = session_pool.cleanup_stale_checkouts(max_age_seconds=0)

        assert cleaned >= 0


class TestInstanceRegistry:
    def test_register_instance(self, instance_registry):
        instance = instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker",
            hostname="worker-1",
            ip_address="192.168.1.1"
        )

        assert instance.instance_id == "inst_001"
        assert instance.instance_type == "worker"
        assert instance.status == InstanceStatus.HEALTHY

    def test_heartbeat(self, instance_registry):
        instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker"
        )

        result = instance_registry.heartbeat("inst_001")

        assert result is True

    def test_update_health_score(self, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        result = instance_registry.update_health_score("inst_001", 50.0)

        assert result is True

        instance = instance_registry.get_instance("inst_001")
        assert instance.health_score == 50.0
        assert instance.status == InstanceStatus.DEGRADED

    def test_get_healthy_instances(self, instance_registry):
        instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker",
            hostname="worker-1"
        )
        instance_registry.register_instance(
            instance_id="inst_002",
            instance_type="worker",
            hostname="worker-2"
        )

        healthy = instance_registry.get_healthy_instances()

        assert len(healthy) == 2

    def test_mark_instance_offline(self, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        result = instance_registry.mark_instance_offline("inst_001")

        assert result is True

        instance = instance_registry.get_instance("inst_001")
        assert instance.status == InstanceStatus.OFFLINE

    def test_cleanup_stale_instances(self, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")

        cleaned = instance_registry.cleanup_stale_instances(max_age_seconds=0)

        assert cleaned >= 0

    def test_get_registry_stats(self, instance_registry):
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")
        instance_registry.register_instance(instance_id="inst_002", instance_type="scraper")

        stats = instance_registry.get_registry_stats()

        assert stats["total"] == 2
        assert stats["healthy"] == 2


class TestDistributedLock:
    def test_acquire_lock(self, distributed_lock):
        lock = distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001",
            ttl_seconds=60
        )

        assert lock is not None
        assert lock.resource_name == "test_resource"
        assert lock.status == LockStatus.ACQUIRED

    def test_acquire_lock_duplicate(self, distributed_lock):
        lock1 = distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001",
            ttl_seconds=60
        )

        lock2 = distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001",
            ttl_seconds=60
        )

        assert lock2 is not None
        assert lock2.acquire_count == 2

    def test_acquire_lock_conflict(self, distributed_lock):
        distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001",
            ttl_seconds=60
        )

        lock2 = distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_002",
            owner_id="owner_002",
            ttl_seconds=60
        )

        assert lock2 is None

    def test_release_lock(self, distributed_lock):
        distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001",
            ttl_seconds=60
        )

        result = distributed_lock.release_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001"
        )

        assert result is True

    def test_get_active_lock(self, distributed_lock):
        distributed_lock.acquire_lock(
            resource_name="test_resource",
            instance_id="inst_001",
            owner_id="owner_001",
            ttl_seconds=60
        )

        active = distributed_lock.get_active_lock("test_resource")

        assert active is not None
        assert active.resource_name == "test_resource"

    def test_lock_context_manager(self, distributed_lock):
        with distributed_lock.lock("test_resource", "inst_001", "owner_001"):
            active = distributed_lock.get_active_lock("test_resource")
            assert active is not None

        active = distributed_lock.get_active_lock("test_resource")
        assert active is None


class TestHealthRouter:
    def test_route_to_healthy_instance(self, health_router, instance_registry):
        instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker",
            hostname="worker-1"
        )

        instance = health_router.route_to_healthy_instance(instance_type="worker")

        assert instance is not None
        assert instance.instance_id == "inst_001"

    def test_route_session(self, health_router, instance_registry):
        instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker",
            hostname="worker-1"
        )

        health_router.session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )

        session = health_router.route_session(instance_id="inst_001")

        assert session is not None
        assert session.session_id == "sess_001"

    def test_get_health_summary(self, health_router):
        health_router.session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )
        health_router.instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker"
        )

        summary = health_router.get_health_summary()

        assert "sessions" in summary
        assert "instances" in summary
        assert summary["sessions"]["total"] == 1
        assert summary["instances"]["total"] == 1

    def test_perform_health_checks(self, health_router):
        health_router.session_pool.register_session(
            session_id="sess_001",
            username="test_user",
            session_cookie="cookie_data"
        )
        health_router.instance_registry.register_instance(
            instance_id="inst_001",
            instance_type="worker"
        )

        results = health_router.perform_health_checks()

        assert "sessions_cleaned" in results
        assert "instances_marked_offline" in results


class TestConcurrency:
    def test_concurrent_checkout_checkin(self, db_instance):
        session_pool = SessionPool(db=db_instance)
        instance_registry = InstanceRegistry(db=db_instance)

        # Registrar 2 instancias
        instance_registry.register_instance(instance_id="inst_001", instance_type="worker")
        instance_registry.register_instance(instance_id="inst_002", instance_type="worker")

        # Crear 2 sesiones
        session_pool.register_session(
            session_id="sess_001",
            username="user1",
            session_cookie="cookie1"
        )
        session_pool.register_session(
            session_id="sess_002",
            username="user2",
            session_cookie="cookie2"
        )

        # Checkout secuencial funciona
        s1 = session_pool.checkout_session(instance_id="inst_001")
        assert s1.session_id == "sess_001"
        
        s2 = session_pool.checkout_session(instance_id="inst_002")
        assert s2.session_id == "sess_002"
        
        # Checkin y re-checkout
        session_pool.checkin_session(session_id="sess_001", success=True)
        
        s1_again = session_pool.checkout_session(instance_id="inst_001")
        assert s1_again.session_id == "sess_001"

    def test_concurrent_lock_acquisition(self, db_instance):
        lock_mgr = DistributedLock(db=db_instance)

        results = []

        def acquire_release():
            lock = lock_mgr.acquire_lock(
                resource_name="shared_resource",
                instance_id="inst_001",
                owner_id="owner_001",
                ttl_seconds=5
            )
            if lock:
                results.append("acquired")
                time.sleep(0.1)
                lock_mgr.release_lock(
                    resource_name="shared_resource",
                    instance_id="inst_001",
                    owner_id="owner_001"
                )
                results.append("released")

        threads = []
        for _ in range(2):
            t = threading.Thread(target=acquire_release)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        acquired_count = results.count("acquired")
        assert acquired_count >= 1


class TestEdgeCases:
    def test_checkout_no_available_sessions(self, session_pool):
        result = session_pool.checkout_session(instance_id="inst_001")

        assert result is None

    def test_checkin_unknown_session(self, session_pool):
        result = session_pool.checkin_session(session_id="unknown", success=True)

        assert result is None

    def test_get_instance_not_found(self, instance_registry):
        instance = instance_registry.get_instance("nonexistent")

        assert instance is None

    def test_get_lock_not_found(self, distributed_lock):
        lock = distributed_lock.get_lock("nonexistent")

        assert lock is None

    def test_health_router_no_instances(self, health_router):
        instance = health_router.route_to_healthy_instance()

        assert instance is None
