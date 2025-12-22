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

# Metrics infrastructure
_metrics_lock: threading.Lock = threading.Lock()
METRICS: dict[str, dict] = {
    "counters": {},
    "latencies": {}
}

# Metrics exporter thread
_metrics_exporter_thread: Optional[threading.Thread] = None
_metrics_exporter_stop_event: Optional[threading.Event] = None

# Prometheus HTTP server
_prometheus_server: Optional[socketserver.TCPServer] = None
_prometheus_server_thread: Optional[threading.Thread] = None


def inc_counter(counter_name: str, delta: int = 1) -> None:
    """Increment a counter metric."""
    if not CONFIG.enable_metrics:
        return
    
    with _metrics_lock:
        METRICS["counters"][counter_name] = METRICS["counters"].get(counter_name, 0) + delta


def record_latency(op_name: str, duration: float) -> None:
    """Record a latency sample for an operation."""
    if not CONFIG.enable_metrics:
        return
    
    with _metrics_lock:
        if op_name not in METRICS["latencies"]:
            METRICS["latencies"][op_name] = []
        # Keep last 1000 samples per operation to avoid unbounded growth
        samples = METRICS["latencies"][op_name]
        samples.append(duration)
        if len(samples) > 1000:
            samples.pop(0)


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


def _metrics_exporter_worker():
    """Background thread that periodically exports metrics to JSON file."""
    global _metrics_exporter_stop_event
    
    while not _metrics_exporter_stop_event.is_set():
        try:
            # Wait for interval or stop event
            if _metrics_exporter_stop_event.wait(CONFIG.metrics_export_interval_seconds):
                break  # Stop event was set
            
            # Export metrics
            export_path = Path(CONFIG.metrics_export_path)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            
            with _metrics_lock:
                # Create export data with timestamps
                export_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "counters": dict(METRICS["counters"]),
                    "latencies": {
                        op: {
                            "count": len(samples),
                            "avg": sum(samples) / len(samples) if samples else 0.0,
                            "min": min(samples) if samples else 0.0,
                            "max": max(samples) if samples else 0.0,
                        }
                        for op, samples in METRICS["latencies"].items()
                    }
                }
            
            # Atomic write: write to temp file then rename
            temp_path = export_path.with_suffix(export_path.suffix + ".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            temp_path.replace(export_path)
            
            logger.debug(f"Exported metrics to {export_path}")
        except Exception as e:
            logger.warning(f"Metrics export failed: {e}", exc_info=True)


def ensure_metrics_exporter_started():
    """Start the metrics exporter thread if enabled and not already running."""
    global _metrics_exporter_thread, _metrics_exporter_stop_event
    
    if not CONFIG.metrics_export_enabled:
        return
    
    if _metrics_exporter_thread is not None and _metrics_exporter_thread.is_alive():
        return  # Already running
    
    _metrics_exporter_stop_event = threading.Event()
    _metrics_exporter_thread = threading.Thread(
        target=_metrics_exporter_worker,
        name="metrics-exporter",
        daemon=True
    )
    _metrics_exporter_thread.start()
    logger.info(f"Started metrics exporter (interval={CONFIG.metrics_export_interval_seconds}s, path={CONFIG.metrics_export_path})")


class PrometheusMetricsHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for Prometheus /metrics endpoint."""
    
    def do_GET(self):
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            
            with _metrics_lock:
                # Export counters as Prometheus counters
                for name, value in METRICS["counters"].items():
                    # Sanitize metric name (Prometheus format)
                    safe_name = name.replace(".", "_").replace("-", "_")
                    self.wfile.write(f"# TYPE {safe_name} counter\n".encode())
                    self.wfile.write(f"{safe_name} {value}\n".encode())
                
                # Export latencies as Prometheus summaries
                for op_name, samples in METRICS["latencies"].items():
                    if not samples:
                        continue
                    safe_name = f"latency_{op_name.replace('.', '_').replace('-', '_')}"
                    self.wfile.write(f"# TYPE {safe_name} summary\n".encode())
                    self.wfile.write(f"{safe_name}_count {len(samples)}\n".encode())
                    avg = sum(samples) / len(samples)
                    self.wfile.write(f"{safe_name}_sum {sum(samples)}\n".encode())
                    self.wfile.write(f"{safe_name} {avg}\n".encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        logger.debug(f"Prometheus: {format % args}")


def _prometheus_server_worker():
    """Run the Prometheus HTTP server."""
    global _prometheus_server
    
    try:
        _prometheus_server.serve_forever()
    except Exception as e:
        logger.error(f"Prometheus server error: {e}", exc_info=True)


def ensure_prometheus_server_started():
    """Start the Prometheus HTTP server if enabled and not already running."""
    global _prometheus_server, _prometheus_server_thread
    
    if not CONFIG.metrics_prometheus_enabled:
        return
    
    if _prometheus_server is not None:
        return  # Already started
    
    try:
        _prometheus_server = socketserver.TCPServer(
            (CONFIG.prometheus_listen_addr, CONFIG.prometheus_port),
            PrometheusMetricsHandler
        )
        _prometheus_server.allow_reuse_address = True
        
        _prometheus_server_thread = threading.Thread(
            target=_prometheus_server_worker,
            name="prometheus-server",
            daemon=True
        )
        _prometheus_server_thread.start()
        logger.info(f"Started Prometheus server at http://{CONFIG.prometheus_listen_addr}:{CONFIG.prometheus_port}/metrics")
    except Exception as e:
        logger.error(f"Failed to start Prometheus server: {e}", exc_info=True)


def stop_metrics_exporter():
    """Stop the metrics exporter thread."""
    global _metrics_exporter_thread, _metrics_exporter_stop_event
    
    if _metrics_exporter_stop_event is not None:
        _metrics_exporter_stop_event.set()
    
    if _metrics_exporter_thread is not None and _metrics_exporter_thread.is_alive():
        _metrics_exporter_thread.join(timeout=5.0)
        if _metrics_exporter_thread.is_alive():
            logger.warning("Metrics exporter thread did not stop gracefully")
        else:
            logger.debug("Metrics exporter stopped")
    
    _metrics_exporter_thread = None
    _metrics_exporter_stop_event = None


def stop_prometheus_server():
    """Stop the Prometheus HTTP server."""
    global _prometheus_server, _prometheus_server_thread
    
    if _prometheus_server is not None:
        try:
            _prometheus_server.shutdown()
            _prometheus_server.server_close()
            logger.debug("Prometheus server stopped")
        except Exception as e:
            logger.warning(f"Error stopping Prometheus server: {e}")
    
    if _prometheus_server_thread is not None and _prometheus_server_thread.is_alive():
        _prometheus_server_thread.join(timeout=2.0)
    
    _prometheus_server = None
    _prometheus_server_thread = None


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
