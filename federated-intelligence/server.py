#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for shared utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Icon
from modules.tools import register_tools
from utils import setup_logging

# Initialize Server
# Create icon from SVG file using file:// URI
_icon_path = Path(__file__).parent / "assets" / "icon.svg"
_server_icon = Icon(
    src=f"file://{_icon_path.resolve()}",
    mimeType="image/svg+xml",
)

server = Server(
    "Federated Intelligence",
    icons=[_server_icon],
)

# Setup Logging
# Logs to ~/.local/state/mcp/logs/federated-intelligence-*.jsonl
log_file = setup_logging("federated-intelligence")
logger = logging.getLogger(__name__)

async def main():
    # Register tools
    register_tools(server)
    
    logger.info("Starting Federated Intelligence MCP Server...")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="Federated Intelligence",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
                icons=[_server_icon],
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
