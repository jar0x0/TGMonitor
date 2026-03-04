#!/usr/bin/env python3
# TGMonitor/src/scripts/list_chats.py
"""
列出已加入的所有群组/频道及其 chat_id。
用于获取 TG_MONITOR_CHATS 配置所需的 chat_id。

使用方式：
    cd TGMonitor
    /Users/james/git/relinx/.venv/bin/python3 src/scripts/list_chats.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient

from config.settings import settings


async def list_chats() -> None:
    """列出所有已加入的群组和频道。"""
    accounts = settings.get_accounts()
    if not accounts:
        print("❌ 未在 .env 中找到账号配置")
        return

    # 选择账号
    if len(accounts) == 1:
        selected = accounts[0]
    else:
        print("📋 可用账号:")
        for idx, acc in enumerate(accounts, 1):
            print(f"  [{idx}] {acc['phone']} ({acc['display_name']})")
        choice = input(f"选择账号 [1-{len(accounts)}]: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(accounts):
            print("❌ 无效选择")
            return
        selected = accounts[int(choice) - 1]

    phone = selected["phone"]
    api_id = selected["api_id"]
    api_hash = selected["api_hash"]
    session_name = selected["session_name"]
    original_session = str(settings.sessions_dir / session_name) + ".session"

    # 复制 session 文件到临时目录，避免与运行中的服务争锁
    tmp_dir = tempfile.mkdtemp(prefix="tgm_")
    tmp_session = str(Path(tmp_dir) / session_name)
    shutil.copy2(original_session, tmp_session + ".session")

    print(f"\n🔗 使用账号 {phone} 连接 Telegram...")

    client = TelegramClient(tmp_session, api_id, api_hash)

    try:
        await client.connect()

        if not await client.is_user_authorized():
            print("❌ 账号未认证，请先运行 python3 src/auth.py")
            await client.disconnect()
            return

        me = await client.get_me()
        print(f"👤 已连接: {me.first_name} (@{me.username or 'N/A'})")

        # 列出所有对话
        groups = []
        channels = []
        print("\n📂 正在加载对话列表...\n")

        async for dialog in client.iter_dialogs():
            if dialog.is_group:
                chat_type = "supergroup" if getattr(dialog.entity, "megagroup", False) else "group"
                groups.append({
                    "chat_id": dialog.id,
                    "title": dialog.title,
                    "type": chat_type,
                    "username": getattr(dialog.entity, "username", None),
                    "members": getattr(dialog.entity, "participants_count", "?"),
                })
            elif dialog.is_channel:
                channels.append({
                    "chat_id": dialog.id,
                    "title": dialog.title,
                    "type": "channel",
                    "username": getattr(dialog.entity, "username", None),
                    "members": getattr(dialog.entity, "participants_count", "?"),
                })

        await client.disconnect()

    finally:
        # 清理临时 session 文件
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 打印群组
    if groups:
        print(f"{'='*80}")
        print(f"  群组 ({len(groups)} 个)")
        print(f"{'='*80}")
        print(f"  {'chat_id':<20} {'类型':<12} {'成员':<8} {'名称'}")
        print(f"  {'-'*20} {'-'*12} {'-'*8} {'-'*30}")
        for g in groups:
            print(f"  {g['chat_id']:<20} {g['type']:<12} {str(g['members']):<8} {g['title']}")
            if g["username"]:
                print(f"  {'':20} @{g['username']}")

    # 打印频道
    if channels:
        print(f"\n{'='*80}")
        print(f"  频道 ({len(channels)} 个)")
        print(f"{'='*80}")
        print(f"  {'chat_id':<20} {'类型':<12} {'成员':<8} {'名称'}")
        print(f"  {'-'*20} {'-'*12} {'-'*8} {'-'*30}")
        for c in channels:
            print(f"  {c['chat_id']:<20} {c['type']:<12} {str(c['members']):<8} {c['title']}")
            if c["username"]:
                print(f"  {'':20} @{c['username']}")

    # 打印可直接复制的 .env 格式
    all_chats = groups + channels
    if all_chats:
        print(f"\n{'='*80}")
        print("  📋 复制以下内容到 .env 的 TG_MONITOR_CHATS=")
        print(f"{'='*80}")
        env_parts = []
        for c in all_chats:
            env_parts.append(f"{c['chat_id']}:{c['title']}:{c['type']}")
        print(f"\nTG_MONITOR_CHATS={','.join(env_parts)}")

    if not groups and not channels:
        print("⚠️ 未找到任何群组或频道。请先用此账号加入目标群组。")

    print(f"\n📊 总计: {len(groups)} 个群组, {len(channels)} 个频道")


def main() -> None:
    asyncio.run(list_chats())


if __name__ == "__main__":
    main()
