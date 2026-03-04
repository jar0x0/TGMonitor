# TGMonitor/src/services/entity_cache_service.py
"""
Telegram 实体缓存服务
负责：
1. 缓存 Telegram 用户信息（避免频繁调用 Telegram API get_entity）
2. 缓存 Telegram 群组信息
3. 所有缓存使用 TTL（默认 ENTITY_CACHE_TTL = 86400 秒 = 24 小时）

使用方式：
    from services.entity_cache_service import entity_cache_service

    user = await entity_cache_service.get_user(sender_id)
    if not user:
        user = await client.get_entity(sender_id)
        await entity_cache_service.cache_user(sender_id, user_dict)
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import redis as redis_lib

from config.redis_client import get_redis
from config.settings import settings
from utils.logger import logger


class EntityCacheService:
    """
    Telegram 实体缓存服务
    缓存用户/群组信息到 Redis，减少 Telegram API 调用。

    Redis Key 定义为类常量 REDIS_KEYS。
    Redis 失败 → 降级告警，返回 None（调用方需自行调 Telegram API）。
    """

    REDIS_KEYS = {
        "ENTITY_USER": "monitor:entity:user:",  # STRING: 用户信息 JSON, TTL 24h
        "ENTITY_CHAT": "monitor:entity:chat:",  # STRING: 群组信息 JSON, TTL 24h
    }

    # ==================== 用户缓存 ====================

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        从 Redis 获取用户信息缓存。

        Args:
            user_id: Telegram 用户 ID

        Returns:
            用户信息字典，或 None（缓存未命中或 Redis 不可用）
        """
        try:
            redis = await get_redis()
            if redis:
                cached = await redis.get(f"{self.REDIS_KEYS['ENTITY_USER']}{user_id}")
                if cached:
                    logger.debug("🎯 Entity cache hit: user_id={}", user_id)
                    return json.loads(cached)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis entity cache read failed for user_id={}: {}", user_id, e)

        return None

    async def cache_user(self, user_id: int, user_data: Dict[str, Any]) -> None:
        """
        将用户信息写入 Redis 缓存（带 TTL）。

        Args:
            user_id: Telegram 用户 ID
            user_data: 用户信息字典（包含 username、first_name、last_name 等）
        """
        try:
            redis = await get_redis()
            if redis:
                key = f"{self.REDIS_KEYS['ENTITY_USER']}{user_id}"
                await redis.setex(key, settings.ENTITY_CACHE_TTL, json.dumps(user_data, ensure_ascii=False))
                logger.debug("📦 Cached entity: user_id={}", user_id)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis entity cache write failed for user_id={}: {}", user_id, e)

    async def invalidate_user(self, user_id: int) -> None:
        """
        删除用户缓存（当检测到信息过期或变更时调用）。

        Args:
            user_id: Telegram 用户 ID
        """
        try:
            redis = await get_redis()
            if redis:
                await redis.delete(f"{self.REDIS_KEYS['ENTITY_USER']}{user_id}")
                logger.debug("🗑️ Invalidated entity cache: user_id={}", user_id)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis entity cache delete failed for user_id={}: {}", user_id, e)

    # ==================== 群组缓存 ====================

    async def get_chat(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """
        从 Redis 获取群组信息缓存。

        Args:
            chat_id: Telegram 群组 ID

        Returns:
            群组信息字典，或 None（缓存未命中或 Redis 不可用）
        """
        try:
            redis = await get_redis()
            if redis:
                cached = await redis.get(f"{self.REDIS_KEYS['ENTITY_CHAT']}{chat_id}")
                if cached:
                    logger.debug("🎯 Entity cache hit: chat_id={}", chat_id)
                    return json.loads(cached)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis entity cache read failed for chat_id={}: {}", chat_id, e)

        return None

    async def cache_chat(self, chat_id: int, chat_data: Dict[str, Any]) -> None:
        """
        将群组信息写入 Redis 缓存（带 TTL）。

        Args:
            chat_id: Telegram 群组 ID
            chat_data: 群组信息字典（包含 title、username 等）
        """
        try:
            redis = await get_redis()
            if redis:
                key = f"{self.REDIS_KEYS['ENTITY_CHAT']}{chat_id}"
                await redis.setex(key, settings.ENTITY_CACHE_TTL, json.dumps(chat_data, ensure_ascii=False))
                logger.debug("📦 Cached entity: chat_id={}", chat_id)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis entity cache write failed for chat_id={}: {}", chat_id, e)

    async def invalidate_chat(self, chat_id: int) -> None:
        """
        删除群组缓存。

        Args:
            chat_id: Telegram 群组 ID
        """
        try:
            redis = await get_redis()
            if redis:
                await redis.delete(f"{self.REDIS_KEYS['ENTITY_CHAT']}{chat_id}")
                logger.debug("🗑️ Invalidated entity cache: chat_id={}", chat_id)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis entity cache delete failed for chat_id={}: {}", chat_id, e)


# 单例实例
entity_cache_service = EntityCacheService()
