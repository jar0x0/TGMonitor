# TGMonitor/src/repositories/monitored_chat_repository.py
"""
被监听群组数据库操作层
对应表: tgm_monitored_chat
参照 bot/src/repositories/productRepository.ts 的模式。

职责：纯 SQL CRUD 操作，不涉及 Redis 和业务逻辑。
只能被 Service 层调用。

使用方式：
    from repositories.monitored_chat_repository import monitored_chat_repository

    chats = await monitored_chat_repository.get_all_active()
"""

from __future__ import annotations

from typing import List, Optional

import aiomysql

from config.database import get_pool
from models.monitored_chat import MonitoredChat
from utils.logger import logger


class MonitoredChatRepository:
    """
    被监听群组数据库操作层
    对应表: tgm_monitored_chat

    所有方法使用参数化查询（%s 占位符），严禁字符串拼接 SQL。
    使用 async with 管理连接，确保连接归还连接池。
    """

    async def insert(self, chat: MonitoredChat) -> int:
        """
        插入一条群组记录。

        Args:
            chat: MonitoredChat 实体

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
                    INSERT INTO tgm_monitored_chat (
                        chat_id, chat_title, chat_username, chat_type,
                        assigned_account_phone, is_active, joined_at, note
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        chat.chat_id,
                        chat.chat_title,
                        chat.chat_username,
                        chat.chat_type,
                        chat.assigned_account_phone,
                        int(chat.is_active),
                        chat.joined_at,
                        chat.note,
                    ),
                )
                logger.debug(
                    "💾 Inserted tgm_monitored_chat: chat_id={}, title={}",
                    chat.chat_id,
                    chat.chat_title,
                )
                return cur.lastrowid

    async def get_by_id(self, chat_db_id: int) -> Optional[MonitoredChat]:
        """
        按数据库主键 ID 查询群组。

        Args:
            chat_db_id: 数据库自增 ID

        Returns:
            MonitoredChat 实例，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tgm_monitored_chat WHERE id = %s",
                    (chat_db_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return MonitoredChat.from_db_row(row)

    async def get_by_chat_id(self, chat_id: int) -> Optional[MonitoredChat]:
        """
        按 Telegram 群组 ID 查询。

        Args:
            chat_id: Telegram 群组 ID

        Returns:
            MonitoredChat 实例，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tgm_monitored_chat WHERE chat_id = %s",
                    (chat_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return MonitoredChat.from_db_row(row)

    async def get_all_active(self) -> List[MonitoredChat]:
        """
        获取所有启用的群组配置。

        Returns:
            MonitoredChat 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_monitored_chat
                    WHERE is_active = 1
                    ORDER BY id ASC
                    """
                )
                rows = await cur.fetchall()
                return [MonitoredChat.from_db_row(row) for row in rows]

    async def get_by_account_phone(self, phone: str) -> List[MonitoredChat]:
        """
        按分配的监听账号手机号查询群组。

        Args:
            phone: 监听账号手机号

        Returns:
            MonitoredChat 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_monitored_chat
                    WHERE assigned_account_phone = %s AND is_active = 1
                    ORDER BY id ASC
                    """,
                    (phone,),
                )
                rows = await cur.fetchall()
                return [MonitoredChat.from_db_row(row) for row in rows]

    async def get_all_active_chat_ids(self) -> List[int]:
        """
        获取所有启用群组的 Telegram chat_id 集合（用于消息来源校验）。

        Returns:
            chat_id 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT chat_id FROM tgm_monitored_chat WHERE is_active = 1"
                )
                rows = await cur.fetchall()
                return [row[0] for row in rows]

    async def update(self, chat: MonitoredChat) -> bool:
        """
        完整更新群组信息（按 ID）。

        Args:
            chat: MonitoredChat 实体（必须包含 id）

        Returns:
            bool: 是否更新成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE tgm_monitored_chat
                    SET chat_id = %s, chat_title = %s, chat_username = %s,
                        chat_type = %s, assigned_account_phone = %s,
                        is_active = %s, joined_at = %s, note = %s
                    WHERE id = %s
                    """,
                    (
                        chat.chat_id,
                        chat.chat_title,
                        chat.chat_username,
                        chat.chat_type,
                        chat.assigned_account_phone,
                        int(chat.is_active),
                        chat.joined_at,
                        chat.note,
                        chat.id,
                    ),
                )
                return cur.rowcount > 0

    async def delete_by_id(self, chat_db_id: int) -> bool:
        """
        按 ID 删除群组记录（物理删除）。

        Args:
            chat_db_id: 数据库自增 ID

        Returns:
            bool: 是否删除成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM tgm_monitored_chat WHERE id = %s",
                    (chat_db_id,),
                )
                return cur.rowcount > 0


# 单例实例
monitored_chat_repository = MonitoredChatRepository()
