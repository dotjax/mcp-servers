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
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for shared utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Icon

from utils import setup_logging

# Import models and helpers from the `modules` package
from modules.models import AGENT_LENSES, stop_metrics_exporter, stop_prometheus_server

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

# Create icon from SVG file using file:// URI
_icon_path = Path(__file__).parent / "assets" / "icon.svg"
_server_icon = Icon(
    src=f"file://{_icon_path.resolve()}",
    mimeType="image/svg+xml",
)

server = Server(
    "Ensemble Reasoning",
    icons=[_server_icon],
)

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
        logger.exception("Tool error")
        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "error": "internal_error",
                    "message": "Tool execution failed",
                    "details": {"tool": name, "reason": str(e)},
                }),
            )
        ]


# ============================================================================
# Main
# ============================================================================


async def main():
    """Run the MCP server"""
    # Setup logging using shared utils (logs to ~/.local/state/mcp/logs/)
    log_file = setup_logging("ensemble-reasoning")
    logger.debug("server starting log_file=%s", log_file)

    try:
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
                    icons=[_server_icon],
                ),
            )
    finally:
        stop_metrics_exporter()
        stop_prometheus_server()


if __name__ == "__main__":
    asyncio.run(main())
