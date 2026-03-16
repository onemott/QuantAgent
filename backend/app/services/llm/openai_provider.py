"""
OpenAI LLM Provider
"""

from typing import AsyncGenerator
import httpx
import openai
from app.core.config import settings, get_proxy_url
from app.services.llm.base import LLMProvider

class OpenAIProvider(LLMProvider):
    def __init__(self):
        print(f"Initializing OpenAIProvider with API Key: {settings.OPENAI_API_KEY[:5]}... Base URL: {settings.OPENAI_BASE_URL}")
        # OpenAI / compatible APIs are external services — use proxy if configured.
        proxy_url = get_proxy_url()
        http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
        self.client = openai.AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            http_client=http_client,
        )
        self.model = settings.OPENAI_MODEL

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
