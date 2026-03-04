# TGMonitor/src/repositories/keyword_repository.py
"""
关键词数据库操作层
对应表: tgm_keyword
参照 bot/src/repositories/productRepository.ts 的模式。

职责：纯 SQL CRUD 操作，不涉及 Redis 和业务逻辑。
只能被 Service 层调用。

使用方式：
    from repositories.keyword_repository import keyword_repository

    keywords = await keyword_repository.get_all_active()
"""

from __future__ import annotations

from typing import List, Optional

import aiomysql

from config.database import get_pool
from models.keyword import Keyword
from utils.logger import logger


class KeywordRepository:
    """
    关键词数据库操作层
    对应表: tgm_keyword

    所有方法使用参数化查询（%s 占位符），严禁字符串拼接 SQL。
    使用 async with 管理连接，确保连接归还连接池。
    """

    async def insert(self, keyword: Keyword) -> int:
        """
        插入一条关键词记录。

        Args:
            keyword: Keyword 实体

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
                    INSERT INTO tgm_keyword (
                        word, category, match_type, priority, is_active
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        keyword.word,
                        keyword.category,
                        keyword.match_type,
                        keyword.priority,
                        int(keyword.is_active),
                    ),
                )
                logger.debug("💾 Inserted tgm_keyword: word={}, category={}", keyword.word, keyword.category)
                return cur.lastrowid

    async def get_by_id(self, keyword_id: int) -> Optional[Keyword]:
        """
        按 ID 查询关键词。

        Args:
            keyword_id: 数据库自增 ID

        Returns:
            Keyword 实例，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tgm_keyword WHERE id = %s",
                    (keyword_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return Keyword.from_db_row(row)

    async def get_all_active(self) -> List[Keyword]:
        """
        获取所有启用的关键词，按优先级降序排列。

        Returns:
            Keyword 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_keyword
                    WHERE is_active = 1
                    ORDER BY priority DESC, id ASC
                    """
                )
                rows = await cur.fetchall()
                return [Keyword.from_db_row(row) for row in rows]

    async def get_by_category(self, category: str) -> List[Keyword]:
        """
        按分类查询启用的关键词。

        Args:
            category: 分类名 (brand/risk/product/payment/affiliate/competitor)

        Returns:
            Keyword 列表
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """
                    SELECT * FROM tgm_keyword
                    WHERE category = %s AND is_active = 1
                    ORDER BY priority DESC
                    """,
                    (category,),
                )
                rows = await cur.fetchall()
                return [Keyword.from_db_row(row) for row in rows]

    async def update(self, keyword: Keyword) -> bool:
        """
        更新关键词（按 ID）。

        Args:
            keyword: Keyword 实体（必须包含 id）

        Returns:
            bool: 是否更新成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE tgm_keyword
                    SET word = %s, category = %s, match_type = %s,
                        priority = %s, is_active = %s
                    WHERE id = %s
                    """,
                    (
                        keyword.word,
                        keyword.category,
                        keyword.match_type,
                        keyword.priority,
                        int(keyword.is_active),
                        keyword.id,
                    ),
                )
                logger.debug("💾 Updated tgm_keyword id={}: word={}", keyword.id, keyword.word)
                return cur.rowcount > 0

    async def delete_by_id(self, keyword_id: int) -> bool:
        """
        按 ID 删除关键词（物理删除）。

        Args:
            keyword_id: 数据库自增 ID

        Returns:
            bool: 是否删除成功
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM tgm_keyword WHERE id = %s",
                    (keyword_id,),
                )
                return cur.rowcount > 0

    async def count_all(self) -> int:
        """
        统计关键词总数。

        Returns:
            int: 关键词条数
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM tgm_keyword")
                (count,) = await cur.fetchone()
                return count

    async def get_last_updated_at(self) -> Optional[str]:
        """
        获取关键词表的最新 updated_at 时间戳（用于热加载检测变更）。

        Returns:
            最新 updated_at 的字符串表示，或 None
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT MAX(updated_at) FROM tgm_keyword"
                )
                (max_updated,) = await cur.fetchone()
                if max_updated is None:
                    return None
                return str(max_updated)


# 单例实例
keyword_repository = KeywordRepository()
