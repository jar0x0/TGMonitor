# TGMonitor/src/core/client_manager.py
"""
Telethon 多客户端管理器
负责：
1. 根据 tgm_account 配置创建多个 TelegramClient 实例
2. 管理连接 / 断线重连 / 状态上报
3. 为每个 Client 注册 MessageHandler
4. 启动关键词热加载定时任务

安全规则（来自 DEVELOPMENT_RULES.md §10.1）：
- 只读不写：监听进程只接收消息，严禁发送任何消息、回复、点赞
- 不加群：代码中严禁自动加入群组
- 不拉人：严禁邀请用户进群
- 限制 API 调用频率：get_entity() 等调用必须做 Redis 缓存

使用方式：
    from core.client_manager import client_manager

    await client_manager.start_all()
    await client_manager.stop_all()
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    AuthKeyUnregisteredError,
    UserDeactivatedBanError,
    SessionPasswordNeededError,
)

from config.settings import settings
from handlers.message_handler import (
    create_message_handler,
    reload_monitored_chat_ids,
    set_monitored_chat_ids,
)
from models.account import MonitorAccount
from services.account_service import account_service
from services.keyword_service import keyword_service
from services.monitored_chat_service import monitored_chat_service
from utils.logger import logger, client_logger


class ClientManager:
    """
    Telethon 多客户端管理器。

    为每个启用的 tgm_account 创建一个 TelegramClient，注册
    NewMessage 事件处理器，并管理连接生命周期和定时任务。
    """

    def __init__(self) -> None:
        # phone -> TelegramClient
        self._clients: Dict[str, TelegramClient] = {}
        # phone -> MonitorAccount
        self._accounts: Dict[str, MonitorAccount] = {}
        # 定时任务句柄
        self._tasks: List[asyncio.Task] = []  # type: ignore[type-arg]
        # 停止信号
        self._running: bool = False

    # ==================== 启动 / 停止 ====================

    async def start_all(self) -> None:
        """
        启动所有启用账号的客户端。

        流程：
        1. 加载被监听群组 ID → 注入 MessageHandler
        2. 加载活跃账号
        3. 为每个账号创建 TelegramClient + 连接 + 注册事件
        4. 启动定时任务（关键词热加载 + 群组刷新）
        """
        self._running = True

        # 1. 加载被监听群组 ID
        chat_ids = await monitored_chat_service.get_all_active_chat_ids()
        set_monitored_chat_ids(set(chat_ids))

        # 2. 加载活跃账号
        accounts = await account_service.get_all_active_accounts()
        if not accounts:
            logger.warning("⚠️ No active accounts found in database")
            return

        logger.info("🚀 Starting {} account client(s)...", len(accounts))

        # 3. 启动每个客户端
        for account in accounts:
            try:
                await self._start_client(account)
            except Exception as e:
                logger.error(
                    "❌ Failed to start client for phone={}: {}",
                    account.phone,
                    e,
                )
                await account_service.update_status(
                    account.phone, "offline", last_error=str(e)
                )

        # 4. 启动定时任务
        self._tasks.append(asyncio.create_task(self._keyword_reload_loop()))
        self._tasks.append(asyncio.create_task(self._chat_ids_reload_loop()))
        self._tasks.append(asyncio.create_task(self._health_check_loop()))

        client_count = len(self._clients)
        logger.info(
            "✅ ClientManager started: {}/{} clients online",
            client_count,
            len(accounts),
        )

    async def stop_all(self) -> None:
        """优雅停止所有客户端和定时任务。"""
        if not self._running:
            return
        self._running = False

        # 取消定时任务并等待它们真正结束
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # 断开所有客户端（用 list() 拷贝，避免迭代中字典被修改）
        for phone, client in list(self._clients.items()):
            try:
                await client.disconnect()
                await account_service.update_status(phone, "offline")
                client_logger.info("🔌 Client disconnected: phone={}", phone)
            except Exception as e:
                logger.warning("⚠️ Error disconnecting client phone={}: {}", phone, e)

        self._clients.clear()
        self._accounts.clear()
        logger.info("✅ ClientManager stopped: all clients disconnected")

    async def restart_client(self, phone: str) -> None:
        """
        重启指定账号的客户端。

        Args:
            phone: 手机号
        """
        # 先断开
        if phone in self._clients:
            try:
                await self._clients[phone].disconnect()
            except Exception:
                pass
            del self._clients[phone]

        # 重新启动
        account = self._accounts.get(phone)
        if account:
            await self._start_client(account)
            logger.info("🔄 Client restarted: phone={}", phone)

    # ==================== 内部方法 ====================

    async def _start_client(self, account: MonitorAccount) -> None:
        """
        为单个账号创建并启动 TelegramClient。

        Args:
            account: MonitorAccount 实体
        """
        # 确保 sessions 目录存在
        sessions_dir = settings.sessions_dir
        sessions_dir.mkdir(parents=True, exist_ok=True)

        session_path = str(sessions_dir / account.session_name)

        client = TelegramClient(
            session_path,
            account.api_id,
            account.api_hash,
            # 自动重连由 Telethon 内置处理
            auto_reconnect=True,
            connection_retries=5,
            retry_delay=5,
            # 断线重连后自动追回（get_difference）错过的消息
            catch_up=True,
            # 大群成员多，提高 Entity 缓存上限（默认 5000）
            entity_cache_limit=10000,
        )

        try:
            await client.connect()

            if not await client.is_user_authorized():
                logger.error(
                    "❌ Account phone={} not authorized. Run auth.py first.",
                    account.phone,
                )
                await account_service.update_status(
                    account.phone, "offline", last_error="Not authorized"
                )
                await client.disconnect()
                return

            # 注册 NewMessage 事件处理器
            handler = create_message_handler(account_phone=account.phone)
            client.add_event_handler(handler, events.NewMessage())

            self._clients[account.phone] = client
            self._accounts[account.phone] = account

            # 更新状态为 online
            await account_service.update_status(account.phone, "online")

            client_logger.info(
                "✅ Client connected: phone={}, session={}",
                account.phone,
                account.session_name,
            )

        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(
                "⚠️ FloodWait for phone={}: {}s",
                account.phone,
                wait_seconds,
            )
            await account_service.update_status(
                account.phone, "flood_wait", last_error=f"FloodWait: {wait_seconds}s"
            )
            await client.disconnect()

        except (AuthKeyUnregisteredError, UserDeactivatedBanError) as e:
            logger.error(
                "🚫 Account phone={} banned/deactivated: {}",
                account.phone,
                e,
            )
            await account_service.update_status(
                account.phone, "banned", last_error=str(e)
            )
            await client.disconnect()

        except Exception as e:
            logger.error(
                "❌ Failed to connect client phone={}: {}",
                account.phone,
                e,
            )
            await account_service.update_status(
                account.phone, "offline", last_error=str(e)
            )
            try:
                await client.disconnect()
            except Exception:
                pass

    # ==================== 定时任务 ====================

    async def _keyword_reload_loop(self) -> None:
        """关键词热加载定时任务（每 KEYWORD_RELOAD_INTERVAL 秒检查一次）。"""
        while self._running:
            try:
                await asyncio.sleep(settings.KEYWORD_RELOAD_INTERVAL)
                await keyword_service.reload_if_needed()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("❌ Keyword reload loop error: {}", e)
                await asyncio.sleep(60)

    async def _chat_ids_reload_loop(self) -> None:
        """被监听群组 ID 刷新定时任务（每 5 分钟）。"""
        while self._running:
            try:
                await asyncio.sleep(300)
                await reload_monitored_chat_ids()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("❌ Chat IDs reload loop error: {}", e)
                await asyncio.sleep(60)

    async def _health_check_loop(self) -> None:
        """健康检查定时任务（每 60 秒）。"""
        while self._running:
            try:
                await asyncio.sleep(60)
                for phone, client in list(self._clients.items()):
                    if not client.is_connected():
                        client_logger.warning(
                            "⚠️ Client disconnected detected: phone={}, attempting reconnect...",
                            phone,
                        )
                        try:
                            await client.connect()
                            if await client.is_user_authorized():
                                await account_service.update_status(phone, "online")
                                client_logger.info(
                                    "✅ Client reconnected: phone={}", phone
                                )
                            else:
                                await account_service.update_status(
                                    phone, "offline", last_error="Auth lost after reconnect"
                                )
                        except Exception as e:
                            logger.error(
                                "❌ Reconnect failed for phone={}: {}", phone, e
                            )
                            await account_service.update_status(
                                phone, "offline", last_error=str(e)
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("❌ Health check loop error: {}", e)
                await asyncio.sleep(60)

    # ==================== 属性 ====================

    @property
    def connected_count(self) -> int:
        """当前已连接的客户端数量。"""
        return sum(1 for c in self._clients.values() if c.is_connected())

    @property
    def total_count(self) -> int:
        """总客户端数量（含断线的）。"""
        return len(self._clients)

    async def run_until_disconnected(self) -> None:
        """
        阻塞运行，直到所有客户端断开。
        等同于 asyncio.gather 所有客户端的 run_until_disconnected。
        """
        if not self._clients:
            logger.warning("⚠️ No clients to run")
            return

        tasks = []
        for phone, client in self._clients.items():
            tasks.append(asyncio.create_task(
                self._run_client(phone, client)
            ))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_client(self, phone: str, client: TelegramClient) -> None:
        """保持单个客户端运行直到断开。"""
        try:
            client_logger.info("🏃 Client running: phone={}", phone)
            await client.run_until_disconnected()
        except Exception as e:
            logger.error("❌ Client phone={} run error: {}", phone, e)
        finally:
            await account_service.update_status(phone, "offline")
            client_logger.info("🔌 Client stopped: phone={}", phone)


# 单例实例
client_manager = ClientManager()
