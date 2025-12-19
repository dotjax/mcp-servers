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
from datetime import datetime
from typing import Optional

# Basic runtime settings
CONSOLE_OUTPUT = True
logger = logging.getLogger("ensemble_reasoning.models")


# Runtime-configurable server settings (can be tuned via environment variables)
@dataclass
class ServerConfig:
    max_thoughts_per_session: int = int(os.getenv("MCP_MAX_THOUGHTS_PER_SESSION", 1000))
    max_endorsements_per_thought: int = int(os.getenv("MCP_MAX_ENDORSEMENTS_PER_THOUGHT", 100))
    default_synthesis_threshold: float = float(os.getenv("MCP_DEFAULT_SYNTHESIS_THRESHOLD", 0.6))
    max_thoughts_per_agent_per_session: int = int(os.getenv("MCP_MAX_THOUGHTS_PER_AGENT", 50))
    positive_endorsement_threshold: float = float(os.getenv("MCP_POS_ENDORSE_THRESHOLD", 0.5))
    negative_endorsement_threshold: float = float(os.getenv("MCP_NEG_ENDORSE_THRESHOLD", -0.5))
    enable_metrics: bool = os.getenv("MCP_ENABLE_METRICS", "1") not in ("0", "false", "False")
    # Rate limiter: max operations per agent in the sliding window
    rate_limit_ops_per_window: int = int(os.getenv("MCP_RATE_LIMIT_OPS", 5))
    rate_limit_window_seconds: int = int(os.getenv("MCP_RATE_LIMIT_WINDOW_S", 60))
    # Metrics export
    metrics_export_enabled: bool = os.getenv("MCP_METRICS_EXPORT", "0") not in ("0", "false", "False")
    metrics_export_path: str = os.getenv("MCP_METRICS_EXPORT_PATH", "/tmp/mcp_metrics.json")
    metrics_export_interval_seconds: int = int(os.getenv("MCP_METRICS_EXPORT_INTERVAL", 30))
    # Prometheus endpoint
    metrics_prometheus_enabled: bool = os.getenv("MCP_PROMETHEUS", "0") not in ("0", "false", "False")
    prometheus_listen_addr: str = os.getenv("MCP_PROMETHEUS_ADDR", "127.0.0.1")
    prometheus_port: int = int(os.getenv("MCP_PROMETHEUS_PORT", "8000"))


# Global config instance
CONFIG = ServerConfig()


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
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

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
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

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
        self.started_at = datetime.utcnow().isoformat()
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

# Lightweight runtime metrics (in-memory)
_MAX_LATENCY_SAMPLES = 1000
_metrics_lock = threading.Lock()
METRICS: dict = {
    "counters": defaultdict(int),
    "latencies": defaultdict(list),
}


def inc_counter(counter_name: str, delta: int = 1) -> None:
    """Thread-safe counter increment for in-memory metrics."""
    if not CONFIG.enable_metrics:
        return
    with _metrics_lock:
        METRICS["counters"][counter_name] += int(delta)
    logger.debug("counter %s += %s -> %s", counter_name, delta, METRICS["counters"][counter_name])


def record_latency(op_name: str, duration: float) -> None:
    """Record a latency sample, capping to _MAX_LATENCY_SAMPLES."""
    if not CONFIG.enable_metrics:
        return
    with _metrics_lock:
        lat = METRICS["latencies"][op_name]
        lat.append(duration)
        if len(lat) > _MAX_LATENCY_SAMPLES:
            del lat[:len(lat) - _MAX_LATENCY_SAMPLES]
    logger.debug("latency %s add %.4f samples=%s", op_name, duration, len(METRICS["latencies"][op_name]))

# Per-agent recent operation timestamps for rate limiting (agent_lens -> deque[timestamps])
_agent_op_timestamps: dict[str, deque] = defaultdict(deque)

# Lock to protect agent timestamps in concurrent access
_agent_ops_lock: threading.Lock = threading.Lock()

# Internal background task handle for metrics export
_metrics_export_task: Optional[asyncio.Task] = None
_prometheus_thread: Optional[threading.Thread] = None


def is_rate_limited(agent_lens: str) -> bool:
    """Return True if the agent is currently rate-limited under sliding-window rules."""
    now = time.time()
    window = CONFIG.rate_limit_window_seconds
    cutoff = now - window
    with _agent_ops_lock:
        dq = _agent_op_timestamps[agent_lens]
        # prune old timestamps from the left
        while dq and dq[0] < cutoff:
            dq.popleft()
        limited = len(dq) >= CONFIG.rate_limit_ops_per_window
    logger.debug("rate_limit_check lens=%s count=%s limited=%s", agent_lens, len(dq), limited)
    return limited


def record_agent_op(agent_lens: str) -> None:
    """Record an operation timestamp for `agent_lens`."""
    now = time.time()
    with _agent_ops_lock:
        dq = _agent_op_timestamps[agent_lens]
        dq.append(now)
    inc_counter("agent_ops_total")
    logger.debug("record_agent_op lens=%s count=%s", agent_lens, len(_agent_op_timestamps[agent_lens]))


async def _metrics_exporter_loop():
    path = Path(CONFIG.metrics_export_path)
    interval = max(1, CONFIG.metrics_export_interval_seconds)
    while True:
        try:
            with _metrics_lock:
                snapshot = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "metrics": {
                        "counters": dict(METRICS["counters"]),
                        "latencies": {k: list(v) for k, v in METRICS["latencies"].items()},
                    },
                }
            # write atomically
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(snapshot))
            tmp.replace(path)
        except Exception:
            # swallow to avoid killing the exporter
            print("[mcp] metrics export error", file=sys.stderr)
        await asyncio.sleep(interval)


def ensure_metrics_exporter_started():
    """Start the background exporter task if enabled and not already running."""
    global _metrics_export_task
    if not CONFIG.metrics_export_enabled:
        return
    if _metrics_export_task and not _metrics_export_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # no running loop (e.g., called at import time) — defer start
        return
    _metrics_export_task = loop.create_task(_metrics_exporter_loop())
    print(
        f"[mcp] metrics exporter started, writing to {CONFIG.metrics_export_path} every {CONFIG.metrics_export_interval_seconds}s",
        file=sys.stderr,
    )


def _format_prometheus_metrics() -> str:
    """Render a minimal Prometheus plaintext exposition for in-memory METRICS."""
    lines = []
    with _metrics_lock:
        # counters
        for k, v in list(METRICS["counters"].items()):
            name = f"mcp_{k}_total"
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {int(v)}")
        # latencies: expose avg per op
        for k, samples in list(METRICS["latencies"].items()):
            name = f"mcp_{k}_avg_seconds"
            avg = (sum(samples) / len(samples)) if samples else 0.0
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {avg:.6f}")
    # return joined
    return "\n".join(lines) + "\n"


class _MetricsHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        payload = _format_prometheus_metrics().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # keep handler quiet
        return


def ensure_prometheus_server_started():
    """Start a small HTTP server in a background thread that serves `/metrics`."""
    global _prometheus_thread
    if not CONFIG.metrics_prometheus_enabled:
        return
    if _prometheus_thread and _prometheus_thread.is_alive():
        return
    addr = CONFIG.prometheus_listen_addr
    port = CONFIG.prometheus_port

    def _serve():
        try:
            with socketserver.TCPServer((addr, port), _MetricsHandler) as httpd:
                httpd.serve_forever()
        except Exception:
            print(f"[mcp] prometheus server error on {addr}:{port}", file=sys.stderr)

    print(f"[mcp] prometheus server starting on {addr}:{port}", file=sys.stderr)

    _prometheus_thread = threading.Thread(target=_serve, daemon=True)
    _prometheus_thread.start()
