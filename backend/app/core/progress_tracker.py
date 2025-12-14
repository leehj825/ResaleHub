"""
Simple in-memory progress tracker for long-running operations.
Stores progress messages keyed by job_id.
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import threading

class ProgressTracker:
    """Thread-safe progress message tracker"""
    
    def __init__(self):
        self._progress: Dict[str, List[Dict[str, any]]] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = timedelta(minutes=30)  # Clean up old jobs after 30 minutes
    
    def add_message(self, job_id: str, message: str, level: str = "info"):
        """Add a progress message for a job"""
        with self._lock:
            if job_id not in self._progress:
                self._progress[job_id] = []
            
            self._progress[job_id].append({
                "message": message,
                "level": level,  # info, warning, error, success
                "timestamp": datetime.utcnow().isoformat(),
            })
    
    def get_progress(self, job_id: str) -> List[Dict[str, any]]:
        """Get all progress messages for a job"""
        with self._lock:
            return self._progress.get(job_id, []).copy()
    
    def get_latest_message(self, job_id: str) -> Optional[Dict[str, any]]:
        """Get the latest progress message for a job"""
        with self._lock:
            messages = self._progress.get(job_id, [])
            return messages[-1] if messages else None
    
    def clear(self, job_id: str):
        """Clear progress for a job"""
        with self._lock:
            if job_id in self._progress:
                del self._progress[job_id]
    
    def cleanup_old_jobs(self):
        """Remove old job progress (call periodically)"""
        # For now, we'll keep all jobs. In production, you might want to
        # track timestamps and remove jobs older than cleanup_interval
        pass

# Global instance
progress_tracker = ProgressTracker()

