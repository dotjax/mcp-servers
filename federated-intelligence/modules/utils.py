import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

def log_consultation(request: Any, response: Any):
    """Log consultation details to a JSONL file."""
    log_dir = Path(__file__).parent.parent / "_logs"
    log_dir.mkdir(exist_ok=True)
    
    filename = f"consultations-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    filepath = log_dir / filename
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request": {
            "provider": request.provider,
            "model": request.model,
            "query": request.query,
            "system_prompt": request.system_prompt,
            "temperature": request.temperature
        },
        "response": {
            "content": response.response,
            "metadata": response.metadata
        }
    }
    
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"Failed to write to log file: {e}", file=sys.stderr)
