#!/usr/bin/env python3
# TGMonitor/src/tests/test_services.py
"""
阶段 3 单元测试：Service 层两级存储验证
测试：
1. MonitorService — Redis + MySQL 双写、先查 Redis 再查 MySQL、消息去重
2. KeywordService — 加载到 Redis、Redis 优先读取、热加载检测
3. AccountService — 加载账号、状态更新、Redis 缓存
4. EntityCacheService — 用户/群组缓存、TTL 验证

使用方式：
    cd TGMonitor
    python3 src/tests/test_services.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logger import logger


# ==================== MonitorService Tests ====================

async def test_monitor_service_save_and_read() -> bool:
    """测试 MonitorService 的双写流程和先 Redis 后 MySQL 的读取流程"""
    logger.info("🔍 Testing MonitorService — save_message + get_message_by_id ...")

    from config.redis_client import get_redis
    from services.monitor_service import monitor_service
    from models.message import MonitoredMessage

    now = datetime.now()

    # 1. 保存消息（双写 MySQL + Redis）
    msg = MonitoredMessage(
        telegram_message_id=888001,
        chat_id=-100888888,
        chat_title="Service Test Group",
        sender_id=222333444,
        sender_username="svc_test_user",
        sender_display_name="SVC Test",
        message_text="relinx service test message",
        message_type="text",
        matched_keywords=["relinx"],
        keyword_category="brand",
        monitor_account_phone="+8613800000099",
        message_date=now,
    )
    saved = await monitor_service.save_message(msg)
    assert saved.id is not None and saved.id > 0, f"save_message returned invalid id: {saved.id}"
    logger.info("  ✅ save_message() — id={}", saved.id)

    # 2. 验证 Redis 缓存已写入
    redis = await get_redis()
    if redis:
        cached_raw = await redis.get(f"monitor:msg:id:{saved.id}")
        assert cached_raw is not None, "Redis cache NOT written after save_message"
        cached_msg = MonitoredMessage.model_validate_json(cached_raw)
        assert cached_msg.id == saved.id
        assert cached_msg.telegram_message_id == 888001
        logger.info("  ✅ Redis cache verified after save")

        # 3. 验证索引
        chat_members = await redis.smembers(f"monitor:msg:chat:{msg.chat_id}")
        assert str(saved.id) in chat_members, "Chat index NOT updated"
        logger.info("  ✅ Redis chat index verified")

        sender_members = await redis.smembers(f"monitor:msg:sender:{msg.sender_id}")
        assert str(saved.id) in sender_members, "Sender index NOT updated"
        logger.info("  ✅ Redis sender index verified")

        category_members = await redis.smembers(f"monitor:msg:category:{msg.keyword_category}")
        assert str(saved.id) in category_members, "Category index NOT updated"
        logger.info("  ✅ Redis category index verified")

        # 4. 验证去重标记
        dedup_key = f"monitor:dedup:{msg.chat_id}:{msg.telegram_message_id}"
        dedup_exists = await redis.exists(dedup_key)
        assert dedup_exists, "Dedup key NOT set after save_message"
        logger.info("  ✅ Redis dedup key verified")

    # 5. 先 Redis 后 MySQL 的读取（Redis 命中）
    fetched = await monitor_service.get_message_by_id(saved.id)
    assert fetched is not None, "get_message_by_id returned None"
    assert fetched.id == saved.id
    assert fetched.telegram_message_id == 888001
    logger.info("  ✅ get_message_by_id() — Redis hit path")

    # 6. 删除 Redis 缓存后验证 MySQL 回源
    if redis:
        await redis.delete(f"monitor:msg:id:{saved.id}")
        fetched_from_db = await monitor_service.get_message_by_id(saved.id)
        assert fetched_from_db is not None, "get_message_by_id failed on MySQL fallback"
        assert fetched_from_db.id == saved.id
        logger.info("  ✅ get_message_by_id() — MySQL fallback + backfill path")

        # 验证回写 Redis 后缓存已恢复
        re_cached = await redis.get(f"monitor:msg:id:{saved.id}")
        assert re_cached is not None, "Redis backfill NOT working"
        logger.info("  ✅ Redis backfill verified after MySQL fallback")

    # 7. 清理测试数据
    from repositories.monitor_repository import monitor_repository
    await monitor_repository.delete_by_id(saved.id)
    if redis:
        await redis.delete(f"monitor:msg:id:{saved.id}")
        await redis.srem(f"monitor:msg:chat:{msg.chat_id}", str(saved.id))
        await redis.srem(f"monitor:msg:sender:{msg.sender_id}", str(saved.id))
        await redis.srem(f"monitor:msg:category:{msg.keyword_category}", str(saved.id))
        await redis.delete(f"monitor:dedup:{msg.chat_id}:{msg.telegram_message_id}")
    logger.info("  ✅ Cleanup done")

    return True


async def test_monitor_service_dedup() -> bool:
    """测试 MonitorService 的消息去重逻辑"""
    logger.info("🔍 Testing MonitorService — is_duplicate ...")

    from config.redis_client import get_redis
    from services.monitor_service import monitor_service
    from models.message import MonitoredMessage

    now = datetime.now()
    test_chat_id = -100777777
    test_tg_msg_id = 777001

    # 1. 未处理的消息不应被标记为重复
    is_dup = await monitor_service.is_duplicate(test_chat_id, test_tg_msg_id)
    assert is_dup is False, "New message falsely marked as duplicate"
    logger.info("  ✅ is_duplicate() — new message = False")

    # 2. 保存消息后应被标记为重复
    msg = MonitoredMessage(
        telegram_message_id=test_tg_msg_id,
        chat_id=test_chat_id,
        chat_title="Dedup Test Group",
        sender_id=555666777,
        message_text="dedup test",
        message_type="text",
        matched_keywords=["test"],
        keyword_category="product",
        monitor_account_phone="+8613800000098",
        message_date=now,
    )
    saved = await monitor_service.save_message(msg)
    assert saved.id is not None

    is_dup_after = await monitor_service.is_duplicate(test_chat_id, test_tg_msg_id)
    assert is_dup_after is True, "Saved message NOT marked as duplicate"
    logger.info("  ✅ is_duplicate() — after save = True")

    # 3. 清理
    from repositories.monitor_repository import monitor_repository
    await monitor_repository.delete_by_id(saved.id)
    redis = await get_redis()
    if redis:
        await redis.delete(f"monitor:msg:id:{saved.id}")
        await redis.srem(f"monitor:msg:chat:{msg.chat_id}", str(saved.id))
        await redis.srem(f"monitor:msg:sender:{msg.sender_id}", str(saved.id))
        await redis.srem(f"monitor:msg:category:{msg.keyword_category}", str(saved.id))
        await redis.delete(f"monitor:dedup:{msg.chat_id}:{msg.telegram_message_id}")
    logger.info("  ✅ Cleanup done")

    return True


# ==================== KeywordService Tests ====================

async def test_keyword_service() -> bool:
    """测试 KeywordService 的加载、Redis 查询和热加载"""
    logger.info("🔍 Testing KeywordService — load + query + reload ...")

    from config.redis_client import get_redis
    from services.keyword_service import keyword_service

    # 1. 全量加载到 Redis
    await keyword_service.load_keywords()
    logger.info("  ✅ load_keywords() — completed")

    # 2. 从 Redis 读取
    keywords = await keyword_service.get_all_active_keywords()
    assert len(keywords) > 0, "get_all_active_keywords returned empty list"
    logger.info("  ✅ get_all_active_keywords() — {} results (Redis path)", len(keywords))

    # 3. 验证 Redis Hash 存在
    redis = await get_redis()
    if redis:
        data = await redis.hgetall("monitor:keyword:all")
        assert len(data) > 0, "Redis keyword hash is empty after load"
        assert len(data) == len(keywords), (
            f"Redis hash count ({len(data)}) != keyword count ({len(keywords)})"
        )
        logger.info("  ✅ Redis hash verified: {} entries", len(data))

    # 4. 按分类查询
    brand_kws = await keyword_service.get_keywords_by_category("brand")
    assert len(brand_kws) >= 1, "Should have at least 1 brand keyword from seed data"
    assert all(kw.category == "brand" for kw in brand_kws)
    logger.info("  ✅ get_keywords_by_category('brand') — {} results", len(brand_kws))

    # 5. 热加载检测（无变更场景）
    keyword_service._last_reload_time = 0  # 强制允许检查
    reloaded = await keyword_service.reload_if_needed()
    # 初始场景下无变更，应返回 False（因为 updated_at 一致）
    logger.info("  ✅ reload_if_needed() — reloaded={}", reloaded)

    # 6. 清理 Redis 后验证 MySQL 回源
    if redis:
        await redis.delete("monitor:keyword:all")
        kws_from_db = await keyword_service.get_all_active_keywords()
        assert len(kws_from_db) > 0, "MySQL fallback returned empty"
        logger.info("  ✅ MySQL fallback verified — {} keywords", len(kws_from_db))

        # 验证回源后 Redis 已回填
        re_data = await redis.hgetall("monitor:keyword:all")
        assert len(re_data) > 0, "Redis backfill NOT working after MySQL fallback"
        logger.info("  ✅ Redis backfill verified after MySQL fallback")

    return True


# ==================== AccountService Tests ====================

async def test_account_service() -> bool:
    """测试 AccountService 的加载、查询和状态更新"""
    logger.info("🔍 Testing AccountService — load + query + status ...")

    from config.redis_client import get_redis
    from services.account_service import account_service
    from models.account import MonitorAccount
    from repositories.account_repository import account_repository

    # 1. 插入测试账号
    test_account = MonitorAccount(
        phone="+8619900000001",
        api_id=12345678,
        api_hash="test_api_hash_value_abc",
        session_name="test_svc_session",
        display_name="SVC Test Account",
        is_active=True,
        status="offline",
    )
    acc_id = await account_repository.insert(test_account)
    assert acc_id > 0
    test_account.id = acc_id
    logger.info("  ✅ Test account inserted: id={}", acc_id)

    # 2. 加载账号到 Redis
    accounts = await account_service.load_accounts()
    assert any(a.phone == "+8619900000001" for a in accounts), "Test account not in loaded list"
    logger.info("  ✅ load_accounts() — {} accounts", len(accounts))

    # 3. 验证 Redis 缓存
    redis = await get_redis()
    if redis:
        cached = await redis.get(f"monitor:account:phone:+8619900000001")
        assert cached is not None, "Account NOT cached in Redis"
        logger.info("  ✅ Redis account cache verified")

    # 4. 从 Redis 查询
    found = await account_service.get_account_by_phone("+8619900000001")
    assert found is not None, "get_account_by_phone returned None"
    assert found.phone == "+8619900000001"
    logger.info("  ✅ get_account_by_phone() — found")

    # 5. 更新状态
    ok = await account_service.update_status("+8619900000001", "online")
    assert ok is True, "update_status returned False"
    logger.info("  ✅ update_status('online') — success")

    # 验证状态更新后 Redis 缓存已刷新
    if redis:
        cached_after = await redis.get(f"monitor:account:phone:+8619900000001")
        if cached_after:
            acc_data = MonitorAccount.model_validate_json(cached_after)
            assert acc_data.status == "online", f"Redis status not updated: {acc_data.status}"
            logger.info("  ✅ Redis status cache refreshed after update")

    # 6. 清理
    await account_repository.delete_by_id(acc_id)
    if redis:
        await redis.delete(f"monitor:account:id:{acc_id}")
        await redis.delete(f"monitor:account:phone:+8619900000001")
        await redis.srem("monitor:account:active", str(acc_id))
    logger.info("  ✅ Cleanup done")

    return True


# ==================== EntityCacheService Tests ====================

async def test_entity_cache_service() -> bool:
    """测试 EntityCacheService 的用户/群组缓存"""
    logger.info("🔍 Testing EntityCacheService — user/chat cache ...")

    from config.redis_client import get_redis
    from services.entity_cache_service import entity_cache_service

    test_user_id = 999888777
    test_chat_id = -100666555

    # 1. 缓存未命中
    user = await entity_cache_service.get_user(test_user_id)
    assert user is None, "Should return None for uncached user"
    logger.info("  ✅ get_user() — cache miss = None")

    # 2. 写入用户缓存
    user_data = {
        "id": test_user_id,
        "username": "cache_test_user",
        "first_name": "Cache",
        "last_name": "Test",
    }
    await entity_cache_service.cache_user(test_user_id, user_data)
    logger.info("  ✅ cache_user() — written")

    # 3. 缓存命中
    cached_user = await entity_cache_service.get_user(test_user_id)
    assert cached_user is not None, "Should return cached user"
    assert cached_user["username"] == "cache_test_user"
    assert cached_user["first_name"] == "Cache"
    logger.info("  ✅ get_user() — cache hit verified")

    # 4. 验证 TTL
    redis = await get_redis()
    if redis:
        ttl = await redis.ttl(f"monitor:entity:user:{test_user_id}")
        assert ttl > 0, f"TTL should be positive, got {ttl}"
        logger.info("  ✅ User cache TTL = {} seconds", ttl)

    # 5. 失效缓存
    await entity_cache_service.invalidate_user(test_user_id)
    invalidated = await entity_cache_service.get_user(test_user_id)
    assert invalidated is None, "User cache NOT invalidated"
    logger.info("  ✅ invalidate_user() — verified")

    # 6. 群组缓存
    chat_data = {
        "id": test_chat_id,
        "title": "Cache Test Group",
        "username": "cache_test_group",
    }
    await entity_cache_service.cache_chat(test_chat_id, chat_data)

    cached_chat = await entity_cache_service.get_chat(test_chat_id)
    assert cached_chat is not None, "Should return cached chat"
    assert cached_chat["title"] == "Cache Test Group"
    logger.info("  ✅ cache_chat() + get_chat() — verified")

    if redis:
        ttl = await redis.ttl(f"monitor:entity:chat:{test_chat_id}")
        assert ttl > 0, f"Chat TTL should be positive, got {ttl}"
        logger.info("  ✅ Chat cache TTL = {} seconds", ttl)

    # 7. 清理
    await entity_cache_service.invalidate_chat(test_chat_id)
    logger.info("  ✅ Cleanup done")

    return True


# ==================== 主运行器 ====================

async def run_all_tests() -> None:
    """运行所有 Service 单元测试"""
    from config.database import close_pool
    from config.redis_client import close_redis

    logger.info("=" * 60)
    logger.info("🚀 Phase 3 Service Tests Starting...")
    logger.info("=" * 60)

    passed = 0
    failed = 0
    tests = [
        ("MonitorService — save & read", test_monitor_service_save_and_read),
        ("MonitorService — dedup", test_monitor_service_dedup),
        ("KeywordService", test_keyword_service),
        ("AccountService", test_account_service),
        ("EntityCacheService", test_entity_cache_service),
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
            logger.error("❌ {} — EXCEPTION: {}", name, e)
            import traceback
            traceback.print_exc()
            failed += 1

    # 清理连接
    await close_redis()
    await close_pool()

    logger.info("=" * 60)
    logger.info(
        "📊 Phase 3 Test Results: {}/{} passed, {} failed",
        passed,
        passed + failed,
        failed,
    )
    if failed == 0:
        logger.info("🎉 Phase 3 Service Layer — ALL TESTS PASSED")
    else:
        logger.error("⚠️ Phase 3 Service Layer — {} TESTS FAILED", failed)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
