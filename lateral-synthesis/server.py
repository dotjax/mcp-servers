#!/usr/bin/env python3
"""
Lateral Synthesis MCP Server

An MCP server that injects divergent concepts into reasoning,
forces bridging connections, and captures meta-reflection.

Flow: Origin → Divergence → Synthesis → Reflection
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

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Icon

from utils import setup_logging
from modules.models import CONNECTION_TYPES, get_config
from modules.tools import TOOL_HANDLERS


# -----------------------------------------------------------------------------
# Tool Definitions
# -----------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="start_session",
        description="Start a new lateral synthesis session with an origin concept. The origin is the starting point for generating divergent ideas.",
        inputSchema={
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "The starting concept, phrase, or question (max 1000 characters)",
                },
                "method": {
                    "type": "string",
                    "enum": ["random"],
                    "description": "Divergence generation method (default: random)",
                },
            },
            "required": ["origin"],
        },
    ),
    Tool(
        name="generate_divergence",
        description="Generate divergent concepts for the current session. These are intentionally unrelated concepts to force lateral thinking. Use override=true to regenerate and reset syntheses.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional, uses current session if not provided)",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of divergent concepts to generate (default: 5)",
                },
                "override": {
                    "type": "boolean",
                    "description": "Regenerate concepts even if already generated (resets syntheses and reflection)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="record_synthesis",
        description="Record a synthesis connecting the origin to one divergent concept. Must be called for each divergent concept.",
        inputSchema={
            "type": "object",
            "properties": {
                "divergent_concept": {
                    "type": "string",
                    "description": "The divergent concept being synthesized (must match one from the session)",
                },
                "connection_type": {
                    "type": "string",
                    "enum": CONNECTION_TYPES,
                    "description": "Type of connection: analogy, contrast, causal, metaphor, structural, arbitrary, or other",
                },
                "connection_type_detail": {
                    "type": "string",
                    "description": "Required explanation if connection_type is 'other'",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Confidence in the connection (0.0-1.0)",
                },
                "insight": {
                    "type": "string",
                    "description": "The bridging insight or connection between origin and divergent concept",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional, uses current session if not provided)",
                },
            },
            "required": ["divergent_concept", "connection_type", "confidence", "insight"],
        },
    ),
    Tool(
        name="reflect_on_session",
        description="Record meta-reflection after all syntheses are complete. Requires all divergent concepts to be synthesized first.",
        inputSchema={
            "type": "object",
            "properties": {
                "most_valuable_insight": {
                    "type": "string",
                    "description": "Which synthesis was most valuable",
                },
                "why_valuable": {
                    "type": "string",
                    "description": "Why that insight was valuable",
                },
                "surprising_connections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of divergent concepts that yielded unexpected connections",
                },
                "overall_rating": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Overall productivity rating for the session (0.0-1.0)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional, uses current session if not provided)",
                },
            },
            "required": ["most_valuable_insight", "why_valuable", "surprising_connections", "overall_rating"],
        },
    ),
    Tool(
        name="get_session",
        description="Retrieve the current session state, including origin, divergent concepts, syntheses, and reflection.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional, uses current session if not provided)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="list_sessions",
        description="List all sessions, both in-memory and from history.",
        inputSchema={
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "Include completed sessions from disk history (default: false)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of sessions to return (default: 20)",
                },
            },
            "required": [],
        },
    ),
]


# -----------------------------------------------------------------------------
# Server Setup
# -----------------------------------------------------------------------------

# Create icon from SVG file using file:// URI
_icon_path = Path(__file__).parent / "assets" / "icon.svg"
_server_icon = Icon(
    src=f"file://{_icon_path.resolve()}",
    mimeType="image/svg+xml",
)

server = Server(
    "Lateral Synthesis",
    icons=[_server_icon],
)
logger = logging.getLogger(__name__)


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return the list of available tools."""
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch tool calls to the appropriate handler."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return [TextContent(
            type="text",
            text=json.dumps({"status": "error", "error": "unknown_tool", "message": f"Unknown tool: {name}"})
        )]
    
    logger.debug(f"Calling tool: {name} with args: {arguments}")
    
    try:
        result = await handler(arguments or {})
        
        return result
    except Exception as e:
        logger.exception("Error in tool %s", name)
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error": "internal_error",
                "message": "Tool execution failed",
                "details": {"tool": name, "reason": str(e)},
            })
        )]


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

async def main():
    """Run the MCP server."""
    # Load config first so we can gate logging (disabled by default)
    config = get_config()
    if config.logging_enabled:
        setup_logging("lateral-synthesis")
        logger.info("Starting Lateral Synthesis MCP server")
        logger.info(f"Config: divergence.method={config.divergence.method}, divergence.count={config.divergence.count}")
    else:
        logging.disable(logging.CRITICAL)
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="Lateral Synthesis",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
                icons=[_server_icon],
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
