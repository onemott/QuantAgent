"""
LLM Service Interface and Factory
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, AsyncGenerator
import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """Generate text from prompt"""
        pass
    
    @abstractmethod
    async def stream(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """Stream text from prompt"""
        pass

    def _format_market_data(self, data: Dict[str, Any]) -> str:
        """Helper to format market data into prompt context"""
        return json.dumps(data, indent=2)


class LLMFactory:
    """Factory to create LLM provider instances"""
    
    @staticmethod
    def create_provider(provider_name: str = None) -> LLMProvider:
        provider = provider_name or settings.LLM_PROVIDER
        logger.info(f"Creating LLM provider: {provider} (requested: {provider_name})")
        
        try:
            if provider == "openai":
                from app.services.llm.openai_provider import OpenAIProvider
                return OpenAIProvider()
            elif provider == "ollama":
                from app.services.llm.ollama_provider import OllamaProvider
                return OllamaProvider()
            elif provider == "openrouter":
                from app.services.llm.openrouter_provider import OpenRouterProvider
                return OpenRouterProvider()
            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")
        except Exception as e:
            logger.error(f"Error creating provider {provider}: {e}")
            raise
