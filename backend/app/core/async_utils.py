"""统一的 asyncio 事件循环管理工具"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def get_safe_event_loop() -> asyncio.AbstractEventLoop:
    """
    安全获取事件循环，兼容后台任务、线程池等多种执行上下文。

    使用场景：
    - 后台任务（APScheduler、Celery 等）
    - 线程池中运行的代码
    - 异步上下文中的同步代码
    - 任何可能遇到 RuntimeError: no running event loop 的场景

    Returns:
        asyncio.AbstractEventLoop: 可用的事件循环实例
    """
    try:
        # 首先尝试获取正在运行的循环
        return asyncio.get_running_loop()
    except RuntimeError:
        # 没有正在运行的循环，尝试获取或创建
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logger.debug("创建了新的事件循环（原循环已关闭）")
            return loop
        except Exception:
            # 兜底方案：创建新循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.debug("创建了新的事件循环（异常兜底）")
            return loop
