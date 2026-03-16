"""
Application Configuration
"""

from pydantic_settings import BaseSettings
from typing import List
import os
import logging

class Settings(BaseSettings):
    """Application settings"""
    
    # App
    APP_NAME: str = "QuantAgent OS"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://quantagent:quantagent@localhost:5432/quantagent"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # ClickHouse (Time-Series Analytics)
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_DB: str = "quantagent"
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""

    # NATS (Message Queue — Phase B)
    NATS_URL: str = "nats://localhost:4222"

    # JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Exchange API (for future use)
    BINANCE_API_KEY: str = ""
    BINANCE_SECRET_KEY: str = ""
    BINANCE_PRIVATE_KEY_PATH: str = ""
    SYMBOLS: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
    
    # CoinGecko API
    COINGECKO_API_KEY: str = ""
    
    # Proxy Settings
    HTTP_PROXY: str = ""
    HTTPS_PROXY: str = ""
    
    # AI/LLM Settings
    LLM_PROVIDER: str = "openai"  # openai, ollama, anthropic
    
    # Embedding Settings
    EMBEDDING_PROVIDER: str = "openai" # openai, ollama
    EMBEDDING_MODEL: str = "text-embedding-3-small" # or "nomic-embed-text" for ollama
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o"
    
    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"
    # 禁用 Ollama 代理，确保直连本地服务
    OLLAMA_NO_PROXY: bool = False

    # OpenRouter
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openrouter/auto"
    OPENROUTER_SITE_URL: str = "http://localhost:3000"
    OPENROUTER_SITE_NAME: str = "QuantAgent OS"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
print(f"Loaded settings: LLM_PROVIDER={settings.LLM_PROVIDER}, PROXY={settings.HTTP_PROXY}")


# ── Proxy routing utilities ───────────────────────────────────────────────────
#
# Proxy classification for this project:
#
#  NEEDS PROXY  (external services blocked in restricted regions)
#    - Binance API        (api.binance.com)
#    - CoinGecko API      (api.coingecko.com)
#    - OpenAI / compatible (api.openai.com, dashscope, etc.)
#    - OpenRouter         (openrouter.ai)
#
#  NO PROXY  (local / internal services)
#    - ClickHouse         (localhost / Docker internal)
#    - PostgreSQL         (localhost / Docker internal)
#    - Redis              (localhost / Docker internal)
#    - NATS               (localhost / Docker internal)
#    - Ollama             (localhost:11434)
#
# Use get_proxies() for services that need a proxy.
# Use no_proxy_env() context manager when creating clients that must NOT use a proxy.

from typing import Dict, Optional
from contextlib import contextmanager
import os as _os


def get_proxies() -> Dict[str, str]:
    """
    Return a proxies dict for services that require external network access
    (Binance, CoinGecko, OpenAI, OpenRouter, etc.).
    Returns an empty dict when no proxy is configured.
    """
    proxy = settings.HTTP_PROXY or settings.HTTPS_PROXY
    if not proxy:
        return {}
    return {
        "http":  settings.HTTP_PROXY  or settings.HTTPS_PROXY,
        "https": settings.HTTPS_PROXY or settings.HTTP_PROXY,
    }


def get_proxy_url() -> Optional[str]:
    """Return a single proxy URL string, or None if not configured."""
    return settings.HTTP_PROXY or settings.HTTPS_PROXY or None


@contextmanager
def no_proxy_env():
    """
    Context manager that temporarily removes HTTP/HTTPS proxy environment
    variables so that internal services (ClickHouse, Ollama, PostgreSQL, etc.)
    are contacted directly without going through the system proxy.

    Usage::

        with no_proxy_env():
            client = some_lib.connect(host="localhost", ...)
    """
    _keys = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
    _saved = {k: _os.environ.pop(k) for k in _keys if k in _os.environ}
    try:
        yield
    finally:
        _os.environ.update(_saved)

if not settings.DEBUG and os.path.exists(".env"):
    logging.warning("⚠️ SECURITY WARNING: Running in production mode (DEBUG=False) but .env file found. Use environment variables or secrets manager instead.")
