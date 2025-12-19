"""
Lateral Synthesis MCP - Data Models

Dataclasses for sessions, syntheses, reflections, config, and global state.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging
import os
import uuid
import yaml

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Connection Types
# -----------------------------------------------------------------------------

CONNECTION_TYPES = [
    "analogy",      # X is like Y because...
    "contrast",     # X is opposite to Y in that...
    "causal",       # X leads to Y / Y is caused by X
    "metaphor",     # X represents Y symbolically
    "structural",   # X and Y share the same structure/pattern
    "arbitrary",    # Forced connection with no clear basis
    "other",        # Requires connection_type_detail
]

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

@dataclass
class DivergenceConfig:
    method: str = "random"
    count: int = 5


@dataclass
class PersistenceConfig:
    enabled: bool = True


@dataclass
class LimitsConfig:
    max_origin_chars: int = 1000
    max_insight_chars: int = 2000


@dataclass
class Config:
    divergence: DivergenceConfig = field(default_factory=DivergenceConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)


def load_config(config_path: Path | None = None) -> Config:
    """Load config from YAML file, with env var overrides."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
    
    cfg = Config()
    
    if config_path.exists():
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            
            if "divergence" in data:
                cfg.divergence = DivergenceConfig(**data["divergence"])
            if "persistence" in data:
                cfg.persistence = PersistenceConfig(**data["persistence"])
            if "limits" in data:
                cfg.limits = LimitsConfig(**data["limits"])
            
            logger.info(f"Loaded config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")
    
    # Environment variable overrides
    if env_method := os.getenv("MCP_DIVERGENCE_METHOD"):
        cfg.divergence.method = env_method
    if env_count := os.getenv("MCP_DIVERGENCE_COUNT"):
        cfg.divergence.count = int(env_count)
    if env_persist := os.getenv("MCP_PERSISTENCE_ENABLED"):
        cfg.persistence.enabled = env_persist.lower() in ("true", "1", "yes")
    
    return cfg


# -----------------------------------------------------------------------------
# Session Models
# -----------------------------------------------------------------------------

@dataclass
class ConceptSynthesis:
    """Synthesis for a single divergent concept."""
    divergent_concept: str
    connection_type: str
    connection_type_detail: str | None  # Required if connection_type == "other"
    confidence: float  # 0.0 - 1.0
    insight: str
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def validate(self) -> list[str]:
        """Return list of validation errors, empty if valid."""
        errors = []
        if self.connection_type not in CONNECTION_TYPES:
            errors.append(f"Invalid connection_type: {self.connection_type}. Must be one of {CONNECTION_TYPES}")
        if self.connection_type == "other" and not self.connection_type_detail:
            errors.append("connection_type_detail is required when connection_type is 'other'")
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(f"confidence must be between 0.0 and 1.0, got {self.confidence}")
        if not self.insight.strip():
            errors.append("insight cannot be empty")
        return errors


@dataclass
class SessionReflection:
    """Meta-reflection after all syntheses are complete."""
    most_valuable_insight: str
    why_valuable: str
    surprising_connections: list[str]
    overall_rating: float  # 0.0 - 1.0
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def validate(self) -> list[str]:
        """Return list of validation errors, empty if valid."""
        errors = []
        if not (0.0 <= self.overall_rating <= 1.0):
            errors.append(f"overall_rating must be between 0.0 and 1.0, got {self.overall_rating}")
        if not self.most_valuable_insight.strip():
            errors.append("most_valuable_insight cannot be empty")
        if not self.why_valuable.strip():
            errors.append("why_valuable cannot be empty")
        return errors


@dataclass
class LateralSession:
    """A complete lateral synthesis session."""
    session_id: str
    origin: str
    divergent_concepts: list[str] = field(default_factory=list)
    syntheses: list[ConceptSynthesis] = field(default_factory=list)
    reflection: SessionReflection | None = None
    method: str = "random"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    
    @classmethod
    def create(cls, origin: str, method: str = "random") -> "LateralSession":
        """Create a new session with a unique ID."""
        return cls(
            session_id=str(uuid.uuid4()),
            origin=origin,
            method=method,
        )
    
    def get_synthesized_concepts(self) -> set[str]:
        """Return set of divergent concepts that have been synthesized."""
        return {s.divergent_concept for s in self.syntheses}
    
    def get_remaining_concepts(self) -> list[str]:
        """Return list of divergent concepts not yet synthesized."""
        synthesized = self.get_synthesized_concepts()
        return [c for c in self.divergent_concepts if c not in synthesized]
    
    def is_synthesis_complete(self) -> bool:
        """Check if all divergent concepts have been synthesized."""
        return len(self.syntheses) >= len(self.divergent_concepts) and len(self.divergent_concepts) > 0
    
    def is_complete(self) -> bool:
        """Check if session is fully complete (syntheses + reflection)."""
        return self.is_synthesis_complete() and self.reflection is not None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "origin": self.origin,
            "divergent_concepts": self.divergent_concepts,
            "syntheses": [asdict(s) for s in self.syntheses],
            "reflection": asdict(self.reflection) if self.reflection else None,
            "method": self.method,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LateralSession":
        """Create from dictionary (e.g., from JSON)."""
        session = cls(
            session_id=data["session_id"],
            origin=data["origin"],
            divergent_concepts=data.get("divergent_concepts", []),
            method=data.get("method", "random"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            completed_at=data.get("completed_at"),
        )
        
        for s in data.get("syntheses", []):
            session.syntheses.append(ConceptSynthesis(**s))
        
        if data.get("reflection"):
            session.reflection = SessionReflection(**data["reflection"])
        
        return session


# -----------------------------------------------------------------------------
# Global State
# -----------------------------------------------------------------------------

# Active sessions (in-memory)
SESSIONS: dict[str, LateralSession] = {}

# Current session ID for convenience
CURRENT_SESSION_ID: str | None = None

# Loaded config
CONFIG: Config | None = None


def get_config() -> Config:
    """Get or load config."""
    global CONFIG
    if CONFIG is None:
        CONFIG = load_config()
    return CONFIG


def set_current_session(session_id: str | None) -> None:
    """Set the current active session."""
    global CURRENT_SESSION_ID
    CURRENT_SESSION_ID = session_id
    logger.debug(f"Current session set to: {session_id}")


def get_current_session() -> LateralSession | None:
    """Get the current active session."""
    if CURRENT_SESSION_ID and CURRENT_SESSION_ID in SESSIONS:
        return SESSIONS[CURRENT_SESSION_ID]
    return None
