# TGMonitor/src/models/monitored_chat.py
"""
被监听群组实体
对应数据库表: tgm_monitored_chat
参照 bot/src/types/product.ts 的 Product class 定义模式。

使用方式：
    from models.monitored_chat import MonitoredChat
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MonitoredChat(BaseModel):
    """
    被监听群组实体
    对应数据库表: tgm_monitored_chat
    """

    id: Optional[int] = None

    chat_id: int                          # Telegram 群组 ID
    chat_title: str                       # 群组名称
    chat_username: Optional[str] = None   # 群组 @用户名（如有）
    chat_type: str = "group"              # 类型: group / supergroup / channel

    # 分配给哪个监听账号
    assigned_account_phone: Optional[str] = None  # 分配的监听账号手机号

    is_active: bool = True                # 是否启用监听
    joined_at: Optional[datetime] = None  # 加入时间
    note: Optional[str] = None            # 备注

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True

    @staticmethod
    def from_db_row(row: Dict[str, Any]) -> MonitoredChat:
        """
        从数据库行构建 MonitoredChat 实例。

        Args:
            row: 数据库查询返回的字典

        Returns:
            MonitoredChat 实例
        """
        return MonitoredChat(
            id=row.get("id"),
            chat_id=row["chat_id"],
            chat_title=row["chat_title"],
            chat_username=row.get("chat_username"),
            chat_type=row.get("chat_type", "group"),
            assigned_account_phone=row.get("assigned_account_phone"),
            is_active=bool(row.get("is_active", True)),
            joined_at=row.get("joined_at"),
            note=row.get("note"),
            created_at=row.get("created_at", datetime.now()),
            updated_at=row.get("updated_at", datetime.now()),
        )
