"""
测试 Ollama 连接
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.llm.ollama_provider import OllamaProvider
from app.core.config import settings

async def test_ollama():
    print("=" * 60)
    print("测试 Ollama API 连接")
    print(f"URL: {settings.OLLAMA_BASE_URL}")
    print(f"Model: {settings.OLLAMA_MODEL}")
    print("=" * 60)
    
    provider = OllamaProvider()
    
    try:
        print(f"正在调用 Ollama...")
        response = await provider.generate(
            prompt="用一句话解释什么是量化交易。",
            system_prompt="你是一个专业的金融交易员。"
        )
        print("\n✅ 测试成功！响应内容：")
        print("-" * 60)
        print(response)
        print("-" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        print("\n提示: 请确保 Ollama 服务已启动 (curl http://localhost:11434)")
        print(f"并且模型 '{settings.OLLAMA_MODEL}' 已下载 (ollama pull {settings.OLLAMA_MODEL})")

if __name__ == "__main__":
    asyncio.run(test_ollama())
