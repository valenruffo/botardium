import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


class SystemMonitor:
    def __init__(self, db_path: str = "database/botardium.db"):
        self.db_path = db_path
    
    def check_database(self) -> Dict[str, Any]:
        if not os.path.exists(self.db_path):
            return {
                "status": "unhealthy",
                "details": {"error": "Database file not found"}
            }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            table_counts = {}
            for table in tables:
                if table != 'sqlite_sequence':
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    table_counts[table] = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "status": "healthy",
                "details": {
                    "db_path": self.db_path,
                    "tables": tables,
                    "table_counts": table_counts
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
    
    def check_stale_jobs(self, threshold_minutes: int = 60) -> Dict[str, Any]:
        if not os.path.exists(self.db_path):
            return {
                "status": "unhealthy",
                "details": {"error": "Database file not found"}
            }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            threshold = datetime.utcnow() - timedelta(minutes=threshold_minutes)
            
            cursor.execute(
                """SELECT job_id, job_type, workspace_id, status, started_at, checkpoint
                   FROM jobs 
                   WHERE started_at IS NOT NULL 
                   AND started_at < ?
                   AND status IN ('pending', 'running', 'processing')""",
                (threshold.isoformat(),)
            )
            
            stale_jobs = []
            for row in cursor.fetchall():
                stale_jobs.append({
                    "job_id": row[0],
                    "job_type": row[1],
                    "workspace_id": row[2],
                    "status": row[3],
                    "started_at": row[4],
                    "checkpoint": row[5]
                })
            
            conn.close()
            
            return {
                "status": "healthy" if len(stale_jobs) == 0 else "warning",
                "details": {
                    "threshold_minutes": threshold_minutes,
                    "stale_job_count": len(stale_jobs),
                    "stale_jobs": stale_jobs[:10]
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
    
    def check_rate_limits(self) -> Dict[str, Any]:
        rate_db = ".tmp/rate_limits.db"
        
        if not os.path.exists(rate_db):
            return {
                "status": "healthy",
                "details": {"message": "No rate limits configured"}
            }
        
        try:
            conn = sqlite3.connect(rate_db)
            cursor = conn.cursor()
            
            cursor.execute(
                """SELECT account_id, action_type, limit_count, current_count, window_start, window_seconds
                   FROM rate_limits"""
            )
            
            rate_status = []
            now = datetime.utcnow()
            
            for row in cursor.fetchall():
                account_id = row[0]
                window_start = datetime.fromisoformat(row[4])
                elapsed = (now - window_start).total_seconds()
                remaining = row[2] - row[3]
                
                rate_status.append({
                    "account_id": account_id,
                    "action_type": row[1],
                    "limit_count": row[2],
                    "current_count": row[3],
                    "remaining": remaining,
                    "window_expired": elapsed >= row[5],
                    "usage_percent": (row[3] / row[2] * 100) if row[2] > 0 else 0
                })
            
            conn.close()
            
            near_limit = [r for r in rate_status if r['usage_percent'] >= 80]
            
            return {
                "status": "warning" if near_limit else "healthy",
                "details": {
                    "total_limits": len(rate_status),
                    "near_limit_count": len(near_limit),
                    "rate_limits": rate_status[:20]
                }
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
    
    def get_health_status(self) -> Dict[str, Any]:
        db_check = self.check_database()
        stale_jobs_check = self.check_stale_jobs()
        rate_limits_check = self.check_rate_limits()
        
        overall_status = "healthy"
        if (db_check["status"] != "healthy" or 
            stale_jobs_check["status"] == "unhealthy" or 
            rate_limits_check["status"] == "unhealthy"):
            overall_status = "unhealthy"
        elif (stale_jobs_check["status"] == "warning" or 
              rate_limits_check["status"] == "warning"):
            overall_status = "warning"
        
        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "checks": {
                "database": db_check,
                "stale_jobs": stale_jobs_check,
                "rate_limits": rate_limits_check
            }
        }
    
    def get_json_health(self) -> str:
        return json.dumps(self.get_health_status(), indent=2)
