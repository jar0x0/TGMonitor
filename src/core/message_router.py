# TGMonitor/src/core/message_router.py
"""
消息路由模块
负责：
1. 将 Telethon 事件解耦为标准化的消息处理管道
2. 提供消息处理入口，串联 Filter → Service 层

本模块为 MessageHandler 提供高级路由功能。
当前版本的路由逻辑已内联在 message_handler.py 的 on_new_message 中。
本模块提供辅助函数以支持未来的扩展需求（如多 Handler 分发、
消息队列化等）。

使用方式：
    from core.message_router import process_message_text

    result = await process_message_text(text)
"""

from __future__ import annotations

from typing import Optional

from filters.keyword_filter import FilterResult, keyword_filter
from services.monitor_service import monitor_service
from utils.logger import logger


async def process_message_text(text: str) -> Optional[FilterResult]:
    """
    对消息文本执行关键词匹配（路由入口）。

    Args:
        text: 消息文本

    Returns:
        FilterResult: 匹配结果，或 None
    """
    return await keyword_filter.match(text)


async def check_duplicate(chat_id: int, telegram_message_id: int) -> bool:
    """
    检查消息是否重复（路由级去重入口）。

    Args:
        chat_id: Telegram 群组 ID
        telegram_message_id: Telegram 消息 ID

    Returns:
        bool: True 表示重复
    """
    return await monitor_service.is_duplicate(chat_id, telegram_message_id)
