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

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from modules.models import CONNECTION_TYPES, get_config
from modules.tools import TOOL_HANDLERS

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "session_id"):
            log_obj["session_id"] = record.session_id
        return json.dumps(log_obj)


def setup_logging() -> None:
    """Configure logging with console and file handlers."""
    log_level = os.getenv("MCP_LOG_LEVEL", "DEBUG").upper()
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.DEBUG))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler (stderr for MCP compatibility)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    # File handler (JSON format)
    logs_dir = Path(__file__).parent.parent / "_logs"
    logs_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    log_file = logs_dir / f"lateral-synthesis-{timestamp}.jsonl"
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)
    
    logging.info(f"Logging initialized: console + {log_file}")


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

server = Server("lateral-synthesis")
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
        logger.exception(f"Error in tool {name}")
        return [TextContent(
            type="text",
            text=json.dumps({"status": "error", "error": "internal_error", "message": str(e)})
        )]


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

async def main():
    """Run the MCP server."""
    setup_logging()
    logger.info("Starting Lateral Synthesis MCP server")
    
    # Load config
    config = get_config()
    logger.info(f"Config: divergence.method={config.divergence.method}, divergence.count={config.divergence.count}")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
