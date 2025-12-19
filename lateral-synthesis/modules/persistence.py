"""
Lateral Synthesis MCP - Persistence

Handles saving and loading sessions from disk.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from .models import LateralSession, get_config

logger = logging.getLogger(__name__)

def get_logs_dir() -> Path:
    """Get the path to the logs directory."""
    # Logs dir is at the root level (parent of lateral-synthesis dir)
    return Path(__file__).parent.parent.parent / "_logs"


def save_session_to_history(session: LateralSession) -> None:
    """Save a completed session to a new log file."""
    config = get_config()
    if not config.persistence.enabled:
        return
    
    logs_dir = get_logs_dir()
    logs_dir.mkdir(exist_ok=True)
    
    # Use session completion time or now if incomplete
    ts = session.completed_at or datetime.now(timezone.utc).isoformat()
    # Sanitize timestamp for filename
    ts_str = ts.replace(":", "").replace("-", "").split(".")[0]
    
    filename = f"lateral-synthesis-session-{ts_str}-{session.session_id[:8]}.jsonl"
    file_path = logs_dir / filename
    
    try:
        with open(file_path, "w") as f:
            f.write(json.dumps(session.to_dict()) + "\n")
        logger.info(f"Saved session {session.session_id} to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save session to history: {e}")


def load_sessions_from_history(limit: int = 100) -> list[LateralSession]:
    """Load sessions from the logs directory."""
    logs_dir = get_logs_dir()
    if not logs_dir.exists():
        return []
    
    sessions = []
    # Find all session log files
    log_files = sorted(logs_dir.glob("lateral-synthesis-session-*.jsonl"), reverse=True)
    
    # We only need enough files to potentially fill the limit
    # Since one file = one session, we can just take the first N files
    for file_path in log_files[:limit]:
        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            sessions.append(LateralSession.from_dict(data))
                        except json.JSONDecodeError:
                            logger.warning(f"Skipping invalid JSON line in {file_path}")
                        except Exception as e:
                            logger.warning(f"Skipping invalid session in {file_path}: {e}")
        except Exception as e:
            logger.error(f"Failed to read log file {file_path}: {e}")
    
    # Double check sort order (trusting filename sort is usually good, but robust to sort by data)
    sessions.sort(key=lambda s: s.created_at or "", reverse=True)
    return sessions[:limit]
