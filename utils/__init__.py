"""
Shared utilities for MCP servers.

Provides common logging configuration and helper functions.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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
        # Include any extra fields
        for key in ("session_id", "agent_lens", "thought_id"):
            if hasattr(record, key):
                log_obj[key] = getattr(record, key)
        return json.dumps(log_obj)


def setup_logging(
    server_name: str,
    logs_dir: Optional[Path] = None,
    log_level: Optional[str] = None,
) -> Path:
    """
    Configure logging with console and file handlers.
    
    Args:
        server_name: Name of the server (used in log filename)
        logs_dir: Directory for log files (default: ~/.local/state/mcp/logs/)
        log_level: Log level (default: from MCP_LOG_LEVEL env or DEBUG)
        
    Returns:
        Path to the log file
    """
    # Determine log level
    if log_level is None:
        log_level = os.getenv("MCP_LOG_LEVEL", "DEBUG").upper()
    log_level_value = getattr(logging, log_level, logging.DEBUG)
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level_value)
    root_logger.handlers.clear()
    
    # Console handler (stderr for MCP compatibility)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level_value)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    # Determine logs directory
    if logs_dir is None:
        # Use XDG standard path on Linux
        state_dir = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        logs_dir = state_dir / "mcp" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # File handler (JSON format)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_file = logs_dir / f"{server_name}-{timestamp}.jsonl"
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level_value)
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)
    
    # Align MCP logger with configured level
    logging.getLogger("mcp").setLevel(log_level_value)
    
    logging.info(f"Logging initialized: console + {log_file}")
    
    return log_file
