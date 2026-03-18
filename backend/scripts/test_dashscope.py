"""
测试 Dashscope (OpenAI 兼容) 连接
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.llm.openai_provider import OpenAIProvider
from app.core.config import settings

async def test_dashscope():
    print("=" * 60)
    print("测试 Dashscope (OpenAI 兼容) API 连接")
    print(f"Base URL: {settings.OPENAI_BASE_URL}")
    print(f"Model: {settings.OPENAI_MODEL}")
    print(f"API Key: {settings.OPENAI_API_KEY[:8]}...{settings.OPENAI_API_KEY[-4:]}")
    print(f"Proxy: {settings.HTTP_PROXY}")
    print("=" * 60)
    
    # 强制指定 provider 为 openai
    provider = OpenAIProvider()
    
    try:
        print(f"正在调用 Dashscope...")
        response = await provider.generate(
            prompt="你好，请用一句话自我介绍。",
            system_prompt="你是一个专业的量化交易助手。"
        )
        print("\n✅ 测试成功！响应内容：")
        print("-" * 60)
        print(response)
        print("-" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_dashscope())
