# TGMonitor/src/models/account.py
"""
监听账号实体
对应数据库表: tgm_account
参照 bot/src/types/product.ts 的 Product class 定义模式。

使用方式：
    from models.account import MonitorAccount
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MonitorAccount(BaseModel):
    """
    监听账号实体
    对应数据库表: tgm_account
    """

    id: Optional[int] = None

    phone: str                            # 手机号（唯一标识）
    api_id: int                           # Telegram API ID
    api_hash: str                         # Telegram API Hash
    session_name: str                     # Session 文件名（不含路径和扩展名）
    display_name: Optional[str] = None    # 备注名称

    is_active: bool = True                # 是否启用
    status: str = "offline"               # 状态: online / offline / banned / flood_wait
    last_connected_at: Optional[datetime] = None  # 最后连接时间
    last_error: Optional[str] = None      # 最近一次错误信息

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True

    @staticmethod
    def from_db_row(row: Dict[str, Any]) -> MonitorAccount:
        """
        从数据库行构建 MonitorAccount 实例。

        Args:
            row: 数据库查询返回的字典

        Returns:
            MonitorAccount 实例
        """
        return MonitorAccount(
            id=row.get("id"),
            phone=row["phone"],
            api_id=row["api_id"],
            api_hash=row["api_hash"],
            session_name=row["session_name"],
            display_name=row.get("display_name"),
            is_active=bool(row.get("is_active", True)),
            status=row.get("status", "offline"),
            last_connected_at=row.get("last_connected_at"),
            last_error=row.get("last_error"),
            created_at=row.get("created_at", datetime.now()),
            updated_at=row.get("updated_at", datetime.now()),
        )
