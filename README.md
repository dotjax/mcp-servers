# mcp

This repository contains two local MCP servers:

- **ensemble-reasoning**: a collaborative multi-lens reasoning framework (analytical/skeptical/creative/pragmatic/ethical) with synthesis and convergence mapping.
- **lateral-synthesis**: a divergent thinking tool that injects random concepts to force novel connections (Origin → Divergence → Synthesis).

## Repo layout

- `ensemble-reasoning/` — Ensemble Reasoning MCP server
- `lateral-synthesis/` — Lateral Synthesis MCP server
- `_logs/` — runtime log output (ignored by git)

## Requirements

- Python 3.10+
- `mcp` Python package (see each server’s `requirements.txt`)

Install dependencies (global environment):

```bash
pip install -r ensemble-reasoning/requirements.txt
pip install -r lateral-synthesis/requirements.txt
```

## Running the servers

Ensemble Reasoning:

```bash
python ensemble-reasoning/server.py
```

Lateral Synthesis:

```bash
python lateral-synthesis/server.py
```

## Logging

Both servers default to **DEBUG** logging and write:

- Console logs (useful for VS Code OUTPUT / terminal)
- JSONL logs per run under `_logs/`:
  - `_logs/ensemble-reasoning-YYYYMMDDTHHMMSS.jsonl`
  - `_logs/lateral-synthesis-YYYYMMDDTHHMMSS.jsonl`

`_logs/` is ignored via `.gitignore`.

### Tuning verbosity

- Ensemble Reasoning: `ENSEMBLE_LOG_LEVEL=INFO`
- Lateral Synthesis: `MCP_LOG_LEVEL=INFO`

Example:

```bash
ENSEMBLE_LOG_LEVEL=INFO python ensemble-reasoning/server.py
MCP_LOG_LEVEL=INFO python lateral-synthesis/server.py
```

 
