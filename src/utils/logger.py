# TGMonitor/src/utils/logger.py
"""
日志配置模块
使用 loguru 实现分级日志系统，参照 bot 项目 bot/src/utils/logger.ts 的分级模式。

日志文件规划：
- logs/app.log      : 全量日志 (DEBUG+)
- logs/error.log    : 仅错误日志 (ERROR+)
- logs/message.log  : 消息监听专用日志 (INFO，消息相关)
- logs/client.log   : Telethon 客户端连接/断线日志 (INFO，客户端相关)

轮转配置：
- 单文件最大 10MB
- 保留 5 个备份
- 启用 gzip 压缩

日志格式：
  [2026-03-03 14:30:25.123] [INFO] [module_name] 消息内容

使用方式：
    from utils.logger import logger

    logger.info("✅ Account {} connected", phone)
    logger.error("❌ MySQL insert failed: {}", error)
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _loguru_logger

from config.settings import settings


def _setup_logger() -> "loguru.Logger":
    """
    配置 loguru 日志系统

    Returns:
        配置完成的 loguru logger 实例
    """
    # 移除 loguru 默认的 stderr handler
    _loguru_logger.remove()

    # 日志目录
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 统一日志格式
    log_format = (
        "[{time:YYYY-MM-DD HH:mm:ss.SSS}] [{level}] [{module}] {message}"
    )

    # ======================== 控制台输出 ========================
    # 开发环境：彩色输出；生产环境：关闭控制台
    if not settings.is_production:
        _loguru_logger.add(
            sys.stderr,
            format=log_format,
            level=settings.LOG_LEVEL,
            colorize=True,
        )

    # ======================== app.log（全量日志） ========================
    _loguru_logger.add(
        str(log_dir / "app.log"),
        format=log_format,
        level="DEBUG",
        rotation="10 MB",
        retention=5,
        compression="gz",
        encoding="utf-8",
        enqueue=True,  # 线程安全：异步写入
    )

    # ======================== error.log（仅错误） ========================
    _loguru_logger.add(
        str(log_dir / "error.log"),
        format=log_format,
        level="ERROR",
        rotation="10 MB",
        retention=5,
        compression="gz",
        encoding="utf-8",
        enqueue=True,
    )

    # ======================== message.log（消息监听专用） ========================
    _loguru_logger.add(
        str(log_dir / "message.log"),
        format=log_format,
        level="INFO",
        rotation="10 MB",
        retention=5,
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: record["extra"].get("log_type") == "message",
    )

    # ======================== client.log（客户端连接/断线） ========================
    _loguru_logger.add(
        str(log_dir / "client.log"),
        format=log_format,
        level="INFO",
        rotation="10 MB",
        retention=5,
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: record["extra"].get("log_type") == "client",
    )

    return _loguru_logger


# 初始化并导出全局 logger
logger = _setup_logger()

# 创建消息专用日志绑定器（便于 handler 层使用）
message_logger = logger.bind(log_type="message")

# 创建客户端专用日志绑定器（便于 core 层使用）
client_logger = logger.bind(log_type="client")
