
import asyncio
import os
import sys

# Add backend to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.core.config import settings
from backend.app.services.llm.base import LLMFactory

async def test_all_providers():
    providers = ["openai", "ollama", "openrouter"]
    print(f"Current LLM_PROVIDER in settings: {settings.LLM_PROVIDER}")
    
    for provider_name in providers:
        print(f"\n--- Testing Provider: {provider_name} ---")
        try:
            provider = LLMFactory.create_provider(provider_name)
            # Try a very simple prompt
            response = await asyncio.wait_for(
                provider.generate("Say 'Hello'"),
                timeout=10.0
            )
            print(f"✅ {provider_name} is working!")
            print(f"Response: {response}")
        except Exception as e:
            print(f"❌ {provider_name} failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_all_providers())
