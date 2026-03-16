"""
Ollama LLM Provider
"""

from typing import AsyncGenerator
import aiohttp
import json
from app.core.config import settings
from app.services.llm.base import LLMProvider

class OllamaProvider(LLMProvider):
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL

    def _make_session(self) -> aiohttp.ClientSession:
        """
        Create an aiohttp session that bypasses any system proxy.
        Ollama runs locally (localhost / host.docker.internal), so it must
        never go through an HTTP proxy.
        """
        return aiohttp.ClientSession(trust_env=False)

    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """
        Ollama API implementation
        Docs: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-completion
        """
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": kwargs
        }
        
        if system_prompt:
            payload["system"] = system_prompt
            
        async with self._make_session() as session:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get("response", "")

    async def stream(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": kwargs
        }
        
        if system_prompt:
            payload["system"] = system_prompt
            
        async with self._make_session() as session:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                async for line in response.content:
                    if line:
                        try:
                            chunk = json.loads(line)
                            if not chunk.get("done"):
                                yield chunk.get("response", "")
                        except json.JSONDecodeError:
                            pass
