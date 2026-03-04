# TGMonitor/src/services/monitor_service.py
"""
消息监听业务逻辑层
负责：
1. Redis 缓存管理（读写一级存储）
2. 调用 MonitorRepository 操作数据库（二级存储）
3. 消息去重
参照 bot/src/services/productService.ts 的完整模式。

使用方式：
    from services.monitor_service import monitor_service

    saved = await monitor_service.save_message(message)
    msg = await monitor_service.get_message_by_id(1)
"""

from __future__ import annotations

from typing import List, Optional

import aiomysql
import redis as redis_lib

from config.redis_client import get_redis
from config.settings import settings
from models.message import MonitoredMessage
from repositories.monitor_repository import monitor_repository
from utils.logger import logger


class MonitorService:
    """
    消息监听业务逻辑层
    负责 Redis 缓存管理和调用 MonitorRepository。

    Redis Key 定义为类常量 REDIS_KEYS，所有 Redis 操作在 Service 层完成。
    MySQL 写失败 → raise；Redis 失败 → 降级告警，不影响主流程。
    """

    REDIS_PREFIX = "monitor:"
    REDIS_KEYS = {
        # 主数据存储
        "MSG_BY_ID": "monitor:msg:id:",              # STRING: 完整消息 JSON
        # 索引
        "MSG_BY_CHAT": "monitor:msg:chat:",           # SET: 按群组索引消息ID
        "MSG_BY_SENDER": "monitor:msg:sender:",       # SET: 按发送者索引消息ID
        "MSG_BY_CATEGORY": "monitor:msg:category:",   # SET: 按关键词分类索引
        # 去重
        "MSG_DEDUP": "monitor:dedup:",                # STRING with TTL: chat_id:telegram_message_id
        # 统计
        "STATS": "monitor:stats",                     # HASH: 各类统计数据
    }

    # ==================== 写入 ====================

    async def save_message(self, message: MonitoredMessage) -> MonitoredMessage:
        """
        保存监听到的消息（两级存储写入）。

        流程：
        1. 写入 MySQL（获取自增 ID）
        2. 写入 Redis 缓存
        3. 更新索引（chat / sender / category）
        4. 标记去重（SETEX，TTL = DEDUP_TTL）

        Args:
            message: MonitoredMessage 实体（id 为 None，由 MySQL 生成）

        Returns:
            MonitoredMessage: 写入后的实体（含 id）

        Raises:
            aiomysql.Error: MySQL 写入失败时抛出
        """
        try:
            # 1. 写入 MySQL（获取自增 ID）
            message.id = await monitor_repository.insert(message)
        except aiomysql.Error as e:
            logger.error(
                "❌ MySQL insert failed for message telegram_msg_id={}, chat_id={}: {}",
                message.telegram_message_id,
                message.chat_id,
                e,
            )
            raise

        # 2~4. Redis 缓存 / 索引 / 去重（Redis 失败不影响主流程）
        try:
            redis = await get_redis()
            if redis:
                # 2. 写入 Redis 主数据
                key = f"{self.REDIS_KEYS['MSG_BY_ID']}{message.id}"
                await redis.set(key, message.model_dump_json())

                # 3. 更新索引
                await redis.sadd(
                    f"{self.REDIS_KEYS['MSG_BY_CHAT']}{message.chat_id}",
                    str(message.id),
                )
                await redis.sadd(
                    f"{self.REDIS_KEYS['MSG_BY_SENDER']}{message.sender_id}",
                    str(message.id),
                )
                if message.keyword_category:
                    await redis.sadd(
                        f"{self.REDIS_KEYS['MSG_BY_CATEGORY']}{message.keyword_category}",
                        str(message.id),
                    )

                # 4. 标记去重
                dedup_key = (
                    f"{self.REDIS_KEYS['MSG_DEDUP']}"
                    f"{message.chat_id}:{message.telegram_message_id}"
                )
                await redis.setex(dedup_key, settings.DEDUP_TTL, "1")

                logger.debug(
                    "📦 Cached message id={} to Redis (chat={}, sender={})",
                    message.id,
                    message.chat_id,
                    message.sender_id,
                )
        except redis_lib.RedisError as e:
            logger.warning(
                "⚠️ Redis cache failed for message id={}: {}",
                message.id,
                e,
            )

        return message

    # ==================== 读取 ====================

    async def get_message_by_id(self, message_id: int) -> Optional[MonitoredMessage]:
        """
        按 ID 获取消息（先查 Redis，未命中查 MySQL 并回写）。

        Args:
            message_id: 数据库自增 ID

        Returns:
            MonitoredMessage 实例，或 None
        """
        # 1. 先查 Redis
        try:
            redis = await get_redis()
            if redis:
                cached = await redis.get(f"{self.REDIS_KEYS['MSG_BY_ID']}{message_id}")
                if cached:
                    logger.debug("🎯 Redis hit for message id={}", message_id)
                    return MonitoredMessage.model_validate_json(cached)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis read failed for message id={}: {}", message_id, e)

        # 2. Redis 未命中，查 MySQL
        message = await monitor_repository.get_by_id(message_id)
        if message is None:
            return None

        # 3. 回写 Redis
        try:
            redis = await get_redis()
            if redis:
                await redis.set(
                    f"{self.REDIS_KEYS['MSG_BY_ID']}{message.id}",
                    message.model_dump_json(),
                )
                logger.debug("📥 Backfilled message id={} to Redis", message.id)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis backfill failed for message id={}: {}", message.id, e)

        return message

    async def get_messages_by_chat(
        self, chat_id: int, limit: int = 50, offset: int = 0
    ) -> List[MonitoredMessage]:
        """
        按群组查询消息（委托 Repository 查 MySQL）。

        Args:
            chat_id: Telegram 群组 ID
            limit: 每页数量
            offset: 偏移量

        Returns:
            MonitoredMessage 列表
        """
        return await monitor_repository.get_by_chat_id(chat_id, limit, offset)

    # ==================== 去重 ====================

    async def is_duplicate(self, chat_id: int, telegram_message_id: int) -> bool:
        """
        检查消息是否已处理（Redis 去重键）。

        Args:
            chat_id: Telegram 群组 ID
            telegram_message_id: Telegram 消息 ID

        Returns:
            bool: True 表示已处理（重复），False 表示未处理
        """
        try:
            redis = await get_redis()
            if redis:
                dedup_key = (
                    f"{self.REDIS_KEYS['MSG_DEDUP']}"
                    f"{chat_id}:{telegram_message_id}"
                )
                exists = await redis.exists(dedup_key)
                return bool(exists)
        except redis_lib.RedisError as e:
            logger.warning(
                "⚠️ Redis dedup check failed for chat={}, msg={}: {}",
                chat_id,
                telegram_message_id,
                e,
            )

        # Redis 不可用时，无法去重，返回 False（允许处理）
        return False


# 单例实例
monitor_service = MonitorService()
