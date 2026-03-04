# TGMonitor/src/config/database.py
"""
MySQL 异步连接池管理模块
参照 bot/src/config/database.ts 的连接池模式。

职责：
- 创建和管理 aiomysql 异步连接池
- 提供 get_pool() 获取连接池（懒初始化）
- 提供 close_pool() 优雅关闭

使用方式（在 Repository 层）：
    from config.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM tgm_message WHERE id = %s", (msg_id,))
            row = await cur.fetchone()
"""

from typing import Optional

import aiomysql

from config.settings import settings
from utils.logger import logger


# 全局连接池实例（懒初始化）
_pool: Optional[aiomysql.Pool] = None


async def get_pool() -> aiomysql.Pool:
    """
    获取 MySQL 异步连接池（懒初始化，单例模式）

    Returns:
        aiomysql.Pool: 连接池实例

    Raises:
        Exception: 连接失败时抛出
    """
    global _pool

    if _pool is not None and not _pool._closed:
        return _pool

    try:
        _pool = await aiomysql.create_pool(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            db=settings.DB_NAME,
            charset="utf8mb4",
            maxsize=10,
            minsize=2,
            autocommit=True,
            connect_timeout=10,
            echo=False,
        )
        logger.info(
            "✅ MySQL connection pool created (host={}, port={}, db={})",
            settings.DB_HOST,
            settings.DB_PORT,
            settings.DB_NAME,
        )
        return _pool

    except Exception as e:
        logger.error("❌ Failed to create MySQL connection pool: {}", e)
        raise


async def close_pool() -> None:
    """
    优雅关闭 MySQL 连接池
    """
    global _pool

    if _pool is not None and not _pool._closed:
        _pool.close()
        await _pool.wait_closed()
        logger.info("✅ MySQL connection pool closed gracefully")
        _pool = None
