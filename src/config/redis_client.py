# TGMonitor/src/config/redis_client.py
"""
Redis 异步客户端管理模块
参照 bot/src/config/redisClient.ts 的 RedisClientManager 单例模式。

职责：
- 创建和管理 Redis 异步客户端（单例模式）
- 支持 USE_REDIS=false 时降级为纯 MySQL 模式
- 提供 get_redis() 获取客户端
- 提供 close_redis() 优雅关闭

所有 Key 统一使用 `monitor:` 前缀，与 bot 项目的 Key 空间隔离。

使用方式（在 Service 层）：
    from config.redis_client import get_redis

    redis = await get_redis()
    if redis:
        await redis.set("monitor:msg:id:123", data)
"""

from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from config.settings import settings
from utils.logger import logger


# 全局 Redis 客户端实例（懒初始化）
_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    """
    获取 Redis 异步客户端（懒初始化，单例模式）

    当 USE_REDIS=false 时返回 None，上层 Service 需判空后降级为纯 MySQL 模式。

    Returns:
        aioredis.Redis | None: Redis 客户端实例，或 None（Redis 未启用）

    Raises:
        Exception: 连接失败时抛出
    """
    global _redis_client

    if not settings.USE_REDIS:
        return None

    if _redis_client is not None:
        try:
            await _redis_client.ping()
            return _redis_client
        except Exception:
            logger.warning("⚠️ Redis ping failed, reconnecting...")
            _redis_client = None

    try:
        _redis_client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

        # 验证连接
        await _redis_client.ping()

        logger.info(
            "✅ Redis client connected (host={}, port={}, db={})",
            settings.redis_host,
            settings.redis_port,
            settings.REDIS_DB,
        )
        return _redis_client

    except Exception as e:
        logger.error("❌ Failed to connect Redis: {}", e)
        _redis_client = None
        raise


async def close_redis() -> None:
    """
    优雅关闭 Redis 客户端
    """
    global _redis_client

    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("✅ Redis client closed gracefully")
        except Exception as e:
            logger.warning("⚠️ Redis close error: {}", e)
        finally:
            _redis_client = None
