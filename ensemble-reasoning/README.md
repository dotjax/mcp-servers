# Ensemble Reasoning MCP Server

Collaborative reasoning with multiple agent lenses, cross-endorsement/challenge, and synthesis.

## Agent Lenses

- `analytical`
- `skeptical`
- `creative`
- `pragmatic`
- `ethical`

## Install

```bash
pip install -r ../requirements.txt  # all servers
# or
pip install -r requirements.txt     # this server only
```

## Run

```bash
python server.py
```

`MCP_LOG_LEVEL` controls verbosity (default DEBUG). Logs stream to stderr and `_logs/ensemble-reasoning-*.jsonl`.

## Config

Config file: `config.yaml`

- `max_thoughts_per_session` (default `1000`)
- `max_endorsements_per_thought` (default `100`)
- `max_thoughts_per_agent_per_session` (default `50`)
- `default_synthesis_threshold` (default `0.6`)
- `positive_endorsement_threshold` (default `0.5`)
- `negative_endorsement_threshold` (default `-0.5`)
- Metrics and rate limiting toggles mirror the environment variables listed below.

Environment overrides include `MCP_LOG_LEVEL`, `MCP_ENABLE_METRICS`, `MCP_PROMETHEUS`, `MCP_RATE_LIMIT_OPS`, and related variables documented in the Metrics section.

## Response Format (JSON)

All tools return JSON in a single envelope:

Success:

```json
{"status":"success","result":{}}
```

Error:

```json
{"status":"error","error":"<code>","message":"<optional>","details":{}}
```

## Tools

The server provides 10 MCP tools:

### 1. Start Collaborative Reasoning
```json
{
  "tool": "start_collaborative_reasoning",
  "arguments": {
    "problem": "Should we adopt microservices architecture?",
    "agentLenses": ["analytical", "skeptical", "pragmatic", "creative"]
  }
}
```

Success response:

```json
{
  "status": "success",
  "result": {
    "sessionId": "<uuid>",
    "problem": "Should we adopt microservices architecture?",
    "agentLenses": ["analytical", "skeptical", "pragmatic", "creative"],
    "lensDescriptions": {
      "analytical": {"focus": "...", "bias_check": "..."}
    }
  }
}
```

### 2. Contribute Perspective
```json
{
  "tool": "contribute_perspective",
  "arguments": {
    "sessionId": "...",
    "agentLens": "analytical",
    "thought": "Let's examine the scalability benefits versus operational complexity...",
    "buildsOn": [1, 3],
    "weight": 0.8
  }
}
```

### 3. Endorse or Challenge
```json
{
  "tool": "endorse_or_challenge",
  "arguments": {
    "sessionId": "...",
    "thoughtId": 2,
    "agentLens": "skeptical",
    "endorsementLevel": -0.6,
    "note": "This overlooks the deployment complexity and team size constraints"
  }
}
```

### 4. Synthesize Convergence
```json
{
  "tool": "synthesize_convergence",
  "arguments": {
    "sessionId": "...",
    "threshold": 0.6
  }
}
```

Returns a JSON `result` containing convergence score, consensus, tensions, cycles, and contribution counts.

### 5. Propose Integration
```json
{
  "tool": "propose_integration",
  "arguments": {
    "sessionId": "...",
    "agentLens": "pragmatic",
    "integration": "Adopt microservices incrementally, starting with highest-value domains...",
    "reconciles": [2, 4, 7]
  }
}
```

### 6. Get Convergence Map
```json
{
  "tool": "get_convergence_map",
  "arguments": {
    "sessionId": "..."
  }
}
```

Returns JSON. The `result.mapText` field contains an ASCII-only human-readable map.

Success response (shape):

```json
{
  "status": "success",
  "result": {
    "sessionId": "<uuid>",
    "convergenceScore": 0.67,
    "mapText": "..."
  }
}
```

Example error (no active session):

```json
{
  "status": "error",
  "error": "no_active_session"
}
```

### 7. Get Active Session
```json
{
  "tool": "get_active_session"
}
```

### 8. Get Metrics
```json
{
  "tool": "get_metrics"
}
```
Returns counters, average latencies, and config info.

### 9. Get Rate Status
```json
{
  "tool": "get_rate_status"
}
```
Returns per-agent operation counts in the current sliding window.

### 10. Reset Agent Rate (Admin)
```json
{
  "tool": "reset_agent_rate",
  "arguments": {
    "agentLens": "analytical"
  }
}
```
Clears the rate-limit window for an agent, allowing new operations immediately.


## Limits

Controlled via environment variables:

- `MCP_MAX_THOUGHTS_PER_SESSION` (default `1000`)
- `MCP_MAX_ENDORSEMENTS_PER_THOUGHT` (default `100`)
- `MCP_MAX_THOUGHTS_PER_AGENT` (default `50`)

## Related

(No related servers listed.)

## Metrics & Prometheus

This MCP implementation exposes lightweight in-memory metrics and optional observability features.

- JSON periodic export (atomic write): enable with `MCP_METRICS_EXPORT=1`. Default path: `/tmp/mcp_metrics.json`.
- Prometheus scrape endpoint: enable with `MCP_PROMETHEUS=1`. Defaults: listen address `127.0.0.1` and port `8000`.
- Rate limiting: control per-agent operation limits with `MCP_RATE_LIMIT_OPS` and `MCP_RATE_LIMIT_WINDOW_S`.

Important environment variables:

- `MCP_ENABLE_METRICS` (default `1`) — enable metrics collection.
- `MCP_METRICS_EXPORT` (default `0`) — enable periodic JSON export.
- `MCP_METRICS_EXPORT_PATH` (default `/tmp/mcp_metrics.json`) — JSON export path.
- `MCP_METRICS_EXPORT_INTERVAL` (seconds, default `30`) — export interval.
- `MCP_PROMETHEUS` (default `0`) — enable Prometheus `/metrics` endpoint.
- `MCP_PROMETHEUS_ADDR` (default `127.0.0.1`) — bind address for Prometheus endpoint.
- `MCP_PROMETHEUS_PORT` (default `8000`) — port for Prometheus endpoint.
- `MCP_RATE_LIMIT_OPS` (default `5`) — allowed ops per agent per sliding window.
- `MCP_RATE_LIMIT_WINDOW_S` (default `60`) — sliding window seconds for rate limiting.

Quick example (enable Prometheus):

```bash
export MCP_PROMETHEUS=1
export MCP_PROMETHEUS_ADDR=127.0.0.1
export MCP_PROMETHEUS_PORT=8000
python server.py
```

You can then curl or configure Prometheus to scrape:

```bash
curl http://127.0.0.1:8000/metrics
```
