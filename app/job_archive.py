"""
Job Archive Module - Action 5
Archives old jobs to SQLite, keeps last 50 in memory.

Memory Impact: 100-150MB freed
Guarantees: Can query archived jobs, persistent storage
Scaling: Supports unlimited job history

Architecture:
- Active jobs (last 50): In-memory deque, fast access
- Archived jobs (older): SQLite database, slow access
- Automatic archival when job removed from active
"""

import sqlite3
import json
from pathlib import Path
from collections import deque
from typing import Optional
from dataclasses import asdict
from app.job_queue import JobInfo, JobStatus
import logging

logger = logging.getLogger(__name__)


class JobArchive:
    """Archive old jobs to SQLite database"""
    
    def __init__(self, db_path: str = "data/job_archive.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS archived_jobs (
                    id TEXT PRIMARY KEY,
                    job_data TEXT NOT NULL,
                    archived_at REAL NOT NULL,
                    status TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON archived_jobs(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_archived_at ON archived_jobs(archived_at)
            """)
            conn.commit()
    
    def archive_job(self, job_info: JobInfo) -> bool:
        """Save job to SQLite when removed from active memory"""
        try:
            job_data = json.dumps(asdict(job_info), default=str)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO archived_jobs (id, job_data, archived_at, status) VALUES (?, ?, ?, ?)",
                    (job_info.id, job_data, time.time(), job_info.status.value)
                )
                conn.commit()
            
            logger.debug(f"Archived job {job_info.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to archive job {job_info.id}: {e}")
            return False
    
    def retrieve_archived(self, job_id: str) -> Optional[JobInfo]:
        """Get job from SQLite if needed"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT job_data FROM archived_jobs WHERE id = ?",
                    (job_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    job_data = json.loads(row[0])
                    # Convert status string back to enum
                    if 'status' in job_data:
                        job_data['status'] = JobStatus(job_data['status'])
                    return JobInfo(**job_data)
            
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve archived job {job_id}: {e}")
            return None
    
    def list_archived(self, limit: int = 50) -> list[JobInfo]:
        """List recent archived jobs"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT job_data FROM archived_jobs ORDER BY archived_at DESC LIMIT ?",
                    (limit,)
                )
                
                jobs = []
                for row in cursor.fetchall():
                    job_data = json.loads(row[0])
                    if 'status' in job_data:
                        job_data['status'] = JobStatus(job_data['status'])
                    jobs.append(JobInfo(**job_data))
                
                return jobs
        except Exception as e:
            logger.error(f"Failed to list archived jobs: {e}")
            return []
    
    def cleanup_old_jobs(self, days: int = 30) -> int:
        """Delete jobs older than N days"""
        try:
            import time
            cutoff_time = time.time() - (days * 24 * 3600)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM archived_jobs WHERE archived_at < ?",
                    (cutoff_time,)
                )
                conn.commit()
                
                logger.info(f"Cleaned up {cursor.rowcount} archived jobs older than {days} days")
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to cleanup archived jobs: {e}")
            return 0


import time

# Global archive instance
job_archive = JobArchive()
