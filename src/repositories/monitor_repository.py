# TGMonitor/src/repositories/monitor_repository.py
"""
监听消息数据库操作层
对应表: tgm_message
参照 bot/src/repositories/productRepository.ts 的模式。

职责：纯 SQL CRUD 操作，不涉及 Redis 和业务逻辑。
只能被 Service 层调用。

使用方式：
    from repositories.monitor_repository import monitor_repository

    msg_id = await monitor_repository.insert(message)
    msg = await monitor_repository.get_by_id(msg_id)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import aiomysql

from config.database import get_pool
from models.message import MonitoredMessage
from utils.logger import logger


class MonitorRepository:
    """
    监听消息数据库操作层
    对应表: tgm_message

    所有方法使用参数化查询（%s 占位符），严禁字符串拼接 SQL。
    使用 async with 管理连接，确保连接归还连接池。
    """

    async def insert(self, message: MonitoredMessage) -> int:
        """
        插入一条监听消息记录。

        Args:
            message: MonitoredMessage 实体

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
                    INSERT INTO tgm_message (
                        telegram_message_id, chat_id, chat_title,
                        sender_id, sender_username, sender_display_name,
                        message_text, message_type, reply_to_message_id,
                        matched_keywords, keyword_category,
                        monitor_account_phone, message_date
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s
                    )
                    """,
                    (
                        message.telegram_message_id,
                        message.chat_id,
                        message.chat_title,
                        message.sender_id,
                        message.sender_username,
                        message.sender_display_name,
                        message.message_text,
                        message.message_type,
                        message.reply_to_message_id,
                        message.keywords_to_json(),
                        message.keyword_category,
                        message.monitor_account_phone,
                        message.message_date,
                    ),
                )
                logger.debug(
                    "💾 Inserted tgm_message: telegram_msg_id={}, chat_id={}",
                    message.telegram_message_id,
                    message.chat_id,
                )
                return cur.lastrowid

    async def get_by_id(self, message_id: int) -> Optional[MonitoredMessage]:
        """
        按数据库主键 ID 查询消息。

        Args:
            message_id: 数据库自增 ID

        Returns:
            MonitoredMessage 实例，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tgm_message WHERE id = %s",
                    (message_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return MonitoredMessage.from_db_row(row)

    async def get_by_chat_id(
        self, chat_id: int, limit: int = 50, offset: int = 0
    ) -> List[MonitoredMessage]:
        """
        按群组 ID 分页查询消息，按消息时间倒序。

        Args:
            chat_id: Telegram 群组 ID
            limit: 每页数量
            offset: 偏移量

        Returns:
            MonitoredMessage 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_message
                    WHERE chat_id = %s
                    ORDER BY message_date DESC
                    LIMIT %s OFFSET %s
                    """,
                    (chat_id, limit, offset),
                )
                rows = await cur.fetchall()
                return [MonitoredMessage.from_db_row(row) for row in rows]

    async def get_by_date_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> List[MonitoredMessage]:
        """
        按时间范围查询消息，按消息时间倒序。

        Args:
            start: 开始时间（含）
            end: 结束时间（含）
            limit: 最大返回数量

        Returns:
            MonitoredMessage 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_message
                    WHERE message_date BETWEEN %s AND %s
                    ORDER BY message_date DESC
                    LIMIT %s
                    """,
                    (start, end, limit),
                )
                rows = await cur.fetchall()
                return [MonitoredMessage.from_db_row(row) for row in rows]

    async def get_by_keyword_category(
        self, category: str, limit: int = 50, offset: int = 0
    ) -> List[MonitoredMessage]:
        """
        按关键词分类查询消息，按消息时间倒序。

        Args:
            category: 关键词分类 (brand/risk/product/payment/affiliate/competitor)
            limit: 每页数量
            offset: 偏移量

        Returns:
            MonitoredMessage 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_message
                    WHERE keyword_category = %s
                    ORDER BY message_date DESC
                    LIMIT %s OFFSET %s
                    """,
                    (category, limit, offset),
                )
                rows = await cur.fetchall()
                return [MonitoredMessage.from_db_row(row) for row in rows]

    async def count_by_chat_id(self, chat_id: int) -> int:
        """
        统计某群组的消息数量。

        Args:
            chat_id: Telegram 群组 ID

        Returns:
            int: 消息条数
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM tgm_message WHERE chat_id = %s",
                    (chat_id,),
                )
                (count,) = await cur.fetchone()
                return count

    async def delete_by_id(self, message_id: int) -> bool:
        """
        按 ID 删除消息记录（物理删除）。

        Args:
            message_id: 数据库自增 ID

        Returns:
            bool: 是否删除成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM tgm_message WHERE id = %s",
                    (message_id,),
                )
                return cur.rowcount > 0


# 单例实例
monitor_repository = MonitorRepository()
