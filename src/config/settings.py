# TGMonitor/src/config/settings.py
"""
全局配置模块
从 .env 文件加载所有配置项，提供统一的 settings 对象供全局访问。
参照 bot 项目的配置管理模式。

使用方式：
    from config.settings import settings
    print(settings.DB_HOST)
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv


# 项目根目录：TGMonitor/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 加载 .env 文件
_env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings:
    """
    全局配置对象
    所有配置项从环境变量读取，禁止在代码中直接使用 os.environ。
    """

    # ==================== 运行环境 ====================
    NODE_ENV: str = os.getenv("NODE_ENV", "development")

    @property
    def is_production(self) -> bool:
        return self.NODE_ENV == "production"

    # ==================== MySQL 配置 ====================
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "hello")

    # ==================== Redis 配置 ====================
    USE_REDIS: bool = os.getenv("USE_REDIS", "true").lower() == "true"
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    REDIS_DB: int = int(os.getenv("REDIS_DB", "1"))

    @property
    def redis_host(self) -> str:
        """从 REDIS_URL 解析主机名"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.REDIS_URL)
            return parsed.hostname or "localhost"
        except Exception:
            return "localhost"

    @property
    def redis_port(self) -> int:
        """从 REDIS_URL 解析端口"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.REDIS_URL)
            return parsed.port or 6379
        except Exception:
            return 6379

    @property
    def redis_password(self) -> str | None:
        """从 REDIS_URL 解析密码"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.REDIS_URL)
            return parsed.password
        except Exception:
            return None

    # ==================== 日志配置 ====================
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")
    LOG_DIR: str = os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs"))

    # ==================== 监听配置 ====================
    KEYWORD_RELOAD_INTERVAL: int = int(os.getenv("KEYWORD_RELOAD_INTERVAL", "300"))
    DEDUP_TTL: int = int(os.getenv("DEDUP_TTL", "604800"))
    ENTITY_CACHE_TTL: int = int(os.getenv("ENTITY_CACHE_TTL", "86400"))

    # ==================== 告警配置 ====================
    ALERT_ENABLED: bool = os.getenv("ALERT_ENABLED", "false").lower() == "true"
    ALERT_BOT_TOKEN: str = os.getenv("ALERT_BOT_TOKEN", "")
    ALERT_CHAT_ID: str = os.getenv("ALERT_CHAT_ID", "")

    # ==================== 路径配置 ====================
    @property
    def sessions_dir(self) -> Path:
        """Telethon session 文件目录"""
        return PROJECT_ROOT / "sessions"

    @property
    def logs_dir(self) -> Path:
        """日志目录"""
        return Path(self.LOG_DIR)

    # ==================== Telegram 账号配置 ====================

    def get_accounts(self) -> list[dict]:
        """
        从 .env 解析所有 TG_ACCOUNT_N_ 前缀的账号配置。

        支持多账号，编号从 1 开始递增：
            TG_ACCOUNT_1_PHONE, TG_ACCOUNT_1_API_ID, ...
            TG_ACCOUNT_2_PHONE, TG_ACCOUNT_2_API_ID, ...

        Returns:
            账号字典列表，每项包含 phone / api_id / api_hash / session_name / display_name
        """
        accounts: list[dict] = []
        i = 1
        while True:
            phone = os.getenv(f"TG_ACCOUNT_{i}_PHONE", "").strip()
            if not phone:
                break
            api_id_str = os.getenv(f"TG_ACCOUNT_{i}_API_ID", "0").strip()
            api_hash = os.getenv(f"TG_ACCOUNT_{i}_API_HASH", "").strip()
            session_name = os.getenv(f"TG_ACCOUNT_{i}_SESSION_NAME", f"account_{i}").strip()
            display_name = os.getenv(f"TG_ACCOUNT_{i}_DISPLAY_NAME", f"Account {i}").strip()

            if not api_id_str.isdigit() or not api_hash:
                i += 1
                continue

            accounts.append({
                "phone": phone,
                "api_id": int(api_id_str),
                "api_hash": api_hash,
                "session_name": session_name,
                "display_name": display_name,
            })
            i += 1
        return accounts

    def get_monitor_chats(self) -> list[dict]:
        """
        从 .env 解析 TG_MONITOR_CHATS 配置。

        格式: chat_id:群名:类型[:账号手机号],chat_id:群名:类型[:账号手机号],...
        类型可选（默认 supergroup），账号手机号可选。

        Returns:
            群组字典列表，每项包含 chat_id / chat_title / chat_type / assigned_phone(可选)
        """
        raw = os.getenv("TG_MONITOR_CHATS", "").strip()
        if not raw:
            return []
        chats: list[dict] = []
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            parts = item.split(":")
            if len(parts) < 2:
                continue
            try:
                chat_id = int(parts[0].strip())
            except ValueError:
                continue
            chat_title = parts[1].strip()
            chat_type = parts[2].strip() if len(parts) >= 3 else "supergroup"
            assigned_phone = parts[3].strip() if len(parts) >= 4 else None
            chat_dict = {
                "chat_id": chat_id,
                "chat_title": chat_title,
                "chat_type": chat_type,
            }
            if assigned_phone:
                chat_dict["assigned_phone"] = assigned_phone
            chats.append(chat_dict)
        return chats


# 全局单例
settings = Settings()
