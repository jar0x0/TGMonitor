#!/usr/bin/env python3
# TGMonitor/src/main.py
"""
TGMonitor 主入口
启动流程编排（参照技术规划 §9.1）：
1. 加载 .env 配置
2. 初始化日志系统 (loguru)
3. 初始化 MySQL 连接池 (database.py)
4. 初始化 Redis 客户端 (redis_client.py)
5. 同步 .env 账号/群组配置到 MySQL（不存在则插入，已存在跳过）
6. KeywordService.load_keywords() — 从 MySQL 加载关键词到 Redis
7. AccountService.load_accounts() — 从 MySQL 加载启用的监听账号
8. ClientManager.start_all() — 启动所有客户端 + 注册事件处理器
9. 阻塞运行直到中断

使用方式：
    cd TGMonitor
    python3 src/main.py
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import sys
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import settings
from utils.logger import logger

# PID 锁文件路径（防止多实例同时运行导致 session 文件 SQLite 锁冲突）
_PID_FILE = Path(__file__).resolve().parent.parent / "tgmonitor.pid"
_pid_fp = None  # 保持文件句柄，进程结束时自动释放


def _acquire_pid_lock() -> None:
    """
    获取 PID 文件排他锁。如果已有另一个 main.py 进程在运行，立即退出。
    利用 fcntl.flock 的特性：锁在进程退出（含 kill -9）时自动释放。
    """
    global _pid_fp
    # 用 r+ 打开（不截断），文件不存在时用 w 创建
    try:
        _pid_fp = open(_PID_FILE, "r+")
    except FileNotFoundError:
        _pid_fp = open(_PID_FILE, "w")
    try:
        fcntl.flock(_pid_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # 锁被占用 → 另一个实例正在运行
        _pid_fp.seek(0)
        other_pid = _pid_fp.read().strip() or "unknown"
        print(
            f"❌ Another TGMonitor instance is already running (PID {other_pid}).\n"
            f"   If the process is dead, delete {_PID_FILE} and retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    # 写入当前 PID
    _pid_fp.seek(0)
    _pid_fp.truncate(0)
    _pid_fp.write(str(os.getpid()))
    _pid_fp.flush()


async def startup() -> None:
    """
    系统启动流程编排。
    """
    logger.info("=" * 60)
    logger.info("🚀 TGMonitor Starting...")
    logger.info("   Environment: {}", settings.NODE_ENV)
    logger.info("   MySQL: {}:{}/{}", settings.DB_HOST, settings.DB_PORT, settings.DB_NAME)
    logger.info("   Redis: {} (db={})", settings.REDIS_URL, settings.REDIS_DB)
    logger.info("=" * 60)

    # 1. 初始化 MySQL 连接池（懒初始化，首次 get_pool 时创建）
    from config.database import get_pool
    pool = await get_pool()
    logger.info("✅ MySQL connection pool initialized")

    # 2. 初始化 Redis 客户端
    from config.redis_client import get_redis
    redis = await get_redis()
    if redis:
        logger.info("✅ Redis client initialized")
    else:
        logger.warning("⚠️ Redis disabled (USE_REDIS=false), running in MySQL-only mode")

    # 3. 同步 .env 中的账号和群组配置到 MySQL（不存在则插入）
    from services.account_service import account_service
    synced_accounts = await account_service.sync_from_env()
    if synced_accounts:
        logger.info("📥 Synced {} new account(s) from .env to DB", synced_accounts)

    from services.monitored_chat_service import monitored_chat_service
    synced_chats = await monitored_chat_service.sync_from_env()
    if synced_chats:
        logger.info("📥 Synced {} new chat(s) from .env to DB", synced_chats)

    # 4. 从 MySQL 加载关键词到 Redis
    from services.keyword_service import keyword_service
    await keyword_service.load_keywords()

    # 5. 从 MySQL 加载账号（由 ClientManager 内部调用，此处仅验证）
    accounts = await account_service.get_all_active_accounts()
    logger.info("📋 Found {} active account(s)", len(accounts))

    if not accounts:
        logger.error("❌ No active accounts found. Run auth.py to add an account first.")
        return

    # 6. 启动 ClientManager（创建客户端 + 注册事件 + 启动定时任务）
    from core.client_manager import client_manager
    await client_manager.start_all()

    logger.info("=" * 60)
    logger.info("✅ TGMonitor is running!")
    logger.info("   Clients: {}/{} connected", client_manager.connected_count, client_manager.total_count)
    logger.info("   Press Ctrl+C to stop")
    logger.info("=" * 60)

    # 7. 阻塞运行直到所有客户端断开
    await client_manager.run_until_disconnected()


async def shutdown() -> None:
    """
    优雅停止流程。
    """
    logger.info("🛑 TGMonitor shutting down...")

    from core.client_manager import client_manager
    await client_manager.stop_all()

    from config.redis_client import close_redis
    await close_redis()

    from config.database import close_pool
    await close_pool()

    logger.info("✅ TGMonitor stopped gracefully")


# 全局标志，防止 shutdown 被多次执行
_shutdown_done = False


async def _safe_shutdown() -> None:
    """确保 shutdown 只执行一次。"""
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    await shutdown()


def main() -> None:
    """
    主入口：设置信号处理 + 运行事件循环。
    """
    # 防止多实例：获取 PID 文件排他锁
    _acquire_pid_lock()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 用 asyncio.Event 通知主协程停止
    stop_event = asyncio.Event()

    # 信号处理（Ctrl+C / SIGTERM）—— 只设置 stop_event，不直接调用 shutdown
    def handle_signal(sig: int, frame) -> None:
        logger.info("📡 Received signal {}, initiating shutdown...", sig)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(startup())
    except KeyboardInterrupt:
        logger.info("📡 KeyboardInterrupt received")
    except Exception as e:
        logger.error("❌ Fatal error: {}", e)
        import traceback
        traceback.print_exc()
    finally:
        # 统一在 finally 中执行一次 shutdown
        loop.run_until_complete(_safe_shutdown())
        # 清理所有未完成的任务
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        # 释放 PID 锁并删除文件
        if _pid_fp:
            try:
                fcntl.flock(_pid_fp, fcntl.LOCK_UN)
                _pid_fp.close()
                _PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
