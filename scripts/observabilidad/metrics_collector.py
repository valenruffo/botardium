import sqlite3
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from contextvars import ContextVar
from uuid import uuid4


trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class MetricsCollector:
    def __init__(self, db_path: str = ".tmp/metrics.db"):
        os.makedirs(os.path.dirname(db_path) or ".tmp", exist_ok=True)
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                metric_type TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                workspace_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_name_time 
            ON metrics(metric_name, created_at)
        """)
        conn.commit()
        conn.close()
    
    def _get_trace_id(self) -> str:
        return trace_id_var.get() or str(uuid4())
    
    def incr(self, name: str, delta: float = 1.0, workspace_id: Optional[int] = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO metrics (trace_id, metric_type, metric_name, value, workspace_id, created_at) VALUES (?, 'counter', ?, ?, ?, ?)",
            (self._get_trace_id(), name, delta, workspace_id, _now_iso())
        )
        conn.commit()
        conn.close()
    
    def observe(self, name: str, value: float, workspace_id: Optional[int] = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO metrics (trace_id, metric_type, metric_name, value, workspace_id, created_at) VALUES (?, 'histogram', ?, ?, ?, ?)",
            (self._get_trace_id(), name, value, workspace_id, _now_iso())
        )
        conn.commit()
        conn.close()
    
    def gauge(self, name: str, value: float, workspace_id: Optional[int] = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO metrics (trace_id, metric_type, metric_name, value, workspace_id, created_at) VALUES (?, 'gauge', ?, ?, ?, ?)",
            (self._get_trace_id(), name, value, workspace_id, _now_iso())
        )
        conn.commit()
        conn.close()
    
    def get_stats(self, name: str, window_minutes: int = 60) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(value), 0) as sum,
                COALESCE(MIN(value), 0) as min,
                COALESCE(MAX(value), 0) as max,
                COALESCE(AVG(value), 0) as avg
            FROM metrics 
            WHERE metric_name = ? AND created_at >= ?
        """, (name, cutoff_str))
        
        row = cursor.fetchone()
        conn.close()
        
        return {
            "metric_name": name,
            "window_minutes": window_minutes,
            "count": row[0] or 0,
            "sum": row[1] or 0.0,
            "min": row[2] or 0.0,
            "max": row[3] or 0.0,
            "avg": row[4] or 0.0
        }
    
    def get_all_gauges(self, window_minutes: int = 60) -> Dict[str, float]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            SELECT m.metric_name, m.value
            FROM metrics m
            INNER JOIN (
                SELECT metric_name, MAX(created_at) as max_created
                FROM metrics 
                WHERE metric_type = 'gauge' AND created_at >= ?
                GROUP BY metric_name
            ) latest ON m.metric_name = latest.metric_name AND m.created_at = latest.max_created
        """, (cutoff_str,))
        
        results = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        
        return results
