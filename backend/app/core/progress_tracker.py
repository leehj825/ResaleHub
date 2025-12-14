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
        self._status: Dict[str, Dict[str, any]] = {}  # job_id -> {status, latest_message, result}
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
    
    def set_status(self, job_id: str, status: str, latest_message: str, level: str = "info", result: Optional[Dict] = None):
        """Set the status of a job (pending, completed, failed)"""
        import sys
        try:
            print(f">>> [PROGRESS_TRACKER] set_status called: job_id={job_id}, status={status}", flush=True)
            sys.stdout.flush()
            
            with self._lock:
                print(f">>> [PROGRESS_TRACKER] Acquired lock for job_id={job_id}", flush=True)
                sys.stdout.flush()
                
                self._status[job_id] = {
                    "status": status,
                    "latest_message": latest_message,
                    "level": level,
                    "result": result,
                }
                # Also add as a message
                self.add_message(job_id, latest_message, level)
                
                print(f">>> [PROGRESS_TRACKER] set_status completed for job_id={job_id}", flush=True)
                sys.stdout.flush()
        except Exception as e:
            print(f">>> [PROGRESS_TRACKER] ERROR in set_status: {e}", flush=True)
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            raise
    
    def get_status(self, job_id: str) -> Optional[Dict[str, any]]:
        """Get the status of a job"""
        with self._lock:
            return self._status.get(job_id)
    
    def cleanup_old_jobs(self):
        """Remove old job progress (call periodically)"""
        # For now, we'll keep all jobs. In production, you might want to
        # track timestamps and remove jobs older than cleanup_interval
        pass

# Global instance
progress_tracker = ProgressTracker()

