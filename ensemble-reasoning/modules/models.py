import os
import time
import asyncio
import json
import sys
import threading
import http.server
import socketserver
import logging
from pathlib import Path
from urllib.parse import urlparse
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import yaml

# Basic runtime settings
CONSOLE_OUTPUT = True
logger = logging.getLogger("ensemble_reasoning.models")


# Runtime-configurable server settings (can be tuned via environment variables)
@dataclass
class ServerConfig:
    max_thoughts_per_session: int = 1000
    max_endorsements_per_thought: int = 100
    default_synthesis_threshold: float = 0.6
    max_thoughts_per_agent_per_session: int = 50
    positive_endorsement_threshold: float = 0.5
    negative_endorsement_threshold: float = -0.5
    enable_metrics: bool = True
    # Rate limiter: max operations per agent in the sliding window
    rate_limit_ops_per_window: int = 5
    rate_limit_window_seconds: int = 60
    # Metrics export
    metrics_export_enabled: bool = False
    metrics_export_path: str = "/tmp/mcp_metrics.json"
    metrics_export_interval_seconds: int = 30
    # Prometheus endpoint
    metrics_prometheus_enabled: bool = False
    prometheus_listen_addr: str = "127.0.0.1"
    prometheus_port: int = 8000
    # Input bounds
    max_thought_length: int = 4000
    max_note_length: int = 2000
    max_integration_length: int = 4000
    max_reconciles_per_integration: int = 50


def _env_bool(name: str, current: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return current
    return val.lower() not in ("0", "false", "no")


def _env_int(name: str, current: int) -> int:
    val = os.getenv(name)
    if val is None:
        return current
    try:
        return int(val)
    except ValueError:
        return current


def _env_float(name: str, current: float) -> float:
    val = os.getenv(name)
    if val is None:
        return current
    try:
        return float(val)
    except ValueError:
        return current


def _env_str(name: str, current: str) -> str:
    val = os.getenv(name)
    return val if val is not None else current


def load_config(config_path: Path | None = None) -> ServerConfig:
    """Load config from YAML with environment overrides."""
    cfg = ServerConfig()
    path = config_path or Path(__file__).parent.parent / "config.yaml"

    if path.exists():
        try:
            data = yaml.safe_load(path.read_text()) or {}
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        except Exception:
            logger.warning("Failed to load config.yaml; using defaults", exc_info=True)

    # Environment overrides
    cfg.max_thoughts_per_session = _env_int("MCP_MAX_THOUGHTS_PER_SESSION", cfg.max_thoughts_per_session)
    cfg.max_endorsements_per_thought = _env_int("MCP_MAX_ENDORSEMENTS_PER_THOUGHT", cfg.max_endorsements_per_thought)
    cfg.default_synthesis_threshold = _env_float("MCP_DEFAULT_SYNTHESIS_THRESHOLD", cfg.default_synthesis_threshold)
    cfg.max_thoughts_per_agent_per_session = _env_int("MCP_MAX_THOUGHTS_PER_AGENT", cfg.max_thoughts_per_agent_per_session)
    cfg.positive_endorsement_threshold = _env_float("MCP_POS_ENDORSE_THRESHOLD", cfg.positive_endorsement_threshold)
    cfg.negative_endorsement_threshold = _env_float("MCP_NEG_ENDORSE_THRESHOLD", cfg.negative_endorsement_threshold)
    cfg.enable_metrics = _env_bool("MCP_ENABLE_METRICS", cfg.enable_metrics)
    cfg.rate_limit_ops_per_window = _env_int("MCP_RATE_LIMIT_OPS", cfg.rate_limit_ops_per_window)
    cfg.rate_limit_window_seconds = _env_int("MCP_RATE_LIMIT_WINDOW_S", cfg.rate_limit_window_seconds)
    cfg.metrics_export_enabled = _env_bool("MCP_METRICS_EXPORT", cfg.metrics_export_enabled)
    cfg.metrics_export_path = _env_str("MCP_METRICS_EXPORT_PATH", cfg.metrics_export_path)
    cfg.metrics_export_interval_seconds = _env_int("MCP_METRICS_EXPORT_INTERVAL", cfg.metrics_export_interval_seconds)
    cfg.metrics_prometheus_enabled = _env_bool("MCP_PROMETHEUS", cfg.metrics_prometheus_enabled)
    cfg.prometheus_listen_addr = _env_str("MCP_PROMETHEUS_ADDR", cfg.prometheus_listen_addr)
    cfg.prometheus_port = _env_int("MCP_PROMETHEUS_PORT", cfg.prometheus_port)
    cfg.max_thought_length = _env_int("MCP_MAX_THOUGHT_LENGTH", cfg.max_thought_length)
    cfg.max_note_length = _env_int("MCP_MAX_NOTE_LENGTH", cfg.max_note_length)
    cfg.max_integration_length = _env_int("MCP_MAX_INTEGRATION_LENGTH", cfg.max_integration_length)
    cfg.max_reconciles_per_integration = _env_int("MCP_MAX_RECONCILES", cfg.max_reconciles_per_integration)

    return cfg


# Global config instance
CONFIG = load_config()


# Predefined agent lenses
AGENT_LENSES = {
    "analytical": {
        "focus": "Data-driven, logical decomposition, systematic analysis",
        "bias_check": "May overlook human factors and edge cases"
    },
    "skeptical": {
        "focus": "Critical examination, identifying flaws, risk assessment",
        "bias_check": "May be overly negative, miss opportunities"
    },
    "creative": {
        "focus": "Novel solutions, lateral thinking, unconventional approaches",
        "bias_check": "May propose impractical or risky ideas"
    },
    "pragmatic": {
        "focus": "Feasibility, resources, implementation, real-world constraints",
        "bias_check": "May be too conservative, miss innovation"
    },
    "ethical": {
        "focus": "Values, fairness, long-term impact, stakeholder effects",
        "bias_check": "May prioritize ideals over practicality"
    }
}


@dataclass
class CollaborativeThought:
    thought_id: int
    thought: str
    agent_lens: str
    builds_on: list[int] = field(default_factory=list)
    weight: float = 1.0
    endorsements: dict[str, float] = field(default_factory=dict)
    challenges: list[dict] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            'thought_id': self.thought_id,
            'thought': self.thought,
            'agent_lens': self.agent_lens,
            'builds_on': self.builds_on,
            'weight': self.weight,
            'endorsements': self.endorsements,
            'challenges': self.challenges,
            'timestamp': self.timestamp
        }


@dataclass
class IntegrationProposal:
    proposal_id: int
    proposing_agent: str
    integration: str
    reconciles: list[int]
    endorsements: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            'proposal_id': self.proposal_id,
            'proposing_agent': self.proposing_agent,
            'integration': self.integration,
            'reconciles': self.reconciles,
            'endorsements': self.endorsements,
            'timestamp': self.timestamp
        }


class EnsembleSession:
    def __init__(self, session_id: str, problem: str, agent_lenses: list[str]):
        self.session_id = session_id
        self.problem = problem
        self.agent_lenses = agent_lenses
        self.thoughts: list[CollaborativeThought] = []
        self.integrations: list[IntegrationProposal] = []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.completed_at: Optional[str] = None

        # Indices for O(1) lookups
        self._thought_index: dict[int, CollaborativeThought] = {}
        self._agent_thoughts: dict[str, list[int]] = defaultdict(list)
        self._next_thought_id = 1
        self._next_proposal_id = 1

    def add_thought(self, thought: CollaborativeThought) -> int:
        if len(self.thoughts) >= CONFIG.max_thoughts_per_session:
            raise ValueError(f"Session has reached maximum thoughts ({CONFIG.max_thoughts_per_session})")

        agent_count = len(self._agent_thoughts.get(thought.agent_lens, []))
        if agent_count >= CONFIG.max_thoughts_per_agent_per_session:
            raise ValueError(f"Agent '{thought.agent_lens}' has reached max thoughts ({CONFIG.max_thoughts_per_agent_per_session}) in this session")

        thought.thought_id = self._next_thought_id
        self._next_thought_id += 1

        self.thoughts.append(thought)
        self._thought_index[thought.thought_id] = thought
        self._agent_thoughts[thought.agent_lens].append(thought.thought_id)

        return thought.thought_id

    def add_integration(self, integration: IntegrationProposal) -> int:
        integration.proposal_id = self._next_proposal_id
        self._next_proposal_id += 1
        self.integrations.append(integration)
        return integration.proposal_id

    def get_thought(self, thought_id: int) -> Optional[CollaborativeThought]:
        return self._thought_index.get(thought_id)

    def get_agent_thoughts(self, agent_lens: str) -> list[CollaborativeThought]:
        return [self._thought_index[tid] for tid in self._agent_thoughts.get(agent_lens, [])]

    def to_dict(self) -> dict:
        return {
            'session_id': self.session_id,
            'problem': self.problem,
            'agent_lenses': self.agent_lenses,
            'thoughts': [t.to_dict() for t in self.thoughts],
            'integrations': [i.to_dict() for i in self.integrations],
            'started_at': self.started_at,
            'completed_at': self.completed_at
        }


# Global state
active_sessions: dict[str, EnsembleSession] = {}
current_session_id: Optional[str] = None

# Per-agent recent operation timestamps for rate limiting (scoped per session)
_agent_session_ops: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))

# Lock to protect agent timestamps in concurrent access
_agent_ops_lock: threading.Lock = threading.Lock()


def inc_counter(counter_name: str, delta: int = 1) -> None:
    """No-op counter increment."""
    pass


def record_latency(op_name: str, duration: float) -> None:
    """No-op latency record."""
    pass


def is_rate_limited(session_id: str, agent_lens: str) -> bool:
    """Return True if the agent is rate-limited under sliding-window rules for a given session."""
    now = time.time()
    window = CONFIG.rate_limit_window_seconds
    cutoff = now - window
    with _agent_ops_lock:
        dq = _agent_session_ops[session_id][agent_lens]
        while dq and dq[0] < cutoff:
            dq.popleft()
        limited = len(dq) >= CONFIG.rate_limit_ops_per_window
        count = len(dq)
    logger.debug("rate_limit_check session=%s lens=%s count=%s limited=%s", session_id, agent_lens, count, limited)
    return limited


def record_agent_op(session_id: str, agent_lens: str) -> None:
    """Record an operation timestamp for `agent_lens` within a session."""
    now = time.time()
    with _agent_ops_lock:
        dq = _agent_session_ops[session_id][agent_lens]
        dq.append(now)
        count = len(dq)
    inc_counter("agent_ops_total")
    logger.debug("record_agent_op session=%s lens=%s count=%s", session_id, agent_lens, count)


def ensure_metrics_exporter_started():
    """No-op."""
    pass


def ensure_prometheus_server_started():
    """No-op."""
    pass


def stop_metrics_exporter():
    """No-op."""
    pass


def stop_prometheus_server():
    """No-op."""
    pass


def _logs_dir() -> Path:
    return Path(__file__).parent.parent / "_logs"


def log_session_event(session: EnsembleSession, event_type: str, details: dict | None = None) -> None:
    """Persist a lightweight event log to _logs."""
    try:
        log_dir = _logs_dir()
        log_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = log_dir / f"ensemble-session-{session.session_id}.jsonl"
        
        payload = {
            "timestamp": ts,
            "event": event_type,
            "session_id": session.session_id,
        }
        if details:
            payload["details"] = details
            
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        logger.debug("session log failed", exc_info=True)

# Backward compatibility alias if needed, but we will update calls
save_session_snapshot = log_session_event
