#!/usr/bin/env python3
"""
Universal Clock MCP Server

Provides real-time UTC and local time to any AI agent.
This gives temporal awareness within conversations.

This server sends notifications/tools/list_changed every second to force
clients to refresh the tool list, which includes the current time in the
tool description. This achieves true per-message temporal awareness.
"""

import asyncio
from datetime import datetime, timezone
import functools

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.server.session import ServerSession
from mcp.types import Tool, TextContent

server = Server("clock")

# Global reference to the active session for sending notifications
_active_session = None
_notification_task = None


def get_current_time_string():
    """Generate current time string for description."""
    now = datetime.now(timezone.utc)
    local_now = now.astimezone()  # Automatically uses system timezone
    
    utc_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    local_str = local_now.strftime("%Y-%m-%d %I:%M:%S %p %Z")
    day_of_week = local_now.strftime("%A")
    
    return f"{utc_str} | {local_str} ({day_of_week})"


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
            description=f"🕐 **NOW: {current_time}** | Call this tool for a formatted time response.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None):
    """Handle tool calls."""
    if name == "get_current_time":
        now = datetime.now(timezone.utc)
        local_now = now.astimezone()
        
        utc_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        local_str = local_now.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        day_of_week = local_now.strftime("%A")
        tz_name = local_now.strftime("%Z")
        
        result = f"""**Current Time:**
- UTC: {utc_str}
- Local: {local_str} ({day_of_week})
- Timezone: {tz_name}
- Unix Timestamp: {int(now.timestamp())}
- ISO 8601: {now.isoformat()}"""
        
        return [TextContent(type="text", text=result)]
    
    raise ValueError(f"Unknown tool: {name}")


async def time_notification_loop():
    """Background task that sends tool list changed notifications every second."""
    global _active_session, _notification_task
    
    try:
        while True:
            await asyncio.sleep(1)  # Update every second
            
            if _active_session is None:
                break
            
            # Send notification that tool list changed
            await _active_session.send_tool_list_changed()
            
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
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

