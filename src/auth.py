#!/usr/bin/env python3
# TGMonitor/src/auth.py
"""
Telegram 账号首次登录认证脚本
生成 Telethon session 文件，并将账号信息写入 tgm_account 表。

流程（参照技术规划 §9.3）：
1. 输入手机号
2. Telethon 发送验证码到手机
3. 输入验证码
4. (可能) 输入两步验证密码
5. 认证成功，生成 session 文件保存到 sessions/ 目录
6. 将账号信息写入 tgm_account 表

后续启动直接使用 session 文件，无需重复登录。

使用方式：
    cd TGMonitor
    python3 src/auth.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from telethon import TelegramClient
from telethon.errors import (
    AuthRestartError,
    SessionPasswordNeededError,
)

from config.settings import settings
from config.database import close_pool
from models.account import MonitorAccount
from repositories.account_repository import account_repository
from utils.logger import logger


async def authenticate() -> None:
    """
    交互式认证流程：
    从 .env 读取 API 凭证 → 选择账号 → 输入验证码 → (两步验证) → 生成 session → 写入数据库。
    """
    print("\n" + "=" * 60)
    print("  TGMonitor — Telegram 账号认证")
    print("=" * 60)

    # 1. 从 .env 读取账号配置
    accounts = settings.get_accounts()
    if not accounts:
        print("❌ 未在 .env 中找到账号配置")
        print("   请先在 .env 中配置 TG_ACCOUNT_1_PHONE / TG_ACCOUNT_1_API_ID / TG_ACCOUNT_1_API_HASH")
        return

    # 2. 选择要认证的账号
    if len(accounts) == 1:
        selected = accounts[0]
        print(f"\n📋 使用 .env 中的账号配置:")
    else:
        print("\n📋 在 .env 中找到以下账号:")
        for idx, acc in enumerate(accounts, 1):
            print(f"  [{idx}] {acc['phone']} ({acc['display_name']})")
        choice = input(f"\n请选择要认证的账号 [1-{len(accounts)}]: ").strip()
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(accounts):
            print("❌ 无效选择")
            return
        selected = accounts[int(choice) - 1]

    phone = selected["phone"]
    api_id = selected["api_id"]
    api_hash = selected["api_hash"]
    session_name = selected["session_name"]
    display_name = selected["display_name"]

    print(f"   手机号: {phone}")
    print(f"   API ID: {api_id}")
    print(f"   Session: {session_name}")
    print(f"   备注: {display_name}")

    # 确保 sessions 目录存在
    sessions_dir = settings.sessions_dir
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_path = str(sessions_dir / session_name)

    print(f"\n📂 Session 文件将保存到: {session_path}.session")

    # 4. 创建 Telethon 客户端并认证
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()

        if await client.is_user_authorized():
            print("✅ 已有有效 session，无需重新认证")
        else:
            # 发送验证码（带重试，处理 AuthRestartError）
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    print(f"\n📲 正在向 {phone} 发送验证码...")
                    await client.send_code_request(phone)
                    break
                except AuthRestartError:
                    if attempt < max_retries - 1:
                        print(f"⚠️ Telegram 要求重启认证流程，正在重试 ({attempt + 2}/{max_retries})...")
                        await asyncio.sleep(2)
                    else:
                        print("❌ 多次重试仍失败，请稍后再试")
                        return

            code = input("请输入收到的验证码: ").strip()

            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                # 两步验证
                print("\n🔐 此账号已开启两步验证（2FA）")
                print("   请输入你在 Telegram Settings → Privacy → Two-Step Verification 设置的密码")
                print("   （注意：不是刚才的验证码，是你自己设置的密码）")
                password = input("\n请输入两步验证密码: ").strip()
                await client.sign_in(password=password)

            print("✅ 认证成功！")

        # 5. 获取当前用户信息
        me = await client.get_me()
        print(f"👤 已认证账号: {me.first_name} (@{me.username or 'N/A'})")

        # 6. 写入数据库
        # 先检查是否已存在
        existing = await account_repository.get_by_phone(phone)
        if existing:
            print(f"📋 账号 {phone} 已存在于数据库中 (id={existing.id})，跳过插入")
        else:
            account = MonitorAccount(
                phone=phone,
                api_id=api_id,
                api_hash=api_hash,
                session_name=session_name,
                display_name=display_name,
                is_active=True,
                status="offline",
            )
            acc_id = await account_repository.insert(account)
            print(f"💾 账号信息已写入数据库 (id={acc_id})")

        # 7. 设置 session 文件权限
        session_file = Path(f"{session_path}.session")
        if session_file.exists():
            session_file.chmod(0o600)
            print(f"🔒 Session 文件权限已设为 600")

        print("\n" + "=" * 60)
        print("  ✅ 认证完成！")
        print(f"  Session 文件: {session_path}.session")
        print(f"  手机号: {phone}")
        print("  下次启动 TGMonitor 将自动使用此 session 登录")
        print("=" * 60 + "\n")

    except Exception as e:
        logger.error("❌ 认证失败: {}", e)
        print(f"\n❌ 认证失败: {e}")
        raise
    finally:
        await client.disconnect()
        await close_pool()


def main() -> None:
    """入口"""
    asyncio.run(authenticate())


if __name__ == "__main__":
    main()
