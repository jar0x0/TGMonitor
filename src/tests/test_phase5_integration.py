#!/usr/bin/env python3
# TGMonitor/src/tests/test_phase5_integration.py
"""
阶段 5 集成测试
测试完整的消息处理管线：.env → DB 同步 → 关键词加载 → 消息匹配 → 去重 → 持久化

测试项：
1. .env 配置同步 — 账号 & 群组写入 DB
2. 连接验证 — session 文件存在且可连接
3. 完整消息管线 — 模拟消息经过所有步骤写入 DB + Redis
4. 去重验证 — 同一消息不会重复写入
5. Redis ↔ MySQL 一致性 — 缓存与持久化数据一致
6. 压力测试 — 批量消息写入性能
7. 关键词热加载 — 验证 reload 机制
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logger import logger


# ==================== Test 1: .env 配置同步 ====================

async def test_env_sync() -> bool:
    """测试 .env 账号和群组配置同步到 MySQL"""
    logger.info("🔍 Test 1: .env → DB sync ...")

    from config.settings import settings
    from services.account_service import account_service
    from services.monitored_chat_service import monitored_chat_service

    # 检查 .env 有配置
    env_accounts = settings.get_accounts()
    assert len(env_accounts) > 0, "No accounts in .env"
    logger.info("  ✅ .env has {} account(s)", len(env_accounts))

    # 同步账号
    await account_service.sync_from_env()

    # 验证 DB 有数据
    accounts = await account_service.get_all_active_accounts()
    assert len(accounts) > 0, "No active accounts in DB after sync"
    logger.info("  ✅ DB has {} active account(s)", len(accounts))

    # 同步群组
    await monitored_chat_service.sync_from_env()

    # 验证群组
    env_chats = settings.get_monitor_chats()
    if env_chats:
        chat_ids = await monitored_chat_service.get_all_active_chat_ids()
        assert len(chat_ids) > 0, "No active chat IDs after sync"
        logger.info("  ✅ DB has {} active chat(s)", len(chat_ids))
    else:
        logger.info("  ⚠️ No chats in .env (skipped)")

    return True


# ==================== Test 2: 连接验证 ====================

async def test_connection_verify() -> bool:
    """测试 session 文件存在且 Telethon 可连接"""
    logger.info("🔍 Test 2: Connection verify ...")

    from config.settings import settings
    from telethon import TelegramClient

    env_accounts = settings.get_accounts()
    assert len(env_accounts) > 0

    acc = env_accounts[0]
    session_path = str(settings.sessions_dir / acc["session_name"])

    # 检查 session 文件
    session_file = Path(f"{session_path}.session")
    assert session_file.exists(), f"Session file not found: {session_file}"
    logger.info("  ✅ Session file exists: {}", session_file.name)

    # 连接测试
    client = TelegramClient(session_path, acc["api_id"], acc["api_hash"])
    await client.connect()
    authorized = await client.is_user_authorized()
    assert authorized, "Account not authorized"

    me = await client.get_me()
    logger.info("  ✅ Connected as: {} (@{})", me.first_name, me.username or "N/A")

    await client.disconnect()
    logger.info("  ✅ Disconnected cleanly")

    return True


# ==================== Test 3: 完整消息管线 ====================

async def test_message_pipeline() -> bool:
    """测试模拟消息经过完整处理管线写入 DB + Redis"""
    logger.info("🔍 Test 3: Full message pipeline ...")

    from config.redis_client import get_redis
    from filters.keyword_filter import keyword_filter
    from models.message import MonitoredMessage
    from services.keyword_service import keyword_service
    from services.monitor_service import monitor_service

    # 确保关键词已加载
    await keyword_service.load_keywords()

    # 模拟消息文本
    test_text = "I just bought a steam gift card from relinx, it was awesome!"

    # Step 1: 关键词匹配
    result = await keyword_filter.match(test_text)
    assert result is not None, "Keywords should match"
    assert len(result.matched_keywords) > 0
    logger.info(
        "  ✅ Keyword match: {} keywords, category='{}'",
        len(result.matched_keywords),
        result.category,
    )

    # Step 2: 构建消息实体
    test_msg = MonitoredMessage(
        telegram_message_id=999001,
        chat_id=-5026789353,
        chat_title="Testing",
        sender_id=12345678,
        sender_username="test_user",
        sender_display_name="Test User",
        message_text=test_text,
        message_type="text",
        matched_keywords=result.matched_keywords,
        keyword_category=result.category,
        monitor_account_phone="+13239025485",
        message_date=datetime.now(),
    )

    # Step 3: 去重检查（应该是新消息）
    is_dup = await monitor_service.is_duplicate(test_msg.chat_id, test_msg.telegram_message_id)
    assert not is_dup, "New message should not be duplicate"
    logger.info("  ✅ Dedup check: not duplicate")

    # Step 4: 持久化
    saved = await monitor_service.save_message(test_msg)
    assert saved.id is not None, "Message should have DB id after save"
    logger.info("  ✅ Saved to MySQL: id={}", saved.id)

    # Step 5: 验证 Redis 缓存
    redis = await get_redis()
    if redis:
        cached = await redis.get(f"monitor:msg:id:{saved.id}")
        assert cached is not None, "Message should be in Redis cache"
        logger.info("  ✅ Redis cache verified: msg id={}", saved.id)

        # 验证去重标记
        dedup_key = f"monitor:dedup:{test_msg.chat_id}:{test_msg.telegram_message_id}"
        exists = await redis.exists(dedup_key)
        assert exists, "Dedup key should exist in Redis"
        logger.info("  ✅ Redis dedup key set")

    # Step 6: 从 DB 读回验证
    loaded = await monitor_service.get_message_by_id(saved.id)
    assert loaded is not None
    assert loaded.message_text == test_text
    assert loaded.keyword_category == result.category
    logger.info("  ✅ Read back from DB: text matches, category matches")

    # 清理测试数据
    if redis:
        await redis.delete(f"monitor:msg:id:{saved.id}")
        await redis.delete(f"monitor:dedup:{test_msg.chat_id}:{test_msg.telegram_message_id}")
        await redis.srem(f"monitor:msg:chat:{test_msg.chat_id}", str(saved.id))
        await redis.srem(f"monitor:msg:sender:{test_msg.sender_id}", str(saved.id))
        await redis.srem(f"monitor:msg:category:{result.category}", str(saved.id))

    return True


# ==================== Test 4: 去重验证 ====================

async def test_dedup() -> bool:
    """测试同一消息去重逻辑"""
    logger.info("🔍 Test 4: Dedup verification ...")

    from config.redis_client import get_redis
    from models.message import MonitoredMessage
    from services.monitor_service import monitor_service

    chat_id = -5026789353
    telegram_msg_id = 999002

    # 第一次：不重复
    is_dup_1 = await monitor_service.is_duplicate(chat_id, telegram_msg_id)
    assert not is_dup_1, "First check should not be duplicate"
    logger.info("  ✅ First check: not duplicate")

    # 保存消息（会设置去重标记）
    msg = MonitoredMessage(
        telegram_message_id=telegram_msg_id,
        chat_id=chat_id,
        chat_title="Testing",
        sender_id=12345678,
        sender_username="test_user",
        sender_display_name="Test Dedup",
        message_text="Dedup test message about relinx",
        message_type="text",
        matched_keywords=["relinx"],
        keyword_category="brand",
        monitor_account_phone="+13239025485",
        message_date=datetime.now(),
    )
    saved = await monitor_service.save_message(msg)
    logger.info("  ✅ Message saved: id={}", saved.id)

    # 第二次：应该重复
    is_dup_2 = await monitor_service.is_duplicate(chat_id, telegram_msg_id)
    assert is_dup_2, "Second check SHOULD be duplicate"
    logger.info("  ✅ Second check: correctly detected as duplicate")

    # 清理
    redis = await get_redis()
    if redis:
        await redis.delete(f"monitor:dedup:{chat_id}:{telegram_msg_id}")
        await redis.delete(f"monitor:msg:id:{saved.id}")
        await redis.srem(f"monitor:msg:chat:{chat_id}", str(saved.id))
        await redis.srem(f"monitor:msg:sender:12345678", str(saved.id))
        await redis.srem(f"monitor:msg:category:brand", str(saved.id))

    return True


# ==================== Test 5: 压力测试 ====================

async def test_stress() -> bool:
    """批量消息写入性能测试"""
    logger.info("🔍 Test 5: Stress test — batch message writes ...")

    from config.redis_client import get_redis
    from models.message import MonitoredMessage
    from services.monitor_service import monitor_service

    batch_size = 100
    saved_ids = []

    start_time = time.time()

    for i in range(batch_size):
        msg = MonitoredMessage(
            telegram_message_id=900000 + i,
            chat_id=-5026789353,
            chat_title="Testing",
            sender_id=12345678 + (i % 10),
            sender_username=f"user_{i % 10}",
            sender_display_name=f"User {i % 10}",
            message_text=f"Stress test message #{i} about relinx gift cards",
            message_type="text",
            matched_keywords=["relinx", "gift card"],
            keyword_category="brand",
            monitor_account_phone="+13239025485",
            message_date=datetime.now(),
        )
        saved = await monitor_service.save_message(msg)
        saved_ids.append(saved.id)

    elapsed = time.time() - start_time
    rate = batch_size / elapsed

    logger.info(
        "  ✅ Wrote {} messages in {:.2f}s ({:.0f} msg/s)",
        batch_size,
        elapsed,
        rate,
    )

    # 验证去重：最后一条应该被检测为重复
    last_dup = await monitor_service.is_duplicate(-5026789353, 900000 + batch_size - 1)
    assert last_dup, "Last written message should be detected as duplicate"
    logger.info("  ✅ Dedup after batch write: verified")

    # 清理
    redis = await get_redis()
    if redis:
        for sid in saved_ids:
            await redis.delete(f"monitor:msg:id:{sid}")
        for i in range(batch_size):
            await redis.delete(f"monitor:dedup:-5026789353:{900000 + i}")

        await redis.delete("monitor:msg:chat:-5026789353")
        for i in range(10):
            await redis.delete(f"monitor:msg:sender:{12345678 + i}")
        await redis.delete("monitor:msg:category:brand")

    logger.info("  ✅ Cleanup done")

    # 性能门槛：至少 50 msg/s
    assert rate > 50, f"Performance too low: {rate:.0f} msg/s (minimum 50)"
    logger.info("  ✅ Performance OK: {:.0f} msg/s (threshold: 50)", rate)

    return True


# ==================== Test 6: 关键词热加载 ====================

async def test_keyword_reload() -> bool:
    """测试关键词热加载机制"""
    logger.info("🔍 Test 6: Keyword hot-reload ...")

    from config.redis_client import get_redis
    from services.keyword_service import keyword_service

    # 加载关键词
    await keyword_service.load_keywords()
    keywords_before = await keyword_service.get_all_active_keywords()
    count_before = len(keywords_before)
    logger.info("  ✅ Loaded {} keywords", count_before)

    # 调用 reload（应该不重新加载因为间隔未到）
    await keyword_service.reload_if_needed()
    keywords_after = await keyword_service.get_all_active_keywords()
    assert len(keywords_after) == count_before, "Count should be same after reload"
    logger.info("  ✅ Reload skipped (interval not reached) — count unchanged")

    # 重置内存计时器 + Redis 标记，强制重加载
    redis = await get_redis()
    if redis:
        await redis.delete("monitor:keyword:reload")
    # 重置内存中的 _last_reload_time 以绕过间隔检查
    keyword_service._last_reload_time = 0
    keyword_service._last_db_updated_at = None
    reloaded = await keyword_service.reload_if_needed()
    keywords_reloaded = await keyword_service.get_all_active_keywords()
    assert len(keywords_reloaded) == count_before
    logger.info("  ✅ Forced reload (timer reset) — reloaded={}, count={}", reloaded, len(keywords_reloaded))

    return True


# ==================== Test 7: MonitoredChat 管线 ====================

async def test_monitored_chat_pipeline() -> bool:
    """测试群组配置的完整管线：.env → DB → Redis → reload"""
    logger.info("🔍 Test 7: MonitoredChat pipeline ...")

    from handlers.message_handler import (
        get_monitored_chat_ids,
        reload_monitored_chat_ids,
        set_monitored_chat_ids,
    )
    from services.monitored_chat_service import monitored_chat_service

    # 加载群组 IDs
    chat_ids = await monitored_chat_service.get_all_active_chat_ids()
    logger.info("  ✅ Active chat IDs from service: {} IDs", len(chat_ids))

    # 注入到 message_handler
    set_monitored_chat_ids(set(chat_ids))
    current = get_monitored_chat_ids()
    assert len(current) == len(chat_ids)
    logger.info("  ✅ Injected into message_handler: {} IDs", len(current))

    # reload
    await reload_monitored_chat_ids()
    reloaded = get_monitored_chat_ids()
    assert len(reloaded) == len(chat_ids)
    logger.info("  ✅ reload_monitored_chat_ids() — count={}", len(reloaded))

    return True


# ==================== 主运行器 ====================

async def run_all_tests() -> None:
    """运行所有 Phase 5 集成测试"""
    from config.database import close_pool
    from config.redis_client import close_redis

    logger.info("=" * 60)
    logger.info("🚀 Phase 5 Integration Tests Starting...")
    logger.info("=" * 60)

    passed = 0
    failed = 0
    tests = [
        ("ENV Sync", test_env_sync),
        ("Connection Verify", test_connection_verify),
        ("Message Pipeline", test_message_pipeline),
        ("Dedup Verification", test_dedup),
        ("Stress Test", test_stress),
        ("Keyword Reload", test_keyword_reload),
        ("MonitoredChat Pipeline", test_monitored_chat_pipeline),
    ]

    for name, test_fn in tests:
        try:
            result = await test_fn()
            if result:
                logger.info("✅ {} — ALL PASSED", name)
                passed += 1
            else:
                logger.error("❌ {} — FAILED", name)
                failed += 1
        except Exception as e:
            logger.error("❌ {} — ERROR: {}", name, e)
            import traceback
            traceback.print_exc()
            failed += 1

    # 清理
    try:
        await close_redis()
        await close_pool()
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("📊 Phase 5 Test Results: {}/{} passed, {} failed", passed, passed + failed, failed)
    if failed == 0:
        logger.info("🎉 Phase 5 Integration Tests — ALL TESTS PASSED")
    else:
        logger.error("💥 Phase 5 Integration Tests — {} FAILURES", failed)
    logger.info("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
