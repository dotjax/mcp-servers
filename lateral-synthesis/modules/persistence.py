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
    # Logs dir is inside the lateral-synthesis folder
    return Path(__file__).parent.parent / "_logs"


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


def log_session_event(session: LateralSession, event_type: str, details: dict | None = None) -> None:
    """Append a lightweight event log to a per-session log."""
    config = get_config()
    if not config.persistence.enabled:
        return

    logs_dir = get_logs_dir()
    logs_dir.mkdir(exist_ok=True)

    path = logs_dir / f"lateral-synthesis-session-{session.session_id}.jsonl"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "session_id": session.session_id,
    }
    if details:
        payload["details"] = details

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception as e:
        logger.debug(f"Failed to write session log: {e}")

# Alias for backward compatibility
save_session_snapshot = log_session_event


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
                last_valid_session = None
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            # Handle both formats:
                            # 1. Direct session dict: {"session_id": ..., ...}
                            # 2. Snapshot wrapper: {"timestamp": ..., "label": ..., "session": {...}}
                            if "session" in data and isinstance(data["session"], dict):
                                # This is a snapshot wrapper - extract the session
                                session_data = data["session"]
                            else:
                                # This is a direct session dict
                                session_data = data
                            last_valid_session = LateralSession.from_dict(session_data)
                        except json.JSONDecodeError:
                            logger.warning(f"Skipping invalid JSON line in {file_path}")
                        except Exception as e:
                            logger.warning(f"Skipping invalid session in {file_path}: {e}")
                # Only add the last valid session from each file (most recent state)
                if last_valid_session is not None:
                    sessions.append(last_valid_session)
        except Exception as e:
            logger.error(f"Failed to read log file {file_path}: {e}")
    
    # Deduplicate sessions by session_id, keeping the most complete version
    seen_ids: dict[str, LateralSession] = {}
    for s in sessions:
        existing = seen_ids.get(s.session_id)
        if existing is None:
            seen_ids[s.session_id] = s
        elif s.completed_at and not existing.completed_at:
            # Prefer completed sessions
            seen_ids[s.session_id] = s
    
    sessions = list(seen_ids.values())
    # Sort by created_at descending
    sessions.sort(key=lambda s: s.created_at or "", reverse=True)
    return sessions[:limit]
