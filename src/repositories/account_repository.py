# TGMonitor/src/repositories/account_repository.py
"""
监听账号数据库操作层
对应表: tgm_account
参照 bot/src/repositories/productRepository.ts 的模式。

职责：纯 SQL CRUD 操作，不涉及 Redis 和业务逻辑。
只能被 Service 层调用。

使用方式：
    from repositories.account_repository import account_repository

    accounts = await account_repository.get_all_active()
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import aiomysql

from config.database import get_pool
from models.account import MonitorAccount
from utils.logger import logger


class AccountRepository:
    """
    监听账号数据库操作层
    对应表: tgm_account

    所有方法使用参数化查询（%s 占位符），严禁字符串拼接 SQL。
    使用 async with 管理连接，确保连接归还连接池。
    """

    async def insert(self, account: MonitorAccount) -> int:
        """
        插入一条账号记录。

        Args:
            account: MonitorAccount 实体

        Returns:
            int: 数据库自增 ID

        Raises:
            aiomysql.Error: 数据库写入失败
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO tgm_account (
                        phone, api_id, api_hash, session_name,
                        display_name, is_active, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        account.phone,
                        account.api_id,
                        account.api_hash,
                        account.session_name,
                        account.display_name,
                        int(account.is_active),
                        account.status,
                    ),
                )
                logger.debug("💾 Inserted tgm_account: phone={}", account.phone)
                return cur.lastrowid

    async def get_by_id(self, account_id: int) -> Optional[MonitorAccount]:
        """
        按 ID 查询账号。

        Args:
            account_id: 数据库自增 ID

        Returns:
            MonitorAccount 实例，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tgm_account WHERE id = %s",
                    (account_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return MonitorAccount.from_db_row(row)

    async def get_by_phone(self, phone: str) -> Optional[MonitorAccount]:
        """
        按手机号查询账号。

        Args:
            phone: 手机号

        Returns:
            MonitorAccount 实例，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tgm_account WHERE phone = %s",
                    (phone,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return MonitorAccount.from_db_row(row)

    async def get_all_active(self) -> List[MonitorAccount]:
        """
        获取所有启用的账号。

        Returns:
            MonitorAccount 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_account
                    WHERE is_active = 1
                    ORDER BY id ASC
                    """
                )
                rows = await cur.fetchall()
                return [MonitorAccount.from_db_row(row) for row in rows]

    async def update_status(
        self,
        phone: str,
        status: str,
        last_error: Optional[str] = None,
    ) -> bool:
        """
        更新账号状态。

        Args:
            phone: 手机号
            status: 新状态 (online/offline/banned/flood_wait)
            last_error: 最近一次错误信息（可选）

        Returns:
            bool: 是否更新成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if status == "online":
                    await cur.execute(
                        """
                        UPDATE tgm_account
                        SET status = %s, last_connected_at = %s, last_error = %s
                        WHERE phone = %s
                        """,
                        (status, datetime.now(), last_error, phone),
                    )
                else:
                    await cur.execute(
                        """
                        UPDATE tgm_account
                        SET status = %s, last_error = %s
                        WHERE phone = %s
                        """,
                        (status, last_error, phone),
                    )
                logger.debug("💾 Updated tgm_account status: phone={}, status={}", phone, status)
                return cur.rowcount > 0

    async def update(self, account: MonitorAccount) -> bool:
        """
        完整更新账号信息（按 ID）。

        Args:
            account: MonitorAccount 实体（必须包含 id）

        Returns:
            bool: 是否更新成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE tgm_account
                    SET phone = %s, api_id = %s, api_hash = %s,
                        session_name = %s, display_name = %s,
                        is_active = %s, status = %s,
                        last_connected_at = %s, last_error = %s
                    WHERE id = %s
                    """,
                    (
                        account.phone,
                        account.api_id,
                        account.api_hash,
                        account.session_name,
                        account.display_name,
                        int(account.is_active),
                        account.status,
                        account.last_connected_at,
                        account.last_error,
                        account.id,
                    ),
                )
                return cur.rowcount > 0

    async def delete_by_id(self, account_id: int) -> bool:
        """
        按 ID 删除账号（物理删除）。

        Args:
            account_id: 数据库自增 ID

        Returns:
            bool: 是否删除成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM tgm_account WHERE id = %s",
                    (account_id,),
                )
                return cur.rowcount > 0


# 单例实例
account_repository = AccountRepository()
