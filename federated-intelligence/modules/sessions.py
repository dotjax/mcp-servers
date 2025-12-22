import json
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class Message:
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class Session:
    id: str
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

class SessionManager:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, session_id: str) -> Path:
        return self.storage_dir / f"{session_id}.json"

    def create_session(self, metadata: Optional[dict[str, Any]] = None) -> Session:
        session_id = str(uuid.uuid4())
        session = Session(id=session_id, metadata=metadata or {})
        self.save_session(session)
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        path = self._get_path(session_id)
        if not path.exists():
            return None
        
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            
            # Reconstruct objects
            messages = [Message(**m) for m in data.get('messages', [])]
            return Session(
                id=data['id'],
                messages=messages,
                created_at=data.get('created_at'),
                updated_at=data.get('updated_at'),
                metadata=data.get('metadata', {})
            )
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def save_session(self, session: Session):
        path = self._get_path(session.id)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            # Ensure directory exists (safety check)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(asdict(session), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save session {session.id}: {e}")

    def add_message(self, session_id: str, role: str, content: str):
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        session.messages.append(Message(role=role, content=content))
        self.save_session(session)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    sessions.append({
                        "id": data['id'],
                        "created_at": data.get('created_at'),
                        "message_count": len(data.get('messages', [])),
                        "preview": data['messages'][-1]['content'][:50] if data.get('messages') else ""
                    })
            except Exception:
                continue
        return sorted(sessions, key=lambda x: x['created_at'], reverse=True)
