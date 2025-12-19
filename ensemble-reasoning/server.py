#!/usr/bin/env python3
"""
Ensemble Reasoning MCP Server

A collaborative thinking framework where multiple agent lenses work together:
- Different reasoning perspectives (analytical, skeptical, creative, pragmatic, ethical)
- Cross-endorsement and challenge system
- Convergence detection and synthesis
- Integration proposals to resolve tensions
"""

import asyncio
import json
import logging
import os
from datetime import datetime

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import models and helpers from the `modules` package
from modules.models import AGENT_LENSES

# Tool implementations
from modules.tools import (
    tool_start_collaborative,
    tool_contribute,
    tool_endorse_challenge,
    tool_synthesize,
    tool_propose_integration,
    tool_convergence_map,
    tool_get_active_session,
    tool_get_metrics,
    tool_get_rate_status,
    tool_reset_agent_rate,
)

# Logger
logger = logging.getLogger("ensemble_reasoning.server")


# ============================================================================
# MCP Server Setup
# ============================================================================

server = Server("Ensemble Reasoning")

_AGENT_LENS_NAMES = list(AGENT_LENSES.keys())

TOOL_HANDLERS = {
    "start_collaborative_reasoning": tool_start_collaborative,
    "contribute_perspective": tool_contribute,
    "endorse_or_challenge": tool_endorse_challenge,
    "synthesize_convergence": tool_synthesize,
    "propose_integration": tool_propose_integration,
    "get_convergence_map": tool_convergence_map,
    "get_active_session": tool_get_active_session,
    "get_metrics": tool_get_metrics,
    "get_rate_status": tool_get_rate_status,
    "reset_agent_rate": tool_reset_agent_rate,
}


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List all available tools"""
    return [
        Tool(
            name="start_collaborative_reasoning",
            description="Start a collaborative reasoning session with multiple agent lenses working together.",
            inputSchema={
                "type": "object",
                "properties": {
                    "problem": {"type": "string", "description": "The problem to solve collaboratively"},
                    "agentLenses": {
                        "type": "array",
                        "items": {"type": "string", "enum": _AGENT_LENS_NAMES},
                        "description": "Which agent lenses to include (analytical, skeptical, creative, pragmatic, ethical)"
                    }
                },
                "required": ["problem", "agentLenses"]
            }
        ),
        Tool(
            name="contribute_perspective",
            description="Contribute a thought from a specific agent lens perspective.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string", "description": "The ensemble session ID"},
                    "agentLens": {"type": "string", "enum": _AGENT_LENS_NAMES},
                    "thought": {"type": "string", "description": "The insight or reasoning from this lens"},
                    "buildsOn": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Thought IDs this builds upon (from other agents)"
                    },
                    "weight": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Confidence in this perspective (0-1)"
                    }
                },
                "required": ["sessionId", "agentLens", "thought"]
            }
        ),
        Tool(
            name="endorse_or_challenge",
            description="Have one agent lens endorse or challenge another's thought.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string"},
                    "thoughtId": {"type": "integer", "description": "The thought to react to"},
                    "agentLens": {"type": "string", "enum": _AGENT_LENS_NAMES},
                    "endorsementLevel": {
                        "type": "number",
                        "minimum": -1,
                        "maximum": 1,
                        "description": "Agreement level: -1 (disagree) to +1 (fully agree)"
                    },
                    "note": {"type": "string", "description": "Why this lens agrees or disagrees"}
                },
                "required": ["sessionId", "thoughtId", "agentLens", "endorsementLevel"]
            }
        ),
        Tool(
            name="synthesize_convergence",
            description="Analyze the ensemble to find consensus, tensions, and synthesis opportunities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string"},
                    "threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Consensus threshold (default 0.6)"
                    }
                },
                "required": ["sessionId"]
            }
        ),
        Tool(
            name="propose_integration",
            description="Propose a synthesis that integrates multiple perspectives.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string"},
                    "agentLens": {"type": "string", "enum": _AGENT_LENS_NAMES},
                    "integration": {"type": "string", "description": "The synthesis that reconciles different views"},
                    "reconciles": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Thought IDs being integrated"
                    }
                },
                "required": ["sessionId", "agentLens", "integration", "reconciles"]
            }
        ),
        Tool(
            name="get_convergence_map",
            description="Get a visual overview of where agents agree, disagree, and opportunities for synthesis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string"}
                },
                "required": ["sessionId"]
            }
        ),
        Tool(
            name="get_active_session",
            description="Get details of the current active ensemble session.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_metrics",
            description="Get lightweight runtime metrics: counters and average latencies.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_rate_status",
            description="Get per-agent rate limiter status (current op count in sliding window).",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="reset_agent_rate",
            description="Admin: reset/clear the rate window for a given agent lens.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agentLens": {"type": "string", "enum": _AGENT_LENS_NAMES, "description": "The agent lens to reset"}
                },
                "required": ["agentLens"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        logger.debug("call_tool name=%s args=%s", name, arguments)
        if handler := TOOL_HANDLERS.get(name):
            return await handler(arguments or {})
        return [
            TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": "unknown_tool", "details": {"tool": name}}),
            )
        ]
    except Exception as e:
        logger.error(f"Tool error: {e}")
        return [
            TextContent(
                type="text",
                text=json.dumps({"status": "error", "error": "internal_error", "message": str(e)}),
            )
        ]


# ============================================================================
# Main
# ============================================================================


async def main():
    """Run the MCP server"""
    # Ensure log directory exists
    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_logs"))
    os.makedirs(log_dir, exist_ok=True)

    # Configure logging: console (stderr) + JSON file, default DEBUG
    log_level = os.getenv("ENSEMBLE_LOG_LEVEL", "DEBUG").upper()

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    # Root logger setup
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.DEBUG))

    # Clear existing handlers to avoid duplication on reload
    root.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    root.addHandler(console_handler)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    log_path = os.path.join(log_dir, f"ensemble-reasoning-{ts}.jsonl")
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(getattr(logging, log_level, logging.DEBUG))
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)

    # Make MCP verbose too
    logging.getLogger("mcp").setLevel(logging.DEBUG)
    logger.debug("server starting log_level=%s log_file=%s", log_level, log_path)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="Ensemble Reasoning",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
