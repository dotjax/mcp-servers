# MCP Servers

Two local Model Context Protocol (MCP) servers:

- Ensemble Reasoning: a collaborative, multi‑lens reasoning framework (analytical, skeptical, creative, pragmatic, ethical) with synthesis and convergence mapping.
- Lateral Synthesis: a divergent‑thinking tool that injects random concepts to provoke novel connections (Origin → Divergence → Synthesis).

## Repository Structure

- `ensemble-reasoning/` — Ensemble Reasoning MCP server
- `lateral-synthesis/` — Lateral Synthesis MCP server
- `_logs/` — runtime logs (ignored by Git)

## Requirements

- Python 3.10+
- `mcp` Python package (installed via each server’s `requirements.txt`)

## Setup

Install dependencies (you may prefer a virtual environment):

```bash
pip install -r ensemble-reasoning/requirements.txt
pip install -r lateral-synthesis/requirements.txt
```

## Run

Ensemble Reasoning:

```bash
python ensemble-reasoning/server.py
```

Lateral Synthesis:

```bash
python lateral-synthesis/server.py
```

## Logging

The `_logs/` directory is ignored via `.gitignore`. Both servers default with DEBUG to write console logs (terminal output) and JSON Lines files under `_logs/`, for example:

- `_logs/ensemble-reasoning-YYYYMMDDTHHMMSS.jsonl`
- `_logs/lateral-synthesis-YYYYMMDDTHHMMSS.jsonl`

### Configure Verbosity

Set `MCP_LOG_LEVEL` (e.g., `INFO`). Examples:

- `MCP_LOG_LEVEL=INFO python ensemble-reasoning/server.py`
- `MCP_LOG_LEVEL=INFO python lateral-synthesis/server.py`

 
