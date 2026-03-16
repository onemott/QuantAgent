
import logging
import httpx
import os
from typing import List, Union
from app.core.config import settings, get_proxy_url

logger = logging.getLogger(__name__)


def _should_use_proxy_for_ollama() -> bool:
    """
    检查是否应该为 Ollama 使用代理。
    如果设置了 OLLAMA_NO_PROXY=true，则禁用代理。
    """
    return not settings.OLLAMA_NO_PROXY

class EmbeddingService:
    """
    Service for generating vector embeddings from text.
    Supports OpenAI and Ollama backends.

    Proxy policy:
      - OpenAI / compatible: external API, use system proxy if configured.
      - Ollama:              local service, always connect directly (no proxy).
    """
    
    def __init__(self):
        self.provider = settings.EMBEDDING_PROVIDER.lower()
        self.model = settings.EMBEDDING_MODEL
        
    async def get_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text string.
        """
        if not text:
            return []
            
        try:
            if self.provider == "openai":
                return await self._get_openai_embedding(text)
            elif self.provider == "ollama":
                return await self._get_ollama_embedding(text)
            else:
                logger.warning(f"Unknown embedding provider: {self.provider}")
                return []
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return []

    async def _get_openai_embedding(self, text: str) -> List[float]:
        """
        Use OpenAI API (compatible with v1/embeddings endpoint).
        Connects via system proxy (external service).
        """
        api_key = settings.OPENAI_API_KEY
        if not api_key or not api_key.strip():
            logger.error("OpenAI API Key is missing or empty. Cannot generate embedding.")
            return []

        url = f"{settings.OPENAI_BASE_URL}/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": text,
            "model": self.model
        }

        # OpenAI is an external API — route through proxy if configured.
        proxy_url = get_proxy_url()
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy_url) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]

    async def _get_ollama_embedding(self, text: str) -> List[float]:
        """
        Use Ollama API (/api/embeddings).
        Ollama runs locally — connect directly, no proxy.
        """
        url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        payload = {
            "model": self.model,
            "prompt": text
        }

        # Ollama is a local service — explicitly disable proxy.
        # 同时禁用环境变量中的代理设置，确保直连
        client_kwargs = {"timeout": 10.0, "proxy": None}
        if not _should_use_proxy_for_ollama():
            # 清除环境变量代理，防止 httpx 读取
            old_http_proxy = os.environ.pop("HTTP_PROXY", None)
            old_https_proxy = os.environ.pop("HTTPS_PROXY", None)
            old_http_proxy_lower = os.environ.pop("http_proxy", None)
            old_https_proxy_lower = os.environ.pop("https_proxy", None)

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["embedding"]
        finally:
            # 恢复环境变量
            if not _should_use_proxy_for_ollama():
                if old_http_proxy:
                    os.environ["HTTP_PROXY"] = old_http_proxy
                if old_https_proxy:
                    os.environ["HTTPS_PROXY"] = old_https_proxy
                if old_http_proxy_lower:
                    os.environ["http_proxy"] = old_http_proxy_lower
                if old_https_proxy_lower:
                    os.environ["https_proxy"] = old_https_proxy_lower

# Singleton
embedding_service = EmbeddingService()
