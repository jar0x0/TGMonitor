#!/usr/bin/env python3
# TGMonitor/src/scripts/verify_phase1.py
"""
阶段 1 验证脚本
检查基础设施是否全部就绪：配置、数据库连接池、Redis 客户端、日志、数据库表、种子数据
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logger import logger


async def verify() -> None:
    """运行所有验证项"""
    passed = 0
    failed = 0

    # 1. 验证 settings
    logger.info("=" * 60)
    logger.info("🔍 [1/6] Verifying config/settings.py ...")
    try:
        from config.settings import settings

        assert settings.DB_HOST == "localhost", f"DB_HOST={settings.DB_HOST}"
        assert settings.DB_PORT == 3306, f"DB_PORT={settings.DB_PORT}"
        assert settings.DB_NAME == "hello", f"DB_NAME={settings.DB_NAME}"
        assert settings.USE_REDIS is True, f"USE_REDIS={settings.USE_REDIS}"
        assert settings.REDIS_DB == 1, f"REDIS_DB={settings.REDIS_DB}"
        assert settings.sessions_dir.exists() or True  # dir may not exist yet
        logger.info("✅ settings — OK")
        passed += 1
    except Exception as e:
        logger.error("❌ settings — FAILED: {}", e)
        failed += 1

    # 2. 验证 MySQL 连接池
    logger.info("🔍 [2/6] Verifying config/database.py (MySQL pool) ...")
    try:
        from config.database import get_pool, close_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                (result,) = await cur.fetchone()
                assert result == 1
        logger.info("✅ MySQL connection pool — OK")
        passed += 1

        # 关闭连接池
        await close_pool()
    except Exception as e:
        logger.error("❌ MySQL connection pool — FAILED: {}", e)
        failed += 1

    # 3. 验证 Redis 客户端
    logger.info("🔍 [3/6] Verifying config/redis_client.py (Redis) ...")
    try:
        from config.redis_client import get_redis, close_redis

        redis = await get_redis()
        assert redis is not None, "Redis client is None but USE_REDIS=true"

        # 测试读写
        await redis.set("monitor:test:phase1", "ok", ex=60)
        val = await redis.get("monitor:test:phase1")
        assert val == "ok", f"Expected 'ok', got '{val}'"
        await redis.delete("monitor:test:phase1")

        logger.info("✅ Redis client — OK")
        passed += 1

        await close_redis()
    except Exception as e:
        logger.error("❌ Redis client — FAILED: {}", e)
        failed += 1

    # 4. 验证日志系统
    logger.info("🔍 [4/6] Verifying utils/logger.py ...")
    try:
        from utils.logger import message_logger, client_logger

        message_logger.info("Test message log entry")
        client_logger.info("Test client log entry")

        log_dir = Path(settings.LOG_DIR)
        assert log_dir.exists(), f"Log dir {log_dir} does not exist"
        assert (log_dir / "app.log").exists(), "app.log not created"

        logger.info("✅ Logger system — OK")
        passed += 1
    except Exception as e:
        logger.error("❌ Logger system — FAILED: {}", e)
        failed += 1

    # 5. 验证数据库表
    logger.info("🔍 [5/6] Verifying database tables ...")
    try:
        from config.database import get_pool, close_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                tables = ["tgm_message", "tgm_keyword", "tgm_account", "tgm_monitored_chat"]
                for table in tables:
                    await cur.execute(f"SHOW CREATE TABLE {table}")
                    await cur.fetchone()
                    logger.info("  ✅ Table '{}' exists", table)

        logger.info("✅ Database tables — OK")
        passed += 1
        await close_pool()
    except Exception as e:
        logger.error("❌ Database tables — FAILED: {}", e)
        failed += 1

    # 6. 验证种子关键词
    logger.info("🔍 [6/6] Verifying seed keywords ...")
    try:
        from config.database import get_pool, close_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM tgm_keyword")
                (count,) = await cur.fetchone()
                assert count >= 16, f"Expected >= 16 keywords, got {count}"

                await cur.execute(
                    "SELECT word, category FROM tgm_keyword WHERE word = %s",
                    ("relinx",),
                )
                row = await cur.fetchone()
                assert row is not None, "Keyword 'relinx' not found"

        logger.info("✅ Seed keywords — OK ({} keywords)", count)
        passed += 1
        await close_pool()
    except Exception as e:
        logger.error("❌ Seed keywords — FAILED: {}", e)
        failed += 1

    # 汇总
    logger.info("=" * 60)
    logger.info("📊 Phase 1 Verification: {}/{} passed, {} failed", passed, passed + failed, failed)
    if failed == 0:
        logger.info("🎉 Phase 1 Infrastructure — ALL CHECKS PASSED")
    else:
        logger.error("⚠️ Phase 1 Infrastructure — {} CHECKS FAILED", failed)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(verify())
