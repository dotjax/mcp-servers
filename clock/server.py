#!/usr/bin/env python3
"""
Universal Clock MCP Server

Provides real-time UTC and Kansas City local time to any AI agent.
This gives Lyra temporal awareness within conversations.

This server sends notifications/tools/list_changed every 60 seconds to force
clients to refresh the tool list, which includes the current time in the
tool description. This achieves true per-message temporal awareness.
"""

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import sys
from pathlib import Path
import functools

# Add parent directory to path for shared utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.server.session import ServerSession
from mcp.types import Tool, TextContent, ServerNotification, ToolListChangedNotification


# ============================================================================
# MCP Server Setup
# ============================================================================

server = Server("clock")

# Global reference to the active session for sending notifications
_active_session = None
_notification_task = None


def get_current_time_string():
    """Generate current time string for description."""
    now = datetime.now(timezone.utc)
    kc_tz = ZoneInfo("America/Chicago")
    kc_now = now.astimezone(kc_tz)
    
    utc_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    kc_str = kc_now.strftime("%Y-%m-%d %I:%M:%S %p %Z")
    day_of_week = kc_now.strftime("%A")
    
    return f"{utc_str} | {kc_str} ({day_of_week})"


@server.list_tools()
async def handle_list_tools():
    """List available tools - description includes CURRENT time!"""
    global _active_session, _notification_task
    
    current_time = get_current_time_string()
    
    # Start the notification task if not already running or if it died
    if _active_session is not None:
        if _notification_task is None or _notification_task.done():
            _notification_task = asyncio.create_task(time_notification_loop())
    
    return [
        Tool(
            name="get_current_time",
            description=f"🕐 **NOW: {current_time}** | Kansas City, Kansas, USA. Call this tool for a formatted time response.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None):
    """Handle tool calls."""
    if name == "get_current_time":
        now = datetime.now(timezone.utc)
        
        # UTC time
        utc_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Kansas City time (America/Chicago)
        kc_tz = ZoneInfo("America/Chicago")
        kc_now = now.astimezone(kc_tz)
        kc_str = kc_now.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        day_of_week = kc_now.strftime("%A")
        
        result = f"""**Current Time:**
- UTC: {utc_str}
- Kansas City: {kc_str} ({day_of_week})
- Location: Kansas City, Kansas, USA
- Unix Timestamp: {int(now.timestamp())}
- ISO 8601: {now.isoformat()}"""
        
        return [TextContent(type="text", text=result)]
    
    raise ValueError(f"Unknown tool: {name}")


async def time_notification_loop():
    """Background task that sends tool list changed notifications every 60 seconds."""
    global _active_session, _notification_task
    
    try:
        while True:
            await asyncio.sleep(60)  # Update every minute
            
            if _active_session is None:
                break
            
            # Send notification that tool list changed
            await _active_session.send_tool_list_changed()
            
    except asyncio.CancelledError:
        pass  # Clean shutdown
    except Exception:
        # Unexpected error - mark task as done so it can be restarted
        pass
    finally:
        # Clean up global reference so task can be restarted if needed
        if _notification_task is not None and _notification_task.done():
            _notification_task = None


async def main():
    """Main entry point."""
    global _active_session, _notification_task
    
    # Hook into ServerSession.__init__ to capture the session
    original_init = ServerSession.__init__
    
    @functools.wraps(original_init)
    def patched_init(self, *args, **kwargs):
        global _active_session
        original_init(self, *args, **kwargs)
        _active_session = self
    
    ServerSession.__init__ = patched_init
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="clock",
                    server_version="1.0.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(
                            tools_changed=True  # Enable tool list change notifications
                        ),
                        experimental_capabilities={},
                    )
                )
            )
    finally:
        ServerSession.__init__ = original_init
        _active_session = None
        if _notification_task:
            _notification_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())

