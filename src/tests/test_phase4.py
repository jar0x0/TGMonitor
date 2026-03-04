#!/usr/bin/env python3
# TGMonitor/src/tests/test_phase4.py
"""
阶段 4 单元测试：核心监听功能
测试：
1. KeywordFilter — exact / regex / fuzzy 三种匹配策略
2. MessageRouter — 关键词路由 + 去重
3. MonitoredChatService — 群组 ID 加载缓存

使用方式：
    cd TGMonitor
    python3 src/tests/test_phase4.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logger import logger


# ==================== KeywordFilter Tests ====================

async def test_keyword_filter_exact() -> bool:
    """测试 KeywordFilter 的 exact 匹配模式"""
    logger.info("🔍 Testing KeywordFilter — exact match ...")

    from filters.keyword_filter import KeywordFilter

    kf = KeywordFilter()

    # exact: word boundary + case-insensitive
    assert kf._exact_match("i like relinx very much", "relinx") is True
    logger.info("  ✅ exact: 'relinx' in 'i like relinx very much' → True")

    assert kf._exact_match("relinx is great", "relinx") is True
    logger.info("  ✅ exact: 'relinx' at start of string → True")

    assert kf._exact_match("check out relinx", "relinx") is True
    logger.info("  ✅ exact: 'relinx' at end of string → True")

    # word boundary：不匹配词内子串
    assert kf._exact_match("relinxyz is not a match", "relinx") is False
    logger.info("  ✅ exact: 'relinx' NOT in 'relinxyz' → False (word boundary)")

    assert kf._exact_match("myrelinx app", "relinx") is False
    logger.info("  ✅ exact: 'relinx' NOT in 'myrelinx' → False (word boundary)")

    # case-insensitive
    assert kf._exact_match("i love relinx", "RELINX") is True
    logger.info("  ✅ exact: case-insensitive 'RELINX' matches 'relinx' → True")

    # 特殊字符关键词
    assert kf._exact_match("buy with usdt now", "usdt") is True
    logger.info("  ✅ exact: 'usdt' in 'buy with usdt now' → True")

    assert kf._exact_match("usdt", "usdt") is True
    logger.info("  ✅ exact: 'usdt' exact string → True")

    return True


async def test_keyword_filter_regex() -> bool:
    """测试 KeywordFilter 的 regex 匹配模式"""
    logger.info("🔍 Testing KeywordFilter — regex match ...")

    from filters.keyword_filter import KeywordFilter

    kf = KeywordFilter()

    # 正则匹配
    assert kf._regex_match("check re-linx site", r"re[-_]?linx") is True
    logger.info("  ✅ regex: 're-linx' matches r're[-_]?linx' → True")

    assert kf._regex_match("check re_linx site", r"re[-_]?linx") is True
    logger.info("  ✅ regex: 're_linx' matches r're[-_]?linx' → True")

    assert kf._regex_match("check relinx site", r"re[-_]?linx") is True
    logger.info("  ✅ regex: 'relinx' matches r're[-_]?linx' → True")

    assert kf._regex_match("check resolinx site", r"re[-_]?linx") is False
    logger.info("  ✅ regex: 'resolinx' NOT matches r're[-_]?linx' → False")

    # case-insensitive
    assert kf._regex_match("RE-LINX is cool", r"re[-_]?linx") is True
    logger.info("  ✅ regex: case-insensitive RE-LINX → True")

    # 无效正则不崩溃
    assert kf._regex_match("test", r"[invalid") is False
    logger.info("  ✅ regex: invalid pattern handled gracefully → False")

    return True


async def test_keyword_filter_fuzzy() -> bool:
    """测试 KeywordFilter 的 fuzzy（包含）匹配模式"""
    logger.info("🔍 Testing KeywordFilter — fuzzy match ...")

    from filters.keyword_filter import KeywordFilter

    kf = KeywordFilter()

    # fuzzy: keyword.lower() in text.lower()
    assert kf._fuzzy_match("cheap gift cards here", "gift card") is True
    logger.info("  ✅ fuzzy: 'gift card' in 'cheap gift cards here' → True")

    assert kf._fuzzy_match("i want a netflix subscription", "netflix") is True
    logger.info("  ✅ fuzzy: 'netflix' in longer text → True")

    # case-insensitive
    assert kf._fuzzy_match("STEAM games on sale", "steam") is True
    logger.info("  ✅ fuzzy: case-insensitive 'steam' in 'STEAM games' → True")

    # 不匹配
    assert kf._fuzzy_match("hello world", "relinx") is False
    logger.info("  ✅ fuzzy: 'relinx' NOT in 'hello world' → False")

    # 中文模糊匹配
    assert kf._fuzzy_match("这个平台是骗子", "骗") is True
    logger.info("  ✅ fuzzy: '骗' in '这个平台是骗子' → True")

    assert kf._fuzzy_match("商家不发货了怎么办", "不发货") is True
    logger.info("  ✅ fuzzy: '不发货' in Chinese text → True")

    return True


async def test_keyword_filter_full_match() -> bool:
    """测试 KeywordFilter.match() 完整流程（需要 KeywordService + 数据库）"""
    logger.info("🔍 Testing KeywordFilter.match() — full pipeline ...")

    from services.keyword_service import keyword_service
    from filters.keyword_filter import keyword_filter

    # 先加载关键词
    await keyword_service.load_keywords()

    # 1. 匹配 brand 类关键词
    result = await keyword_filter.match("I love relinx for buying gift cards")
    assert result is not None, "Should match 'relinx' and 'gift card'"
    assert "relinx" in result.matched_keywords
    assert result.category == "brand"  # brand 优先级 100 最高
    logger.info(
        "  ✅ match('...relinx...gift cards') → keywords={}, category='{}'",
        result.matched_keywords,
        result.category,
    )

    # 2. 匹配 risk 类关键词
    result2 = await keyword_filter.match("This is a scam, total fraud")
    assert result2 is not None
    assert "scam" in result2.matched_keywords or "fraud" in result2.matched_keywords
    assert result2.category == "risk"
    logger.info(
        "  ✅ match('...scam...fraud') → keywords={}, category='{}'",
        result2.matched_keywords,
        result2.category,
    )

    # 3. 无匹配
    result3 = await keyword_filter.match("Hello, how are you today?")
    assert result3 is None, "Should not match generic text"
    logger.info("  ✅ match('Hello, how are you today?') → None (no match)")

    # 4. 空文本
    result4 = await keyword_filter.match("")
    assert result4 is None
    logger.info("  ✅ match('') → None (empty text)")

    result5 = await keyword_filter.match("   ")
    assert result5 is None
    logger.info("  ✅ match('   ') → None (whitespace only)")

    # 5. payment 类关键词 (exact 匹配)
    result6 = await keyword_filter.match("Please pay with USDT via TRC20")
    assert result6 is not None
    assert "USDT" in result6.matched_keywords or "TRC20" in result6.matched_keywords
    logger.info(
        "  ✅ match('...USDT...TRC20') → keywords={}, category='{}'",
        result6.matched_keywords,
        result6.category,
    )

    return True


# ==================== MessageRouter Tests ====================

async def test_message_router() -> bool:
    """测试 MessageRouter 的路由功能"""
    logger.info("🔍 Testing MessageRouter — process + dedup ...")

    from services.keyword_service import keyword_service
    from core.message_router import process_message_text, check_duplicate

    # 确保关键词已加载
    await keyword_service.load_keywords()

    # 1. process_message_text — 命中
    result = await process_message_text("I just used relinx to buy steam keys")
    assert result is not None
    assert "relinx" in result.matched_keywords
    logger.info("  ✅ process_message_text() — matched keywords={}", result.matched_keywords)

    # 2. process_message_text — 未命中
    result2 = await process_message_text("Random unrelated message")
    assert result2 is None
    logger.info("  ✅ process_message_text() — no match → None")

    # 3. check_duplicate — 未处理的消息
    is_dup = await check_duplicate(-100999111, 999111)
    assert is_dup is False
    logger.info("  ✅ check_duplicate() — new message → False")

    return True


# ==================== MonitoredChatService Tests ====================

async def test_monitored_chat_service() -> bool:
    """测试 MonitoredChatService 的群组 ID 加载和缓存"""
    logger.info("🔍 Testing MonitoredChatService — load + cache ...")

    from config.redis_client import get_redis
    from services.monitored_chat_service import monitored_chat_service
    from models.monitored_chat import MonitoredChat
    from repositories.monitored_chat_repository import monitored_chat_repository

    # 1. 插入测试群组
    test_chat = MonitoredChat(
        chat_id=-100555444333,
        chat_title="Phase4 Test Group",
        chat_username="p4_test",
        chat_type="supergroup",
        assigned_account_phone="+8613800000099",
        is_active=True,
    )
    chat_db_id = await monitored_chat_repository.insert(test_chat)
    assert chat_db_id > 0
    logger.info("  ✅ Test chat inserted: db_id={}", chat_db_id)

    # 2. 获取所有活跃 chat_ids
    chat_ids = await monitored_chat_service.get_all_active_chat_ids()
    assert -100555444333 in chat_ids, "Test chat_id not in active list"
    logger.info("  ✅ get_all_active_chat_ids() — {} IDs, test chat found", len(chat_ids))

    # 3. 验证 Redis 缓存
    redis = await get_redis()
    if redis:
        members = await redis.smembers("monitor:chat:active_ids")
        assert str(-100555444333) in members, "Chat ID NOT in Redis cache"
        logger.info("  ✅ Redis cache verified: {} members", len(members))

    # 4. 清除缓存后验证 MySQL 回源
    await monitored_chat_service.invalidate_cache()
    chat_ids2 = await monitored_chat_service.get_all_active_chat_ids()
    assert -100555444333 in chat_ids2
    logger.info("  ✅ MySQL fallback after cache invalidation — verified")

    # 5. 清理
    await monitored_chat_repository.delete_by_id(chat_db_id)
    await monitored_chat_service.invalidate_cache()
    logger.info("  ✅ Cleanup done")

    return True


# ==================== MessageHandler Unit Tests ====================

async def test_message_handler_chat_ids() -> bool:
    """测试 MessageHandler 的群组 ID 管理"""
    logger.info("🔍 Testing MessageHandler — chat ID management ...")

    from handlers.message_handler import (
        set_monitored_chat_ids,
        get_monitored_chat_ids,
    )

    # 设置群组 ID
    test_ids = {-100111222333, -100444555666, -100777888999}
    set_monitored_chat_ids(test_ids)

    current = get_monitored_chat_ids()
    assert current == test_ids, f"Chat IDs mismatch: {current} != {test_ids}"
    logger.info("  ✅ set_monitored_chat_ids() + get_monitored_chat_ids() — verified")

    # 清空
    set_monitored_chat_ids(set())
    assert len(get_monitored_chat_ids()) == 0
    logger.info("  ✅ Clear chat IDs — verified")

    return True


# ==================== 主运行器 ====================

async def run_all_tests() -> None:
    """运行所有 Phase 4 单元测试"""
    from config.database import close_pool
    from config.redis_client import close_redis

    logger.info("=" * 60)
    logger.info("🚀 Phase 4 Core Monitoring Tests Starting...")
    logger.info("=" * 60)

    passed = 0
    failed = 0
    tests = [
        ("KeywordFilter — exact", test_keyword_filter_exact),
        ("KeywordFilter — regex", test_keyword_filter_regex),
        ("KeywordFilter — fuzzy", test_keyword_filter_fuzzy),
        ("KeywordFilter — full match", test_keyword_filter_full_match),
        ("MessageRouter", test_message_router),
        ("MonitoredChatService", test_monitored_chat_service),
        ("MessageHandler — chat IDs", test_message_handler_chat_ids),
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
        "📊 Phase 4 Test Results: {}/{} passed, {} failed",
        passed,
        passed + failed,
        failed,
    )
    if failed == 0:
        logger.info("🎉 Phase 4 Core Monitoring — ALL TESTS PASSED")
    else:
        logger.error("⚠️ Phase 4 Core Monitoring — {} TESTS FAILED", failed)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
