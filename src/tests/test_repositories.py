#!/usr/bin/env python3
# TGMonitor/src/tests/test_repositories.py
"""
阶段 2 单元测试：Repository 层 CRUD 验证
测试所有 4 个 Repository 的核心操作，确保 SQL 正确、连接池正常。

使用方式：
    cd TGMonitor
    python3 src/tests/test_repositories.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logger import logger


async def test_monitor_repository() -> bool:
    """测试 MonitorRepository 的 CRUD 操作"""
    logger.info("🔍 Testing MonitorRepository ...")

    from repositories.monitor_repository import monitor_repository
    from models.message import MonitoredMessage

    now = datetime.now()

    # 1. INSERT
    msg = MonitoredMessage(
        telegram_message_id=999001,
        chat_id=-100999999,
        chat_title="Test Group",
        sender_id=111222333,
        sender_username="test_user",
        sender_display_name="Test User",
        message_text="I love relinx for buying gift cards",
        message_type="text",
        reply_to_message_id=None,
        matched_keywords=["relinx", "gift card"],
        keyword_category="brand",
        monitor_account_phone="+8613800000001",
        message_date=now,
        created_at=now,
    )
    msg_id = await monitor_repository.insert(msg)
    assert msg_id > 0, f"insert returned invalid id: {msg_id}"
    logger.info("  ✅ insert() — id={}", msg_id)

    # 2. GET BY ID
    fetched = await monitor_repository.get_by_id(msg_id)
    assert fetched is not None, "get_by_id returned None"
    assert fetched.telegram_message_id == 999001
    assert fetched.chat_id == -100999999
    assert fetched.sender_username == "test_user"
    assert "relinx" in fetched.matched_keywords
    assert fetched.keyword_category == "brand"
    logger.info("  ✅ get_by_id() — matched")

    # 3. GET BY CHAT ID
    by_chat = await monitor_repository.get_by_chat_id(-100999999, limit=10, offset=0)
    assert len(by_chat) >= 1
    assert any(m.id == msg_id for m in by_chat)
    logger.info("  ✅ get_by_chat_id() — {} results", len(by_chat))

    # 4. GET BY DATE RANGE
    start = now - timedelta(minutes=5)
    end = now + timedelta(minutes=5)
    by_date = await monitor_repository.get_by_date_range(start, end, limit=100)
    assert len(by_date) >= 1
    logger.info("  ✅ get_by_date_range() — {} results", len(by_date))

    # 5. GET BY KEYWORD CATEGORY
    by_category = await monitor_repository.get_by_keyword_category("brand", limit=10, offset=0)
    assert len(by_category) >= 1
    logger.info("  ✅ get_by_keyword_category() — {} results", len(by_category))

    # 6. COUNT BY CHAT ID
    count = await monitor_repository.count_by_chat_id(-100999999)
    assert count >= 1
    logger.info("  ✅ count_by_chat_id() — {}", count)

    # 7. DELETE
    deleted = await monitor_repository.delete_by_id(msg_id)
    assert deleted is True
    verify = await monitor_repository.get_by_id(msg_id)
    assert verify is None
    logger.info("  ✅ delete_by_id() — confirmed")

    return True


async def test_keyword_repository() -> bool:
    """测试 KeywordRepository 的 CRUD 操作"""
    logger.info("🔍 Testing KeywordRepository ...")

    from repositories.keyword_repository import keyword_repository
    from models.keyword import Keyword

    # 1. INSERT
    kw = Keyword(
        word="test_keyword_xyz",
        category="brand",
        match_type="exact",
        priority=100,
        is_active=True,
    )
    kw_id = await keyword_repository.insert(kw)
    assert kw_id > 0
    logger.info("  ✅ insert() — id={}", kw_id)

    # 2. GET BY ID
    fetched = await keyword_repository.get_by_id(kw_id)
    assert fetched is not None
    assert fetched.word == "test_keyword_xyz"
    assert fetched.category == "brand"
    assert fetched.priority == 100
    logger.info("  ✅ get_by_id() — matched")

    # 3. GET ALL ACTIVE
    all_active = await keyword_repository.get_all_active()
    assert len(all_active) >= 1
    assert any(k.id == kw_id for k in all_active)
    logger.info("  ✅ get_all_active() — {} keywords", len(all_active))

    # 4. GET BY CATEGORY
    by_cat = await keyword_repository.get_by_category("brand")
    assert len(by_cat) >= 1
    logger.info("  ✅ get_by_category('brand') — {} keywords", len(by_cat))

    # 5. UPDATE
    fetched.priority = 50
    fetched.match_type = "fuzzy"
    updated = await keyword_repository.update(fetched)
    assert updated is True
    re_fetched = await keyword_repository.get_by_id(kw_id)
    assert re_fetched.priority == 50
    assert re_fetched.match_type == "fuzzy"
    logger.info("  ✅ update() — verified")

    # 6. COUNT
    count = await keyword_repository.count_all()
    assert count >= 1
    logger.info("  ✅ count_all() — {}", count)

    # 7. GET LAST UPDATED AT
    last_updated = await keyword_repository.get_last_updated_at()
    assert last_updated is not None
    logger.info("  ✅ get_last_updated_at() — {}", last_updated)

    # 8. DELETE
    deleted = await keyword_repository.delete_by_id(kw_id)
    assert deleted is True
    verify = await keyword_repository.get_by_id(kw_id)
    assert verify is None
    logger.info("  ✅ delete_by_id() — confirmed")

    return True


async def test_account_repository() -> bool:
    """测试 AccountRepository 的 CRUD 操作"""
    logger.info("🔍 Testing AccountRepository ...")

    from repositories.account_repository import account_repository
    from models.account import MonitorAccount

    # 1. INSERT
    acct = MonitorAccount(
        phone="+8619999990001",
        api_id=12345678,
        api_hash="abcdef1234567890abcdef1234567890",
        session_name="test_session_001",
        display_name="Test Account",
        is_active=True,
        status="offline",
    )
    acct_id = await account_repository.insert(acct)
    assert acct_id > 0
    logger.info("  ✅ insert() — id={}", acct_id)

    # 2. GET BY ID
    fetched = await account_repository.get_by_id(acct_id)
    assert fetched is not None
    assert fetched.phone == "+8619999990001"
    assert fetched.api_id == 12345678
    assert fetched.session_name == "test_session_001"
    logger.info("  ✅ get_by_id() — matched")

    # 3. GET BY PHONE
    by_phone = await account_repository.get_by_phone("+8619999990001")
    assert by_phone is not None
    assert by_phone.id == acct_id
    logger.info("  ✅ get_by_phone() — matched")

    # 4. GET ALL ACTIVE
    all_active = await account_repository.get_all_active()
    assert len(all_active) >= 1
    logger.info("  ✅ get_all_active() — {} accounts", len(all_active))

    # 5. UPDATE STATUS
    updated = await account_repository.update_status("+8619999990001", "online")
    assert updated is True
    re_fetched = await account_repository.get_by_phone("+8619999990001")
    assert re_fetched.status == "online"
    assert re_fetched.last_connected_at is not None
    logger.info("  ✅ update_status() — verified online")

    # 6. UPDATE (full)
    re_fetched.display_name = "Updated Account"
    re_fetched.status = "offline"
    updated = await account_repository.update(re_fetched)
    assert updated is True
    verify = await account_repository.get_by_id(acct_id)
    assert verify.display_name == "Updated Account"
    logger.info("  ✅ update() — verified")

    # 7. DELETE
    deleted = await account_repository.delete_by_id(acct_id)
    assert deleted is True
    verify = await account_repository.get_by_id(acct_id)
    assert verify is None
    logger.info("  ✅ delete_by_id() — confirmed")

    return True


async def test_monitored_chat_repository() -> bool:
    """测试 MonitoredChatRepository 的 CRUD 操作"""
    logger.info("🔍 Testing MonitoredChatRepository ...")

    from repositories.monitored_chat_repository import monitored_chat_repository
    from models.monitored_chat import MonitoredChat

    now = datetime.now()

    # 1. INSERT
    chat = MonitoredChat(
        chat_id=-100888888888,
        chat_title="Test Monitored Group",
        chat_username="test_group_xyz",
        chat_type="supergroup",
        assigned_account_phone="+8613800000001",
        is_active=True,
        joined_at=now,
        note="Unit test chat",
    )
    chat_db_id = await monitored_chat_repository.insert(chat)
    assert chat_db_id > 0
    logger.info("  ✅ insert() — id={}", chat_db_id)

    # 2. GET BY ID
    fetched = await monitored_chat_repository.get_by_id(chat_db_id)
    assert fetched is not None
    assert fetched.chat_id == -100888888888
    assert fetched.chat_title == "Test Monitored Group"
    assert fetched.chat_type == "supergroup"
    logger.info("  ✅ get_by_id() — matched")

    # 3. GET BY CHAT ID
    by_chat_id = await monitored_chat_repository.get_by_chat_id(-100888888888)
    assert by_chat_id is not None
    assert by_chat_id.id == chat_db_id
    logger.info("  ✅ get_by_chat_id() — matched")

    # 4. GET ALL ACTIVE
    all_active = await monitored_chat_repository.get_all_active()
    assert len(all_active) >= 1
    logger.info("  ✅ get_all_active() — {} chats", len(all_active))

    # 5. GET BY ACCOUNT PHONE
    by_phone = await monitored_chat_repository.get_by_account_phone("+8613800000001")
    assert len(by_phone) >= 1
    logger.info("  ✅ get_by_account_phone() — {} chats", len(by_phone))

    # 6. GET ALL ACTIVE CHAT IDS
    chat_ids = await monitored_chat_repository.get_all_active_chat_ids()
    assert -100888888888 in chat_ids
    logger.info("  ✅ get_all_active_chat_ids() — {} ids", len(chat_ids))

    # 7. UPDATE
    fetched.note = "Updated note"
    fetched.chat_title = "Updated Group Title"
    updated = await monitored_chat_repository.update(fetched)
    assert updated is True
    verify = await monitored_chat_repository.get_by_id(chat_db_id)
    assert verify.note == "Updated note"
    assert verify.chat_title == "Updated Group Title"
    logger.info("  ✅ update() — verified")

    # 8. DELETE
    deleted = await monitored_chat_repository.delete_by_id(chat_db_id)
    assert deleted is True
    verify = await monitored_chat_repository.get_by_id(chat_db_id)
    assert verify is None
    logger.info("  ✅ delete_by_id() — confirmed")

    return True


async def run_all_tests() -> None:
    """运行所有 Repository 单元测试"""
    from config.database import close_pool

    logger.info("=" * 60)
    logger.info("🚀 Phase 2 Repository Tests Starting...")
    logger.info("=" * 60)

    passed = 0
    failed = 0
    tests = [
        ("MonitorRepository", test_monitor_repository),
        ("KeywordRepository", test_keyword_repository),
        ("AccountRepository", test_account_repository),
        ("MonitoredChatRepository", test_monitored_chat_repository),
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

    # 清理连接池
    await close_pool()

    logger.info("=" * 60)
    logger.info("📊 Phase 2 Test Results: {}/{} passed, {} failed", passed, passed + failed, failed)
    if failed == 0:
        logger.info("🎉 Phase 2 Repository Layer — ALL TESTS PASSED")
    else:
        logger.error("⚠️ Phase 2 Repository Layer — {} TESTS FAILED", failed)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
