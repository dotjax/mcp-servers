# Lateral Synthesis MCP Server

Inject divergent concepts into a problem, force bridges, and capture reflection.

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

`MCP_LOG_LEVEL` controls verbosity (default DEBUG). Logs stream to stderr and `_logs/lateral-synthesis-*.jsonl`.

## Config

Config file: `config.yaml`

- `divergence.method` (default `random`)
- `divergence.count` (default `5`)
- `persistence.enabled` (default `true`) — snapshots and completed sessions to `_logs/`
- `limits.max_origin_chars` (default `1000`)
- `limits.max_insight_chars` (default `2000`)

Env overrides:
- `MCP_DIVERGENCE_METHOD`
- `MCP_DIVERGENCE_COUNT`
- `MCP_PERSISTENCE_ENABLED`

## Tools

All responses are JSON wrapped as `{ "status": "success" | "error", ... }`.

- `start_session` — begin a session with an `origin`; optional `method` (random).
- `generate_divergence` — create divergent concepts (default count from config); `override=true` regenerates and clears syntheses/reflection.
- `record_synthesis` — record a connection for one divergent concept; requires `connection_type` (analogy|contrast|causal|metaphor|structural|arbitrary|other), `confidence` 0-1, and `insight`.
- `reflect_on_session` — after all syntheses, record reflection with `most_valuable_insight`, `why_valuable`, `surprising_connections`, `overall_rating` 0-1.
- `get_session` — fetch current session state and completeness flags.
- `list_sessions` — list in-memory sessions; with `include_history=true`, merges saved sessions from `_logs/`.

## Typical Flow

1) `start_session` with your origin.
2) `generate_divergence` to get concepts.
3) For each concept, call `record_synthesis`.
4) When all syntheses are done, call `reflect_on_session`.
5) Use `get_session` anytime or `list_sessions` to inspect history.
