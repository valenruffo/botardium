"""
Tests for Phase 6: Observabilidad y Operaciones de Escala
============================================================
Verifies structured logging, metrics collection, rate limiting, and system monitoring.
"""

import unittest
import os
import sys
import json
import sqlite3
import tempfile
import shutil
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.observabilidad.structured_logger import (
    setup_logger,
    generate_trace_id,
    get_trace_id,
    set_trace_id,
    clear_trace_id,
    TraceContext,
    trace_id_var
)

from scripts.observabilidad.metrics_collector import MetricsCollector

from scripts.observabilidad.rate_limiter import RateLimiter

from scripts.observabilidad.system_monitor import SystemMonitor


class TestTraceIDPropagation(unittest.TestCase):
    """Test trace ID propagation through ContextVar."""
    
    def setUp(self):
        self.log_dir = tempfile.mkdtemp()
        clear_trace_id()
    
    def tearDown(self):
        shutil.rmtree(self.log_dir, ignore_errors=True)
    
    def test_generate_trace_id_is_uuid(self):
        """Trace ID generated is a valid UUID."""
        trace_id = generate_trace_id()
        self.assertIsNotNone(trace_id)
        self.assertEqual(len(trace_id), 36)
        self.assertEqual(trace_id.count('-'), 4)
    
    def test_trace_id_set_and_get(self):
        """Can set and get trace ID."""
        test_id = "test-trace-123"
        set_trace_id(test_id)
        self.assertEqual(get_trace_id(), test_id)
    
    def test_trace_id_propagation_in_context(self):
        """Trace ID propagates through TraceContext."""
        test_id = "propagated-trace-456"
        with TraceContext(test_id):
            self.assertEqual(get_trace_id(), test_id)
            self._helper_function()
    
    def _helper_function(self):
        """Helper that should inherit trace_id."""
        self.assertEqual(get_trace_id(), "propagated-trace-456")
    
    def test_trace_id_clear(self):
        """Can clear trace ID."""
        set_trace_id("test-id")
        clear_trace_id()
        self.assertIsNone(get_trace_id())
    
    def test_logger_output_contains_trace_id(self):
        """Logger output contains trace_id in JSON."""
        logger = setup_logger("test_trace", log_dir=self.log_dir)
        set_trace_id("logger-test-789")
        
        import io
        import logging
        
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                return json.dumps({
                    "trace_id": get_trace_id(),
                    "message": record.getMessage()
                })
        
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        
        logger.info("Test message")
        
        output = stream.getvalue()
        self.assertIn("logger-test-789", output)


class TestMetricsCollector(unittest.TestCase):
    """Test metrics collection with SQLite."""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.collector = MetricsCollector(db_path=self.db_path)
    
    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except:
            pass
    
    def test_metrics_counter_increment(self):
        """Counter increments correctly."""
        self.collector.incr("test_counter", delta=5)
        stats = self.collector.get_stats("test_counter", window_minutes=60)
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["sum"], 5.0)
    
    def test_metrics_observation(self):
        """Histogram observation records value."""
        self.collector.observe("response_time", 150.5)
        self.collector.observe("response_time", 200.3)
        
        stats = self.collector.get_stats("response_time", window_minutes=60)
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["sum"], 350.8)
    
    def test_metrics_gauge(self):
        """Gauge sets current value."""
        self.collector.gauge("active_workers", 5)
        self.collector.gauge("active_workers", 7)
        
        gauges = self.collector.get_all_gauges()
        self.assertEqual(gauges["active_workers"], 7)
    
    def test_metrics_get_stats_with_window(self):
        """get_stats respects time window."""
        self.collector.incr("window_test", delta=1)
        
        stats = self.collector.get_stats("window_test", window_minutes=60)
        self.assertEqual(stats["count"], 1)
        
        stats_empty = self.collector.get_stats("nonexistent", window_minutes=60)
        self.assertEqual(stats_empty["count"], 0)
    
    def test_metrics_with_workspace_id(self):
        """Metrics can be tagged with workspace_id."""
        self.collector.incr("dm_sent", delta=1, workspace_id=1)
        self.collector.incr("dm_sent", delta=1, workspace_id=2)
        
        stats_w1 = self.collector.get_stats("dm_sent", window_minutes=60)
        self.assertEqual(stats_w1["count"], 2)


class TestRateLimiter(unittest.TestCase):
    """Test rate limiting functionality."""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.ratelimiter = RateLimiter(db_path=self.db_path)
    
    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except:
            pass
    
    def test_check_limit_allows_under_limit(self):
        """Check limit returns True when under limit."""
        allowed = self.ratelimiter.check_limit(account_id=1, action_type="dm")
        self.assertTrue(allowed)
    
    def test_check_limit_blocks_over_limit(self):
        """Check limit returns False when over limit."""
        self.ratelimiter.set_limits(account_id=1, action_type="test", limit_count=2, window_seconds=3600)
        
        self.assertTrue(self.ratelimiter.check_limit(1, "test"))
        self.ratelimiter.increment(1, "test", limit_count=2)
        
        self.assertTrue(self.ratelimiter.check_limit(1, "test"))
        self.ratelimiter.increment(1, "test", limit_count=2)
        
        self.assertFalse(self.ratelimiter.check_limit(1, "test"))
    
    def test_increment_counter(self):
        """Increment increases counter correctly."""
        self.ratelimiter.increment(account_id=1, action_type="dm", limit_count=50)
        self.ratelimiter.increment(account_id=1, action_type="dm", limit_count=50)
        
        status = self.ratelimiter.get_status(1)
        self.assertEqual(status["dm"]["current_count"], 2)
    
    def test_rate_limit_window_expiration(self):
        """Rate limit resets after window expires."""
        self.ratelimiter.set_limits(account_id=1, action_type="expire_test", limit_count=1, window_seconds=1)
        
        self.assertTrue(self.ratelimiter.check_limit(1, "expire_test"))
        self.ratelimiter.increment(1, "expire_test", limit_count=1)
        self.assertFalse(self.ratelimiter.check_limit(1, "expire_test"))
        
        import time
        time.sleep(1.1)
        
        self.assertTrue(self.ratelimiter.check_limit(1, "expire_test"))
    
    def test_get_status_returns_all_actions(self):
        """get_status returns all action types for account."""
        self.ratelimiter.set_limits(1, "dm", 50, 3600)
        self.ratelimiter.set_limits(1, "follow", 200, 3600)
        self.ratelimiter.set_limits(1, "like", 300, 3600)
        
        status = self.ratelimiter.get_status(1)
        
        self.assertIn("dm", status)
        self.assertIn("follow", status)
        self.assertIn("like", status)


class TestHealthCheckJSONOutput(unittest.TestCase):
    """Test system monitor health check output."""
    
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.monitor = SystemMonitor(db_path=self.db_path)
    
    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except:
            pass
    
    def test_health_check_json_format(self):
        """Health check returns valid JSON."""
        result = self.monitor.get_health_status()
        
        self.assertIn("status", result)
        self.assertIn("timestamp", result)
        self.assertIn("checks", result)
    
    def test_health_check_has_required_fields(self):
        """Health check has all required fields."""
        result = self.monitor.get_health_status()
        
        checks = result["checks"]
        self.assertIn("database", checks)
        self.assertIn("stale_jobs", checks)
        self.assertIn("rate_limits", checks)
    
    def test_check_database_healthy(self):
        """Database check returns healthy status."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()
        
        result = self.monitor.check_database()
        self.assertEqual(result["status"], "healthy")
        self.assertIn("test", result["details"]["tables"])
    
    def test_check_database_unhealthy_missing(self):
        """Database check returns unhealthy for missing db."""
        monitor = SystemMonitor(db_path="/nonexistent/path.db")
        result = monitor.check_database()
        self.assertEqual(result["status"], "unhealthy")
    
    def test_health_check_json_output_valid(self):
        """get_json_health returns valid JSON string."""
        json_output = self.monitor.get_json_health()
        
        parsed = json.loads(json_output)
        self.assertIn("status", parsed)
        self.assertIn("timestamp", parsed)
        self.assertIn("checks", parsed)


if __name__ == "__main__":
    unittest.main()
