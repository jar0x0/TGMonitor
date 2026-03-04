# TGMonitor/src/services/keyword_service.py
"""
关键词业务逻辑层
负责：
1. 从 MySQL 加载关键词到 Redis
2. 支持热加载（定时或按需重新加载）
3. 提供关键词查询接口给 KeywordFilter
参照 bot/src/services/productService.ts 的 Redis 缓存管理模式。

使用方式：
    from services.keyword_service import keyword_service

    await keyword_service.load_keywords()
    keywords = await keyword_service.get_all_active_keywords()
"""

from __future__ import annotations

import json
import time
from typing import List, Optional

import redis as redis_lib

from config.redis_client import get_redis
from config.settings import settings
from models.keyword import Keyword
from repositories.keyword_repository import keyword_repository
from utils.logger import logger


class KeywordService:
    """
    关键词业务逻辑层
    负责 Redis 缓存管理和调用 KeywordRepository。

    关键词在启动时全量加载到 Redis Hash，之后每 KEYWORD_RELOAD_INTERVAL 秒
    检查 MySQL 是否有更新，有变更时自动热加载。

    Redis Key 定义为类常量 REDIS_KEYS。
    MySQL 写失败 → raise；Redis 失败 → 降级告警。
    """

    REDIS_KEYS = {
        "KEYWORD_ALL": "monitor:keyword:all",         # HASH: field=keyword_id, value=keyword_json
        "KEYWORD_RELOAD": "monitor:keyword:reload",   # STRING: 上次加载的时间戳
    }

    def __init__(self) -> None:
        self._last_reload_time: float = 0.0
        self._last_db_updated_at: Optional[str] = None

    # ==================== 加载 ====================

    async def load_keywords(self) -> None:
        """
        从 MySQL 全量加载所有启用的关键词到 Redis Hash。

        启动时调用一次，之后由 reload_if_needed() 定时触发。

        Raises:
            aiomysql.Error: MySQL 查询失败时抛出
        """
        keywords = await keyword_repository.get_all_active()
        count = len(keywords)

        try:
            redis = await get_redis()
            if redis:
                # 先清空旧数据，再写入新数据
                await redis.delete(self.REDIS_KEYS["KEYWORD_ALL"])

                if keywords:
                    # 批量写入 Hash：field=id, value=keyword_json
                    mapping = {
                        str(kw.id): kw.model_dump_json()
                        for kw in keywords
                    }
                    await redis.hset(self.REDIS_KEYS["KEYWORD_ALL"], mapping=mapping)

                # 记录加载时间
                now = time.time()
                await redis.set(self.REDIS_KEYS["KEYWORD_RELOAD"], str(now))
                self._last_reload_time = now

                logger.info("🔄 Loaded {} active keywords to Redis", count)
            else:
                logger.info("🔄 Loaded {} active keywords (Redis disabled)", count)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis keyword load failed: {}", e)

        # 记录 MySQL 最新 updated_at
        self._last_db_updated_at = await keyword_repository.get_last_updated_at()
        self._last_reload_time = time.time()

    # ==================== 查询 ====================

    async def get_all_active_keywords(self) -> List[Keyword]:
        """
        获取所有启用的关键词（先查 Redis，未命中查 MySQL）。

        Returns:
            Keyword 列表
        """
        # 1. 先查 Redis
        try:
            redis = await get_redis()
            if redis:
                data = await redis.hgetall(self.REDIS_KEYS["KEYWORD_ALL"])
                if data:
                    keywords = [
                        Keyword.model_validate_json(v)
                        for v in data.values()
                    ]
                    logger.debug("🎯 Redis hit: {} keywords from cache", len(keywords))
                    return keywords
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis keyword read failed: {}", e)

        # 2. Redis 未命中，查 MySQL
        keywords = await keyword_repository.get_all_active()
        logger.debug("📥 Loaded {} keywords from MySQL (Redis miss)", len(keywords))

        # 3. 回写 Redis
        try:
            redis = await get_redis()
            if redis and keywords:
                mapping = {
                    str(kw.id): kw.model_dump_json()
                    for kw in keywords
                }
                await redis.delete(self.REDIS_KEYS["KEYWORD_ALL"])
                await redis.hset(self.REDIS_KEYS["KEYWORD_ALL"], mapping=mapping)
                logger.debug("📥 Backfilled {} keywords to Redis", len(keywords))
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis keyword backfill failed: {}", e)

        return keywords

    async def get_keywords_by_category(self, category: str) -> List[Keyword]:
        """
        按分类获取启用的关键词。

        先从 Redis Hash 全量获取后过滤，比为每个分类建单独缓存更简单。

        Args:
            category: 关键词分类 (brand/risk/product/payment/affiliate/competitor)

        Returns:
            Keyword 列表
        """
        all_keywords = await self.get_all_active_keywords()
        return [kw for kw in all_keywords if kw.category == category]

    # ==================== 热加载 ====================

    async def reload_if_needed(self) -> bool:
        """
        检查是否需要重新加载关键词（比对 MySQL updated_at 时间戳）。

        每 KEYWORD_RELOAD_INTERVAL 秒（默认 300）检查一次。
        如果 MySQL 有更新，重新全量加载到 Redis。

        Returns:
            bool: True 表示执行了重新加载，False 表示无需加载
        """
        now = time.time()
        elapsed = now - self._last_reload_time

        if elapsed < settings.KEYWORD_RELOAD_INTERVAL:
            return False

        # 检查 MySQL 最新 updated_at
        current_updated_at = await keyword_repository.get_last_updated_at()

        if current_updated_at == self._last_db_updated_at:
            # 无变更，仅更新检查时间
            self._last_reload_time = now
            logger.debug("✅ Keyword reload check: no changes detected")
            return False

        # 有变更，重新加载
        logger.info(
            "🔄 Keyword changes detected (old={}, new={}), reloading...",
            self._last_db_updated_at,
            current_updated_at,
        )
        await self.load_keywords()
        return True


# 单例实例
keyword_service = KeywordService()
