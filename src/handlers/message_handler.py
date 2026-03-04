# TGMonitor/src/handlers/message_handler.py
"""
Telethon NewMessage 事件处理器
负责完整的消息处理流程：
1. 提取消息文本（跳过空消息、系统消息）
2. 检查消息来源是否为被监听的群组
3. 关键词匹配 (KeywordFilter.match)
4. 消息去重 (MonitorService.is_duplicate)
5. 解析发送者信息（Entity 缓存优先）
6. 构建 MonitoredMessage 实体
7. 持久化 (MonitorService.save_message)
8. 高优先级告警（可选）

依赖方向：handlers/ → services/ + filters/

使用方式（由 ClientManager 注册）：
    from handlers.message_handler import create_message_handler

    handler = create_message_handler(account_phone="+86138...")
    client.add_event_handler(handler, events.NewMessage)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Set

from utils.logger import logger, message_logger

if TYPE_CHECKING:
    from telethon import events


# ==================== 被监听群组 ID 集合 ====================
# 由 ClientManager 在启动时加载并注入
_monitored_chat_ids: Set[int] = set()


def set_monitored_chat_ids(chat_ids: Set[int]) -> None:
    """
    设置当前被监听的群组 ID 集合（由 ClientManager 启动时调用）。

    Args:
        chat_ids: Telegram 群组 ID 集合
    """
    global _monitored_chat_ids
    _monitored_chat_ids = chat_ids
    logger.info("📋 Monitored chat IDs loaded: {} groups", len(chat_ids))


def get_monitored_chat_ids() -> Set[int]:
    """获取当前被监听的群组 ID 集合。"""
    return _monitored_chat_ids


async def reload_monitored_chat_ids() -> None:
    """
    从 Service 层重新加载被监听群组 ID 列表。
    可由定时任务调用以支持运行时动态增减群组。

    注意：先清除 Redis 缓存再重新加载，保证能读到 MySQL 最新数据。
    """
    from services.monitored_chat_service import monitored_chat_service

    # 先清除缓存，确保从 MySQL 读取最新数据
    await monitored_chat_service.invalidate_cache()
    chat_ids = await monitored_chat_service.get_all_active_chat_ids()
    set_monitored_chat_ids(set(chat_ids))


def create_message_handler(account_phone: str):
    """
    工厂函数：为指定账号创建消息事件处理器。

    Args:
        account_phone: 执行监听的账号手机号

    Returns:
        异步事件处理函数，可注册到 Telethon client
    """
    # 延迟导入 — 避免模块级别触发 telethon/aiohttp 初始化
    from telethon import events as _events

    from filters.keyword_filter import keyword_filter
    from models.message import MonitoredMessage
    from services.entity_cache_service import entity_cache_service
    from services.monitor_service import monitor_service

    async def on_new_message(event: _events.NewMessage.Event) -> None:
        """
        Telethon NewMessage 事件处理函数。

        流程严格按照技术规划 §9.2 实现：
        1. 提取消息文本 → 2. 检查来源 → 3. 关键词匹配 → 4. 去重
        → 5. 解析发送者 → 6. 构建实体 → 7. 持久化 → 8. 告警
        """
        try:
            # ---- 1. 提取消息文本 ----
            message = event.message
            text = message.text or message.raw_text or ""

            # 跳过空消息 / 纯媒体无文本
            if not text.strip():
                return

            # ---- 2. 检查消息来源 ----
            chat_id = event.chat_id
            if chat_id not in _monitored_chat_ids:
                return

            # ---- 3. 关键词匹配 ----
            filter_result = await keyword_filter.match(text)
            if filter_result is None:
                return  # 未命中任何关键词 → 丢弃

            # ---- 4. 消息去重 ----
            telegram_message_id = message.id
            if await monitor_service.is_duplicate(chat_id, telegram_message_id):
                logger.debug(
                    "🔄 Duplicate message skipped: chat={}, msg_id={}",
                    chat_id,
                    telegram_message_id,
                )
                return

            # ---- 5. 解析发送者信息 ----
            sender_id: int = 0
            sender_username: str | None = None
            sender_display_name: str | None = None

            sender = message.sender
            if sender:
                sender_id = sender.id
                sender_username = getattr(sender, "username", None)
                first_name = getattr(sender, "first_name", "") or ""
                last_name = getattr(sender, "last_name", "") or ""
                sender_display_name = f"{first_name} {last_name}".strip() or None
            else:
                # 尝试从 Entity 缓存获取
                sender_id = message.sender_id or 0
                if sender_id:
                    cached_user = await entity_cache_service.get_user(sender_id)
                    if cached_user:
                        sender_username = cached_user.get("username")
                        sender_display_name = cached_user.get("display_name")

            # 缓存发送者信息（Entity 缓存减少 API 调用）
            if sender and sender_id:
                user_data = {
                    "id": sender_id,
                    "username": sender_username,
                    "display_name": sender_display_name,
                    "first_name": getattr(sender, "first_name", None),
                    "last_name": getattr(sender, "last_name", None),
                }
                await entity_cache_service.cache_user(sender_id, user_data)

            # ---- 6. 获取群组信息（优先缓存，避免 API 调用延迟） ----
            chat_title: str = f"Chat_{chat_id}"

            # 6a. 尝试 entity 缓存
            cached_chat = await entity_cache_service.get_chat(chat_id)
            if cached_chat:
                chat_title = cached_chat.get("title") or chat_title
            else:
                # 6b. 缓存未命中时才调用 Telegram API
                try:
                    chat = await event.get_chat()
                    if chat:
                        chat_title = getattr(chat, "title", "") or chat_title
                        # 缓存群组信息
                        chat_data = {
                            "id": chat_id,
                            "title": chat_title,
                            "username": getattr(chat, "username", None),
                        }
                        await entity_cache_service.cache_chat(chat_id, chat_data)
                except Exception as e:
                    logger.debug("⚠️ get_chat() failed for {}: {}, using fallback title", chat_id, e)

            # ---- 7. 确定消息类型 ----
            if message.reply_to:
                message_type = "reply"
            elif message.media and message.text:
                message_type = "caption"
            else:
                message_type = "text"

            # ---- 8. 构建 MonitoredMessage 实体 ----
            # 处理消息时间：Telethon 返回的 date 是 UTC aware datetime
            msg_date = message.date
            if msg_date and msg_date.tzinfo is not None:
                msg_date = msg_date.replace(tzinfo=None)  # 去掉 tz 存 MySQL

            monitored_msg = MonitoredMessage(
                telegram_message_id=telegram_message_id,
                chat_id=chat_id,
                chat_title=chat_title,
                sender_id=sender_id,
                sender_username=sender_username,
                sender_display_name=sender_display_name,
                message_text=text,
                message_type=message_type,
                reply_to_message_id=message.reply_to.reply_to_msg_id if message.reply_to else None,
                matched_keywords=filter_result.matched_keywords,
                keyword_category=filter_result.category,
                monitor_account_phone=account_phone,
                message_date=msg_date or datetime.now(),
            )

            # ---- 9. 持久化 ----
            saved = await monitor_service.save_message(monitored_msg)

            # 消息专用日志
            message_logger.info(
                "📩 Message matched in \"{}\" | id={} | keywords: {} | category: {} | sender: @{}",
                chat_title,
                saved.id,
                filter_result.matched_keywords,
                filter_result.category,
                sender_username or "unknown",
            )

            # ---- 10. (可选) 高优先级告警 ----
            # 当 brand + risk 同时命中时可触发告警
            # 告警实现预留给 Phase 6

        except Exception as e:
            logger.error(
                "❌ Error processing message from chat={}: {}",
                event.chat_id if event else "unknown",
                e,
            )

    return on_new_message
