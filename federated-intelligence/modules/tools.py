import logging
import asyncio
from pathlib import Path
from mcp.types import Tool, TextContent
from mcp.server import Server

from .models import ConsultationRequest, ProviderType, CONFIG
from .clients import ClientFactory
from .utils import log_consultation
from .sessions import SessionManager

logger = logging.getLogger("federated_intelligence.tools")
session_manager = SessionManager(Path(__file__).parent.parent / "_logs" / "sessions")

async def tool_consult_model(args: dict) -> list[TextContent]:
    """
    Consult an external AI model.
    """
    provider: ProviderType = args["provider"]
    query: str = args["query"]
    model: str = args.get("model")
    system_prompt: str | None = args.get("system_prompt")
    session_id: str | None = args.get("session_id")
    
    # Fallback to default model from config if not provided
    if not model:
        model = CONFIG.providers.get(provider).default_model if CONFIG.providers.get(provider) else None
        if not model:
            return [TextContent(type="text", text=f"Error: No model specified and no default configured for {provider}")]

    try:
        # Pass the full ServerConfig object to the factory
        client = ClientFactory.get_client(provider, CONFIG)
        
        messages = None
        if session_id:
            session = session_manager.get_session(session_id)
            if not session:
                return [TextContent(type="text", text=f"Error: Session {session_id} not found. Use 'create_session' to start a new session.")]
            
            # Add user message to session
            session_manager.add_message(session_id, "user", query)
            
            # Prepare messages for client
            # Convert session messages to list of dicts
            messages = [{"role": m.role, "content": m.content} for m in session.messages]
            
            # If system prompt provided, prepend it (override session system prompt? or just add?)
            # Usually system prompt is static. Let's assume if provided in args, it's the system prompt.
            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

        req = ConsultationRequest(
            provider=provider,
            model=model,
            query=query,
            system_prompt=system_prompt,
            temperature=args.get("temperature"),
            session_id=session_id,
            messages=messages
        )
        
        # Log INFO as per requirements
        logger.info(f"Consulting {provider}/{model} (Session: {session_id})...")
        
        response = await client.consult(req)
        
        # Log to file
        log_consultation(req, response)
        
        # Update session with response
        if session_id:
            session_manager.add_message(session_id, "assistant", response.response)
            return [TextContent(type="text", text=f"Session ID: {session_id}\n\n{response.response}")]
        
        return [TextContent(type="text", text=response.response)]
        
    except Exception as e:
        logger.error(f"Consultation failed: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def tool_consult_multiple_models(args: dict) -> list[TextContent]:
    """
    Consult multiple models in parallel with the same query.
    """
    models_config: list[dict] = args["models"] # List of {provider, model}
    query: str = args["query"]
    
    async def consult_one(cfg):
        provider = cfg["provider"]
        model = cfg.get("model")
        # Fallback default
        if not model:
            model = CONFIG.providers.get(provider).default_model
            
        try:
            client = ClientFactory.get_client(provider, CONFIG)
            req = ConsultationRequest(
                provider=provider,
                model=model,
                query=query,
                temperature=args.get("temperature")
            )
            resp = await client.consult(req)
            log_consultation(req, resp)
            return f"### {provider}/{model}\n{resp.response}\n"
        except Exception as e:
            return f"### {provider}/{model}\nError: {e}\n"

    results = await asyncio.gather(*[consult_one(cfg) for cfg in models_config])
    return [TextContent(type="text", text="\n".join(results))]

async def tool_create_session(args: dict) -> list[TextContent]:
    """Create a new chat session."""
    session = session_manager.create_session(metadata=args.get("metadata"))
    return [TextContent(type="text", text=session.id)]

async def tool_list_sessions(args: dict) -> list[TextContent]:
    """List active sessions."""
    sessions = session_manager.list_sessions()
    text = "Active Sessions:\n"
    for s in sessions:
        text += f"- {s['id']} ({s['created_at']}): {s['message_count']} msgs - {s['preview']}\n"
    return [TextContent(type="text", text=text)]


async def tool_list_models(args: dict) -> list[TextContent]:
    """
    List available models for a provider.
    """
    provider: ProviderType = args["provider"]
    try:
        client = ClientFactory.get_client(provider, CONFIG)
        models = await client.list_models()
        
        text = f"Available models for {provider}:\n"
        for m in models:
            text += f"- {m.id}"
            if m.description:
                text += f" ({m.description})"
            text += "\n"
            
        return [TextContent(type="text", text=text)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error listing models: {str(e)}")]

async def tool_health_check(args: dict) -> list[TextContent]:
    """
    Check health of configured providers.
    """
    results = {}
    
    for p_name, p_config in CONFIG.providers.items():
        if p_config.enabled:
            try:
                client = ClientFactory.get_client(p_name, CONFIG)
                alive = await client.health_check()
                results[p_name] = "OK" if alive else "Unreachable"
            except Exception as e:
                results[p_name] = f"Error: {str(e)}"
        else:
            results[p_name] = "Disabled"
            
    return [TextContent(type="text", text=str(results))]

TOOLS_HANDLERS = {
    "consult_model": tool_consult_model,
    "consult_multiple_models": tool_consult_multiple_models,
    "create_session": tool_create_session,
    "list_sessions": tool_list_sessions,
    "list_models": tool_list_models,
    "health_check": tool_health_check
}

def register_tools(server: Server):
    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="consult_model",
                description="Consult an external AI model (Ollama, OpenAI, Google, OpenRouter). Supports sessions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "enum": ["ollama", "openai", "openrouter", "google"],
                            "description": "The AI provider to use."
                        },
                        "model": {
                            "type": "string",
                            "description": "The model name (e.g., 'llama3', 'gpt-4'). Optional if default is set."
                        },
                        "query": {
                            "type": "string",
                            "description": "The query or prompt to send to the model."
                        },
                        "system_prompt": {
                            "type": "string",
                            "description": "Optional system prompt to set context."
                        },
                        "temperature": {
                            "type": "number",
                            "description": "Sampling temperature (0.0 to 1.0)."
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Session ID to continue a conversation. Use 'new' to start a new session."
                        }
                    },
                    "required": ["provider", "query"]
                }
            ),
            Tool(
                name="consult_multiple_models",
                description="Consult multiple models in parallel with the same query.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "models": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "provider": {"type": "string", "enum": ["ollama", "openai", "openrouter", "google"]},
                                    "model": {"type": "string"}
                                },
                                "required": ["provider"]
                            },
                            "description": "List of models to consult."
                        },
                        "query": {
                            "type": "string",
                            "description": "The query to send to all models."
                        },
                        "temperature": {
                            "type": "number",
                            "description": "Sampling temperature."
                        }
                    },
                    "required": ["models", "query"]
                }
            ),
            Tool(
                name="create_session",
                description="Create a new chat session.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata for the session."
                        }
                    }
                }
            ),
            Tool(
                name="list_sessions",
                description="List active chat sessions.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="list_models",
                description="List available models for a specific provider.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "enum": ["ollama", "openai", "openrouter", "google"],
                            "description": "The provider to list models for."
                        }
                    },
                    "required": ["provider"]
                }
            ),
            Tool(
                name="health_check",
                description="Check connectivity to enabled providers.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
        handler = TOOLS_HANDLERS.get(name)
        if handler:
            return await handler(arguments)
        return [TextContent(type="text", text="Unknown tool")]
