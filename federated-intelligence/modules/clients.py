import os
import json
import httpx
import logging
from abc import ABC, abstractmethod
from typing import override
from openai import AsyncOpenAI
import google.generativeai as genai

from .models import ConsultationRequest, ConsultationResponse, ModelInfo, ProviderType, ServerConfig

logger = logging.getLogger("federated_intelligence.clients")

class AIClient(ABC):
    """Abstract base class for AI providers."""
    
    @abstractmethod
    async def consult(self, request: ConsultationRequest) -> ConsultationResponse:
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        ...
    
    @abstractmethod
    async def health_check(self) -> bool:
        ...

class OllamaClient(AIClient):
    def __init__(self, base_url: str = "http://localhost:11434/api"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=60.0)

    @override
    async def consult(self, request: ConsultationRequest) -> ConsultationResponse:
        url = f"{self.base_url}/chat"
        
        messages = []
        if request.messages:
            messages = request.messages
        else:
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.query})

        payload = {
            "model": request.model,
            "messages": messages,
            "stream": False,
            "options": {}
        }
        
        if request.temperature is not None:
            payload["options"]["temperature"] = request.temperature

        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract content from message object
            content = data.get("message", {}).get("content", "")
            
            return ConsultationResponse(
                provider="ollama",
                model=request.model,
                response=content,
                metadata={"duration": data.get("total_duration"), "done": data.get("done")}
            )
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise

    @override
    async def list_models(self) -> list[ModelInfo]:
        try:
            resp = await self.client.get(f"{self.base_url}/tags")
            resp.raise_for_status()
            data = resp.json()
            return [
                ModelInfo(id=m["name"], provider="ollama", description=f"Size: {m.get('size')}")
                for m in data.get("models", [])
            ]
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []

    @override
    async def health_check(self) -> bool:
        try:
            resp = await self.client.get(f"{self.base_url}/tags")
            return resp.status_code == 200
        except Exception:
            return False

class OpenAIClient(AIClient):
    def __init__(self, api_key: str | None = None, base_url: str | None = None, provider_label: ProviderType = "openai"):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.provider_label = provider_label

    @override
    async def consult(self, request: ConsultationRequest) -> ConsultationResponse:
        messages = []
        if request.messages:
            messages = request.messages
        else:
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.query})

        try:
            completion = await self.client.chat.completions.create(
                model=request.model,
                messages=messages,
                temperature=request.temperature or 0.7
            )
            content = completion.choices[0].message.content or ""
            return ConsultationResponse(
                provider=self.provider_label,
                model=request.model,
                response=content,
                metadata={"finish_reason": completion.choices[0].finish_reason}
            )
        except Exception as e:
            logger.error(f"{self.provider_label} error: {e}")
            raise

    @override
    async def list_models(self) -> list[ModelInfo]:
        try:
            models = await self.client.models.list()
            return [
                ModelInfo(id=m.id, provider=self.provider_label, description=f"Owner: {m.owned_by}")
                for m in models.data
            ]
        except Exception as e:
            logger.warning(f"Failed to list {self.provider_label} models: {e}")
            return []

    @override
    async def health_check(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False

class GoogleClient(AIClient):
    def __init__(self, api_key: str | None = None):
        if api_key:
            genai.configure(api_key=api_key)
        self.available = bool(api_key)

    @override
    async def consult(self, request: ConsultationRequest) -> ConsultationResponse:
        if not self.available:
            raise ValueError("Google API key not configured")
        
        try:
            model = genai.GenerativeModel(request.model)
            
            if request.messages:
                # Convert OpenAI format to Gemini format
                history = []
                last_user_message = ""
                
                for msg in request.messages:
                    role = msg["role"]
                    content = msg["content"]
                    
                    if role == "system":
                        # Gemini handles system prompts differently, but for now we can prepend to first user msg
                        # or ignore if we can't set it easily per-request without re-init.
                        # Let's prepend to the next user message or the very first one.
                        pass 
                    elif role == "user":
                        history.append({"role": "user", "parts": [content]})
                        last_user_message = content
                    elif role == "assistant":
                        history.append({"role": "model", "parts": [content]})
                
                # The last message should be the new query, but request.messages might include it or not.
                # If we are using session history, the last message is the user's new query.
                # Gemini chat.send_message takes the new message, history is passed to start_chat.
                
                # Pop the last message if it's from user to use as the 'message' argument
                if history and history[-1]["role"] == "user":
                    current_msg = history.pop()
                    chat = model.start_chat(history=history)
                    resp = await chat.send_message_async(
                        current_msg["parts"][0],
                        generation_config=genai.types.GenerationConfig(
                            temperature=request.temperature
                        )
                    )
                else:
                    # Fallback if no user message at end (shouldn't happen in normal flow)
                    chat = model.start_chat(history=history)
                    resp = await chat.send_message_async(
                        request.query, # Fallback to explicit query param
                        generation_config=genai.types.GenerationConfig(
                            temperature=request.temperature
                        )
                    )
            else:
                # Legacy/Single-turn mode
                prompt = request.query
                if request.system_prompt:
                    prompt = f"System: {request.system_prompt}\n\nUser: {request.query}"
                
                resp = await model.generate_content_async(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=request.temperature
                    )
                )

            return ConsultationResponse(
                provider="google",
                model=request.model,
                response=resp.text,
                metadata={}
            )
        except Exception as e:
            logger.error(f"Google error: {e}")
            raise

    @override
    async def list_models(self) -> list[ModelInfo]:
        if not self.available:
            return []
        try:
            # genai.list_models is synchronous iterator, wrap or run in executor if needed.
            # For this snippet, we'll iterate directly (it's fast enough usually).
            models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    models.append(ModelInfo(id=m.name.replace("models/", ""), provider="google", description=m.description))
            return models
        except Exception as e:
            logger.warning(f"Failed to list Google models: {e}")
            return []

    @override
    async def health_check(self) -> bool:
        return self.available

class ClientFactory:
    _instances: dict[str, AIClient] = {}

    @classmethod
    def get_client(cls, provider: ProviderType, config: ServerConfig) -> AIClient:
        if provider in cls._instances:
            return cls._instances[provider]
        
        client: AIClient
        p_config = config.providers.get(provider)
        
        if not p_config:
             # Should not happen if config is loaded correctly, but fallback
             raise ValueError(f"Provider {provider} not configured")

        if provider == "ollama":
            base_url = p_config.base_url or "http://localhost:11434/api"
            client = OllamaClient(base_url=base_url)
        
        elif provider == "openai":
            client = OpenAIClient(api_key=p_config.api_key, provider_label="openai")
            
        elif provider == "openrouter":
            client = OpenAIClient(
                api_key=p_config.api_key, 
                base_url="https://openrouter.ai/api/v1",
                provider_label="openrouter"
            )
            
        elif provider == "google":
            client = GoogleClient(api_key=p_config.api_key)
            
        else:
            raise ValueError(f"Unknown provider: {provider}")
            
        cls._instances[provider] = client
        return client
