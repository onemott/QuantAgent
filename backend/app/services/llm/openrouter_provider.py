"""
OpenRouter LLM Provider
"""

from typing import AsyncGenerator
import httpx
import openai
from app.core.config import settings, get_proxy_url
from app.services.llm.base import LLMProvider

class OpenRouterProvider(LLMProvider):
    def __init__(self):
        # OpenRouter is an external API — use proxy if configured.
        proxy_url = get_proxy_url()
        http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
        self.client = openai.AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": settings.OPENROUTER_SITE_URL,
                "X-OpenRouter-Title": settings.OPENROUTER_SITE_NAME,
            },
            http_client=http_client,
        )
        self.model = settings.OPENROUTER_MODEL

    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    async def stream(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            **kwargs
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
