from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Any
import os
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

ProviderType = Literal["ollama", "openai", "openrouter", "google"]

@dataclass
class ProviderConfig:
    enabled: bool = False
    base_url: str | None = None
    default_model: str | None = None
    api_key: str | None = None

@dataclass
class ServerConfig:
    logging_enabled: bool = False
    defaults: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

def load_config(config_path: Path | None = None) -> ServerConfig:
    """Load config from YAML with environment overrides."""
    path = config_path or Path(__file__).parent.parent / "config.yaml"
    
    raw_config = {}
    if path.exists():
        try:
            with open(path) as f:
                raw_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config.yaml: {e}")

    # Parse into dataclasses
    logging_enabled = bool(raw_config.get("logging_enabled", False))
    if os.getenv("MCP_LOGGING_ENABLED") is not None:
        logging_enabled = os.getenv("MCP_LOGGING_ENABLED").lower() in ("true", "1", "yes")

    defaults = raw_config.get("defaults", {})
    providers_data = raw_config.get("providers", {})
    
    providers = {}
    for p_name in ["ollama", "openai", "openrouter", "google"]:
        p_data = providers_data.get(p_name, {})
        
        # Env overrides
        enabled = p_data.get("enabled", False)
        if os.getenv(f"MCP_{p_name.upper()}_ENABLED"):
            enabled = os.getenv(f"MCP_{p_name.upper()}_ENABLED").lower() == "true"
            
        base_url = p_data.get("base_url")
        if os.getenv(f"MCP_{p_name.upper()}_BASE_URL"):
            base_url = os.getenv(f"MCP_{p_name.upper()}_BASE_URL")
            
        default_model = p_data.get("default_model")
        if os.getenv(f"MCP_{p_name.upper()}_DEFAULT_MODEL"):
            default_model = os.getenv(f"MCP_{p_name.upper()}_DEFAULT_MODEL")
            
        # API keys usually come from standard env vars (OPENAI_API_KEY), but we can support MCP_ prefix too
        api_key = os.getenv(f"MCP_{p_name.upper()}_API_KEY")
        
        providers[p_name] = ProviderConfig(
            enabled=enabled,
            base_url=base_url,
            default_model=default_model,
            api_key=api_key
        )

    return ServerConfig(logging_enabled=logging_enabled, defaults=defaults, providers=providers)

# Global config
CONFIG = load_config()

@dataclass
class ConsultationRequest:
    provider: ProviderType
    model: str
    query: str
    system_prompt: str | None = None
    temperature: float | None = None
    session_id: str | None = None
    messages: list[dict[str, str]] | None = None

@dataclass
class ConsultationResponse:
    provider: ProviderType
    model: str
    response: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ModelInfo:
    id: str
    provider: ProviderType
    description: str | None = None
