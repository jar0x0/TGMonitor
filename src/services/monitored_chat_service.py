# TGMonitor/src/services/monitored_chat_service.py
"""
被监听群组业务逻辑层
负责：
1. 加载活跃群组配置（支持 Redis 缓存）
2. 提供群组 ID 集合给 MessageHandler 做来源校验
3. 按账号获取分配的群组

使用方式：
    from services.monitored_chat_service import monitored_chat_service

    chat_ids = await monitored_chat_service.get_all_active_chat_ids()
    chats = await monitored_chat_service.get_chats_by_account("+86138...")
"""

from __future__ import annotations

from typing import List

import redis as redis_lib

from config.redis_client import get_redis
from config.settings import settings
from models.monitored_chat import MonitoredChat
from repositories.monitored_chat_repository import monitored_chat_repository
from utils.logger import logger


class MonitoredChatService:
    """
    被监听群组业务逻辑层
    负责 Redis 缓存管理和调用 MonitoredChatRepository。

    Redis Key 定义为类常量 REDIS_KEYS。
    """

    REDIS_KEYS = {
        "CHAT_ACTIVE_IDS": "monitor:chat:active_ids",  # SET: 所有启用群组的 chat_id
    }

    # ==================== .env 同步 ====================

    async def sync_from_env(self) -> int:
        """
        将 .env 中配置的监听群组同步到 MySQL（不存在则插入，已存在则跳过）。

        启动时由 main.py 调用。

        Returns:
            新增的群组数量
        """
        env_chats = settings.get_monitor_chats()
        if not env_chats:
            return 0

        # 获取第一个 .env 账号的手机号作为默认分配账号
        env_accounts = settings.get_accounts()
        default_phone = env_accounts[0]["phone"] if env_accounts else None

        added = 0
        for chat_dict in env_chats:
            chat_id = chat_dict["chat_id"]
            existing = await monitored_chat_repository.get_by_chat_id(chat_id)
            if existing:
                logger.debug(
                    "📋 Chat {} already in DB (id={}), skipping",
                    chat_id,
                    existing.id,
                )
                continue

            # 优先使用 .env 中指定的账号，未指定则用第一个账号
            phone = chat_dict.get("assigned_phone") or default_phone

            chat = MonitoredChat(
                chat_id=chat_id,
                chat_title=chat_dict["chat_title"],
                chat_type=chat_dict.get("chat_type", "supergroup"),
                assigned_account_phone=phone,
                is_active=True,
            )
            db_id = await monitored_chat_repository.insert(chat)
            logger.info(
                "💾 Synced chat from .env to DB: chat_id={}, title={}, id={}",
                chat_id,
                chat_dict["chat_title"],
                db_id,
            )
            added += 1

        if added:
            await self.invalidate_cache()

        return added

    async def get_all_active_chat_ids(self) -> List[int]:
        """
        获取所有启用群组的 Telegram chat_id 集合。

        先查 Redis，未命中查 MySQL 并回写。

        Returns:
            chat_id 列表
        """
        # 1. 先查 Redis
        try:
            redis = await get_redis()
            if redis:
                members = await redis.smembers(self.REDIS_KEYS["CHAT_ACTIVE_IDS"])
                if members:
                    chat_ids = [int(m) for m in members]
                    logger.debug("🎯 Redis hit: {} active chat IDs", len(chat_ids))
                    return chat_ids
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis read failed for active chat IDs: {}", e)

        # 2. Redis 未命中，查 MySQL
        chat_ids = await monitored_chat_repository.get_all_active_chat_ids()

        # 3. 回写 Redis
        try:
            redis = await get_redis()
            if redis and chat_ids:
                await redis.delete(self.REDIS_KEYS["CHAT_ACTIVE_IDS"])
                await redis.sadd(
                    self.REDIS_KEYS["CHAT_ACTIVE_IDS"],
                    *[str(cid) for cid in chat_ids],
                )
                logger.debug("📥 Backfilled {} active chat IDs to Redis", len(chat_ids))
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis backfill failed for active chat IDs: {}", e)

        return chat_ids

    async def get_all_active(self) -> List[MonitoredChat]:
        """
        获取所有启用的群组配置。

        Returns:
            MonitoredChat 列表
        """
        return await monitored_chat_repository.get_all_active()

    async def get_chats_by_account(self, phone: str) -> List[MonitoredChat]:
        """
        按分配的监听账号获取群组列表。

        Args:
            phone: 监听账号手机号

        Returns:
            MonitoredChat 列表
        """
        return await monitored_chat_repository.get_by_account_phone(phone)

    async def invalidate_cache(self) -> None:
        """清除群组缓存（增删群组后调用）。"""
        try:
            redis = await get_redis()
            if redis:
                await redis.delete(self.REDIS_KEYS["CHAT_ACTIVE_IDS"])
                logger.debug("🗑️ Invalidated active chat IDs cache")
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis invalidate failed for chat IDs: {}", e)


# 单例实例
monitored_chat_service = MonitoredChatService()
