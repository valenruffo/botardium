import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, Any, List


class RateLimiter:
    def __init__(self, db_path: str = ".tmp/rate_limits.db"):
        os.makedirs(os.path.dirname(db_path) or ".tmp", exist_ok=True)
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                limit_count INTEGER NOT NULL DEFAULT 50,
                window_seconds INTEGER NOT NULL DEFAULT 3600,
                current_count INTEGER NOT NULL DEFAULT 0,
                window_start TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(account_id, action_type)
            )
        """)
        conn.commit()
        conn.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _is_window_expired(self, window_start: str, window_seconds: int) -> bool:
        start = datetime.fromisoformat(window_start)
        elapsed = (datetime.utcnow() - start).total_seconds()
        return elapsed >= window_seconds
    
    def check_limit(self, account_id: int, action_type: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT limit_count, current_count, window_start, window_seconds 
               FROM rate_limits WHERE account_id = ? AND action_type = ?""",
            (account_id, action_type)
        )
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return True
        
        limit_count = row['limit_count']
        current_count = row['current_count']
        window_start = row['window_start']
        window_seconds = row['window_seconds']
        
        if self._is_window_expired(window_start, window_seconds):
            conn.close()
            return True
        
        conn.close()
        return current_count < limit_count
    
    def increment(self, account_id: int, action_type: str, limit_count: int = 50, window_seconds: int = 3600):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT id, current_count, window_start, window_seconds 
               FROM rate_limits WHERE account_id = ? AND action_type = ?""",
            (account_id, action_type)
        )
        row = cursor.fetchone()
        
        if not row:
            cursor.execute(
                """INSERT INTO rate_limits (account_id, action_type, limit_count, window_seconds, current_count, window_start)
                   VALUES (?, ?, ?, ?, 1, datetime('now'))""",
                (account_id, action_type, limit_count, window_seconds)
            )
        else:
            window_start = row['window_start']
            window_seconds = row['window_seconds']
            
            if self._is_window_expired(window_start, window_seconds):
                cursor.execute(
                    """UPDATE rate_limits SET current_count = 1, window_start = datetime('now') 
                       WHERE account_id = ? AND action_type = ?""",
                    (account_id, action_type)
                )
            else:
                cursor.execute(
                    """UPDATE rate_limits SET current_count = current_count + 1 
                       WHERE account_id = ? AND action_type = ?""",
                    (account_id, action_type)
                )
        
        conn.commit()
        conn.close()
    
    def get_status(self, account_id: int) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT action_type, limit_count, current_count, window_start, window_seconds
               FROM rate_limits WHERE account_id = ?""",
            (account_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        statuses = {}
        now = datetime.utcnow()
        
        for row in rows:
            action = row['action_type']
            window_start = datetime.fromisoformat(row['window_start'])
            elapsed = (now - window_start).total_seconds()
            remaining_seconds = max(0, row['window_seconds'] - elapsed)
            
            statuses[action] = {
                "limit_count": row['limit_count'],
                "current_count": row['current_count'],
                "remaining": row['limit_count'] - row['current_count'],
                "window_seconds": row['window_seconds'],
                "remaining_seconds": int(remaining_seconds),
                "window_expired": elapsed >= row['window_seconds']
            }
        
        return statuses
    
    def set_limits(self, account_id: int, action_type: str, limit_count: int, window_seconds: int):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT OR REPLACE INTO rate_limits (account_id, action_type, limit_count, window_seconds, current_count, window_start)
               VALUES (?, ?, ?, ?, 0, datetime('now'))""",
            (account_id, action_type, limit_count, window_seconds)
        )
        conn.commit()
        conn.close()
