#!/usr/bin/env python3
# TGMonitor/src/scripts/manage_chats.py
"""
管理监控群组（添加 / 禁用 / 启用 / 删除），无需重启服务。

修改写入 MySQL 后自动清除 Redis 缓存，运行中的服务会在下一个
刷新周期（≤5 分钟）自动加载最新群组列表。

使用方式：
    cd TGMonitor/src
    python3 scripts/manage_chats.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings

# Redis Key 常量（与 monitored_chat_service 保持一致）
REDIS_KEY_CHAT_IDS = "monitor:chat:active_ids"


# ==================== 数据库操作（独立于 Service 层） ====================

async def _get_pool():
    """获取 MySQL 连接池。"""
    from config.database import get_pool
    return await get_pool()


async def _get_redis():
    """获取 Redis 客户端（可能为 None）。"""
    from config.redis_client import get_redis
    return await get_redis()


async def _invalidate_redis_cache() -> None:
    """清除 Redis 中的群组缓存，使运行中的服务从 MySQL 重新加载。"""
    try:
        redis = await _get_redis()
        if redis:
            await redis.delete(REDIS_KEY_CHAT_IDS)
            print("🗑️  已清除 Redis 群组缓存")
    except Exception as e:
        print(f"⚠️  清除 Redis 缓存失败（不影响 MySQL 数据）: {e}")


async def _close_all() -> None:
    """关闭连接池。"""
    from config.redis_client import close_redis
    from config.database import close_pool
    await close_redis()
    await close_pool()


async def _fetch_monitored_chats() -> list:
    """获取所有已配置的监控群组（含已禁用的）。"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, chat_id, chat_title, chat_type, is_active, assigned_account_phone "
                "FROM tgm_monitored_chat ORDER BY is_active DESC, id ASC"
            )
            return await cur.fetchall()


async def _insert_chat(chat_id: int, title: str, chat_type: str, phone: str) -> int:
    """插入新群组到 MySQL，返回自增 ID。"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 先检查是否已存在
            await cur.execute(
                "SELECT id, is_active FROM tgm_monitored_chat WHERE chat_id = %s",
                (chat_id,),
            )
            existing = await cur.fetchone()
            if existing:
                db_id, is_active = existing
                if not is_active:
                    # 已存在但被禁用→重新启用
                    await cur.execute(
                        "UPDATE tgm_monitored_chat SET is_active = 1, chat_title = %s WHERE id = %s",
                        (title, db_id),
                    )
                    print(f"♻️  群组已存在（曾被禁用），已重新启用 (db_id={db_id})")
                    return db_id
                else:
                    print(f"ℹ️  群组已在监控列表中 (db_id={db_id})，无需重复添加")
                    return db_id

            await cur.execute(
                "INSERT INTO tgm_monitored_chat "
                "(chat_id, chat_title, chat_type, assigned_account_phone, is_active) "
                "VALUES (%s, %s, %s, %s, 1)",
                (chat_id, title, chat_type, phone),
            )
            return cur.lastrowid


async def _set_active(db_id: int, active: bool) -> bool:
    """设置群组启用/禁用状态。"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE tgm_monitored_chat SET is_active = %s WHERE id = %s",
                (int(active), db_id),
            )
            return cur.rowcount > 0


async def _delete_chat(db_id: int) -> bool:
    """物理删除群组记录。"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM tgm_monitored_chat WHERE id = %s", (db_id,)
            )
            return cur.rowcount > 0


# ==================== 交互式操作 ====================

async def action_add() -> None:
    """添加新的监控群组（从 Telegram 账号的已加入群组中选取）。"""
    import shutil
    import tempfile
    from telethon import TelegramClient

    accounts = settings.get_accounts()
    if not accounts:
        print("❌ 未在 .env 中找到账号配置")
        return

    # 选择账号
    if len(accounts) == 1:
        selected = accounts[0]
    else:
        print("\n📋 可用账号:")
        for idx, acc in enumerate(accounts, 1):
            print(f"  [{idx}] {acc['phone']} ({acc['display_name']})")
        choice = input(f"选择账号 [1-{len(accounts)}]: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(accounts):
            print("❌ 无效选择")
            return
        selected = accounts[int(choice) - 1]

    phone = selected["phone"]
    original_session = str(settings.sessions_dir / selected["session_name"]) + ".session"

    # 复制 session 文件到临时目录，避免与运行中的服务争锁
    tmp_dir = tempfile.mkdtemp(prefix="tgm_")
    tmp_session = str(Path(tmp_dir) / selected["session_name"])
    shutil.copy2(original_session, tmp_session + ".session")

    print(f"\n🔗 使用账号 {phone} 连接 Telegram...")
    client = TelegramClient(tmp_session, selected["api_id"], selected["api_hash"])

    try:
        await client.connect()

        if not await client.is_user_authorized():
            print("❌ 账号未认证，请先运行 python3 auth.py")
            await client.disconnect()
            return

        # 获取已监控的 chat_id 集合
        monitored_rows = await _fetch_monitored_chats()
        monitored_ids = {row[1] for row in monitored_rows if row[4]}  # chat_id where is_active

        # 列出 Telegram 中的群组（排除已监控的）
        available = []
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                if dialog.id not in monitored_ids:
                    chat_type = "channel" if dialog.is_channel and not dialog.is_group else (
                        "supergroup" if getattr(dialog.entity, "megagroup", False) else "group"
                    )
                    available.append({
                        "chat_id": dialog.id,
                        "title": dialog.title,
                        "type": chat_type,
                        "members": getattr(dialog.entity, "participants_count", "?"),
                    })

        await client.disconnect()

    finally:
        # 清理临时 session 文件
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not available:
        print("\n✅ 该账号的所有群组/频道均已在监控列表中")
        return

    # 显示可添加的群组
    print(f"\n{'='*70}")
    print(f"  可添加的群组/频道 ({len(available)} 个)")
    print(f"{'='*70}")
    print(f"  {'序号':<6} {'chat_id':<20} {'类型':<12} {'成员':<8} {'名称'}")
    print(f"  {'-'*4:<6} {'-'*18:<20} {'-'*10:<12} {'-'*6:<8} {'-'*20}")
    for idx, g in enumerate(available, 1):
        print(f"  {idx:<6} {g['chat_id']:<20} {g['type']:<12} {str(g['members']):<8} {g['title']}")

    print(f"\n  输入序号添加（多个用逗号分隔，如 1,3,5），输入 0 取消")
    choice = input("  选择: ").strip()
    if choice == "0" or not choice:
        print("  已取消")
        return

    # 解析选择
    indices = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(available):
            indices.append(int(part) - 1)

    if not indices:
        print("❌ 无效选择")
        return

    # 写入 MySQL
    added = 0
    for i in indices:
        g = available[i]
        db_id = await _insert_chat(g["chat_id"], g["title"], g["type"], phone)
        print(f"  ✅ 已添加: {g['title']} (chat_id={g['chat_id']}, db_id={db_id})")
        added += 1

    if added:
        await _invalidate_redis_cache()
        print(f"\n📋 共添加 {added} 个群组，服务将在下一刷新周期（≤5分钟）自动生效")


async def action_list() -> None:
    """查看当前所有监控群组。"""
    rows = await _fetch_monitored_chats()
    if not rows:
        print("\n📋 暂无配置任何监控群组")
        return

    print(f"\n{'='*80}")
    print(f"  当前监控群组 ({len(rows)} 个)")
    print(f"{'='*80}")
    print(f"  {'ID':<5} {'chat_id':<20} {'群名':<20} {'类型':<12} {'状态':<8} {'分配账号'}")
    print(f"  {'-'*3:<5} {'-'*18:<20} {'-'*16:<20} {'-'*10:<12} {'-'*6:<8} {'-'*15}")
    for row in rows:
        db_id, chat_id, title, chat_type, is_active, acc_phone = row
        status = "✅ 启用" if is_active else "⏸  禁用"
        print(f"  {db_id:<5} {chat_id:<20} {title:<20} {chat_type:<12} {status:<8} {acc_phone or '-'}")
    print()


async def action_disable() -> None:
    """禁用一个监控群组（保留记录，停止监听）。"""
    rows = await _fetch_monitored_chats()
    active = [(r[0], r[1], r[2]) for r in rows if r[4]]  # (db_id, chat_id, title) where active
    if not active:
        print("\n📋 没有启用中的群组")
        return

    print(f"\n  启用中的群组:")
    for idx, (db_id, chat_id, title) in enumerate(active, 1):
        print(f"  [{idx}] {title} (chat_id={chat_id})")

    choice = input(f"  选择要禁用的群组 [1-{len(active)}]，输入 0 取消: ").strip()
    if choice == "0" or not choice:
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(active):
        print("❌ 无效选择")
        return

    db_id, chat_id, title = active[int(choice) - 1]
    await _set_active(db_id, False)
    await _invalidate_redis_cache()
    print(f"  ⏸  已禁用: {title} (chat_id={chat_id})")
    print(f"  服务将在下一刷新周期（≤5分钟）停止监听该群组")


async def action_enable() -> None:
    """重新启用一个已禁用的群组。"""
    rows = await _fetch_monitored_chats()
    inactive = [(r[0], r[1], r[2]) for r in rows if not r[4]]  # (db_id, chat_id, title) where inactive
    if not inactive:
        print("\n📋 没有已禁用的群组")
        return

    print(f"\n  已禁用的群组:")
    for idx, (db_id, chat_id, title) in enumerate(inactive, 1):
        print(f"  [{idx}] {title} (chat_id={chat_id})")

    choice = input(f"  选择要启用的群组 [1-{len(inactive)}]，输入 0 取消: ").strip()
    if choice == "0" or not choice:
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(inactive):
        print("❌ 无效选择")
        return

    db_id, chat_id, title = inactive[int(choice) - 1]
    await _set_active(db_id, True)
    await _invalidate_redis_cache()
    print(f"  ✅ 已启用: {title} (chat_id={chat_id})")
    print(f"  服务将在下一刷新周期（≤5分钟）开始监听该群组")


async def action_delete() -> None:
    """物理删除一个群组记录。"""
    rows = await _fetch_monitored_chats()
    if not rows:
        print("\n📋 暂无配置任何监控群组")
        return

    print(f"\n  所有群组:")
    items = []
    for row in rows:
        db_id, chat_id, title, _, is_active, _ = row
        status = "启用" if is_active else "禁用"
        items.append((db_id, chat_id, title, status))
        print(f"  [{len(items)}] [{status}] {title} (chat_id={chat_id})")

    choice = input(f"  选择要删除的群组 [1-{len(items)}]，输入 0 取消: ").strip()
    if choice == "0" or not choice:
        return
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(items):
        print("❌ 无效选择")
        return

    db_id, chat_id, title, _ = items[int(choice) - 1]
    confirm = input(f"  ⚠️  确认删除 {title} (chat_id={chat_id})？[y/N]: ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    await _delete_chat(db_id)
    await _invalidate_redis_cache()
    print(f"  🗑️  已删除: {title} (chat_id={chat_id})")


# ==================== 主菜单 ====================

async def main_menu() -> None:
    """主菜单循环。"""
    # 初始化数据库连接
    await _get_pool()

    while True:
        print(f"\n{'='*50}")
        print("  TGMonitor — 监控群组管理")
        print(f"{'='*50}")
        print("  [1] 查看当前监控群组")
        print("  [2] 添加新群组")
        print("  [3] 禁用群组（停止监听）")
        print("  [4] 启用群组（恢复监听）")
        print("  [5] 删除群组（物理删除）")
        print("  [0] 退出")
        print()

        choice = input("  请选择 [0-5]: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            await action_list()
        elif choice == "2":
            await action_add()
        elif choice == "3":
            await action_disable()
        elif choice == "4":
            await action_enable()
        elif choice == "5":
            await action_delete()
        else:
            print("  ❌ 无效选择")

    await _close_all()
    print("\n👋 再见")


if __name__ == "__main__":
    asyncio.run(main_menu())
