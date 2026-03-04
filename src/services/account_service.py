# TGMonitor/src/services/account_service.py
"""
监听账号业务逻辑层
负责：
1. 加载活跃账号（支持 Redis 缓存）
2. 账号状态管理（online / offline / banned / flood_wait）
3. 账号信息更新
参照 bot/src/services/productService.ts 的 Redis 缓存管理模式。

使用方式：
    from services.account_service import account_service

    accounts = await account_service.get_all_active_accounts()
    await account_service.update_status("+86123", "online")
"""

from __future__ import annotations

from typing import List, Optional

import aiomysql
import redis as redis_lib

from config.redis_client import get_redis
from config.settings import settings
from models.account import MonitorAccount
from repositories.account_repository import account_repository
from utils.logger import logger


class AccountService:
    """
    监听账号业务逻辑层
    负责 Redis 缓存管理和调用 AccountRepository。

    Redis Key 定义为类常量 REDIS_KEYS。
    MySQL 写失败 → raise；Redis 失败 → 降级告警。
    """

    REDIS_KEYS = {
        "ACCOUNT_BY_ID": "monitor:account:id:",       # STRING: 单个账号 JSON
        "ACCOUNT_BY_PHONE": "monitor:account:phone:",  # STRING: 按手机号索引 → JSON
        "ACCOUNT_ACTIVE": "monitor:account:active",    # SET: 所有启用账号的 ID 集合
    }

    # ==================== .env 同步 ====================

    async def sync_from_env(self) -> int:
        """
        将 .env 中配置的账号同步到 MySQL（不存在则插入，已存在则跳过）。

        启动时由 main.py 调用，确保 .env 配置落库。

        Returns:
            新增的账号数量
        """
        env_accounts = settings.get_accounts()
        if not env_accounts:
            return 0

        added = 0
        for acc_dict in env_accounts:
            existing = await account_repository.get_by_phone(acc_dict["phone"])
            if existing:
                logger.debug(
                    "📋 Account {} already in DB (id={}), skipping",
                    acc_dict["phone"],
                    existing.id,
                )
                continue

            account = MonitorAccount(
                phone=acc_dict["phone"],
                api_id=acc_dict["api_id"],
                api_hash=acc_dict["api_hash"],
                session_name=acc_dict["session_name"],
                display_name=acc_dict.get("display_name"),
                is_active=True,
                status="offline",
            )
            acc_id = await account_repository.insert(account)
            logger.info(
                "💾 Synced account from .env to DB: phone={}, id={}",
                acc_dict["phone"],
                acc_id,
            )
            added += 1

        if added:
            # 清 Redis 缓存，强制下次从 MySQL 重读
            try:
                redis = await get_redis()
                if redis:
                    await redis.delete(self.REDIS_KEYS["ACCOUNT_ACTIVE"])
            except redis_lib.RedisError:
                pass

        return added

    # ==================== 加载 ====================

    async def load_accounts(self) -> List[MonitorAccount]:
        """
        从 MySQL 加载所有启用的账号，缓存到 Redis。

        Returns:
            MonitorAccount 列表

        Raises:
            aiomysql.Error: MySQL 查询失败时抛出
        """
        accounts = await account_repository.get_all_active()

        try:
            redis = await get_redis()
            if redis:
                # 清空旧的活跃账号索引
                await redis.delete(self.REDIS_KEYS["ACCOUNT_ACTIVE"])

                for acc in accounts:
                    # 主数据
                    await redis.set(
                        f"{self.REDIS_KEYS['ACCOUNT_BY_ID']}{acc.id}",
                        acc.model_dump_json(),
                    )
                    # 手机号索引
                    await redis.set(
                        f"{self.REDIS_KEYS['ACCOUNT_BY_PHONE']}{acc.phone}",
                        acc.model_dump_json(),
                    )
                    # 活跃集合
                    await redis.sadd(self.REDIS_KEYS["ACCOUNT_ACTIVE"], str(acc.id))

                logger.info("🔄 Loaded {} active accounts to Redis", len(accounts))
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis account load failed: {}", e)

        return accounts

    # ==================== 查询 ====================

    async def get_all_active_accounts(self) -> List[MonitorAccount]:
        """
        获取所有启用的账号（先查 Redis，未命中查 MySQL）。

        Returns:
            MonitorAccount 列表
        """
        # 1. 先查 Redis
        try:
            redis = await get_redis()
            if redis:
                member_ids = await redis.smembers(self.REDIS_KEYS["ACCOUNT_ACTIVE"])
                if member_ids:
                    accounts = []
                    for aid in member_ids:
                        data = await redis.get(f"{self.REDIS_KEYS['ACCOUNT_BY_ID']}{aid}")
                        if data:
                            accounts.append(MonitorAccount.model_validate_json(data))
                    if accounts:
                        logger.debug("🎯 Redis hit: {} active accounts", len(accounts))
                        return accounts
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis account read failed: {}", e)

        # 2. Redis 未命中，查 MySQL 并回写
        return await self.load_accounts()

    async def get_account_by_phone(self, phone: str) -> Optional[MonitorAccount]:
        """
        按手机号获取账号（先查 Redis，未命中查 MySQL 并回写）。

        Args:
            phone: 手机号

        Returns:
            MonitorAccount 实例，或 None
        """
        # 1. 先查 Redis
        try:
            redis = await get_redis()
            if redis:
                cached = await redis.get(f"{self.REDIS_KEYS['ACCOUNT_BY_PHONE']}{phone}")
                if cached:
                    logger.debug("🎯 Redis hit for account phone={}", phone)
                    return MonitorAccount.model_validate_json(cached)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis account read failed for phone={}: {}", phone, e)

        # 2. Redis 未命中，查 MySQL
        account = await account_repository.get_by_phone(phone)
        if account is None:
            return None

        # 3. 回写 Redis
        try:
            redis = await get_redis()
            if redis:
                await redis.set(
                    f"{self.REDIS_KEYS['ACCOUNT_BY_PHONE']}{account.phone}",
                    account.model_dump_json(),
                )
                await redis.set(
                    f"{self.REDIS_KEYS['ACCOUNT_BY_ID']}{account.id}",
                    account.model_dump_json(),
                )
                logger.debug("📥 Backfilled account phone={} to Redis", phone)
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis account backfill failed for phone={}: {}", phone, e)

        return account

    # ==================== 状态管理 ====================

    async def update_status(
        self,
        phone: str,
        status: str,
        last_error: Optional[str] = None,
    ) -> bool:
        """
        更新账号状态（双写 MySQL + Redis）。

        Args:
            phone: 手机号
            status: 新状态 (online / offline / banned / flood_wait)
            last_error: 最近一次错误信息（可选）

        Returns:
            bool: 是否更新成功

        Raises:
            aiomysql.Error: MySQL 更新失败时抛出
        """
        try:
            success = await account_repository.update_status(phone, status, last_error)
        except aiomysql.Error as e:
            logger.error("❌ MySQL update_status failed for phone={}: {}", phone, e)
            raise

        if not success:
            return False

        # 更新 Redis 缓存
        try:
            redis = await get_redis()
            if redis:
                # 重新查 MySQL 获取最新完整数据后刷新缓存
                account = await account_repository.get_by_phone(phone)
                if account:
                    await redis.set(
                        f"{self.REDIS_KEYS['ACCOUNT_BY_PHONE']}{account.phone}",
                        account.model_dump_json(),
                    )
                    await redis.set(
                        f"{self.REDIS_KEYS['ACCOUNT_BY_ID']}{account.id}",
                        account.model_dump_json(),
                    )
        except redis_lib.RedisError as e:
            logger.warning("⚠️ Redis status update failed for phone={}: {}", phone, e)

        logger.info("📋 Account status updated: phone={}, status={}", phone, status)
        return True


# 单例实例
account_service = AccountService()
