# TGMonitor/src/models/message.py
"""
监听消息实体
对应数据库表: tgm_message
参照 bot/src/types/product.ts 的 Product class 定义模式。

使用方式：
    from models.message import MonitoredMessage
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MonitoredMessage(BaseModel):
    """
    监听消息实体
    对应数据库表: tgm_message
    """

    # 数据库主键
    id: Optional[int] = None

    # Telegram 原始信息
    telegram_message_id: int              # Telegram 消息 ID
    chat_id: int                          # 群组 ID
    chat_title: str                       # 群组名称
    sender_id: int                        # 发送者 Telegram ID
    sender_username: Optional[str] = None  # 发送者用户名 (@xxx)
    sender_display_name: Optional[str] = None  # 发送者显示名

    # 消息内容
    message_text: str                     # 消息文本内容
    message_type: str = "text"            # 消息类型: text / caption / reply
    reply_to_message_id: Optional[int] = None  # 回复的消息 ID（如有）

    # 关键词匹配结果
    matched_keywords: List[str] = Field(default_factory=list)  # 命中的关键词列表
    keyword_category: str = ""            # 最高优先级分类

    # 账号信息
    monitor_account_phone: str = ""       # 执行监听的账号手机号

    # 时间戳
    message_date: datetime = Field(default_factory=datetime.now)  # 消息原始发送时间
    created_at: datetime = Field(default_factory=datetime.now)    # 记录创建时间

    class Config:
        from_attributes = True  # 支持从 ORM/dict 创建

    @staticmethod
    def from_db_row(row: Dict[str, Any]) -> MonitoredMessage:
        """
        从数据库行（DictCursor 返回的 dict）构建 MonitoredMessage 实例。

        Args:
            row: 数据库查询返回的字典，字段名与表列名一致 (snake_case)

        Returns:
            MonitoredMessage 实例
        """
        # matched_keywords 在数据库中是 JSON 类型
        matched_keywords = row.get("matched_keywords", "[]")
        if isinstance(matched_keywords, str):
            matched_keywords = json.loads(matched_keywords)

        return MonitoredMessage(
            id=row.get("id"),
            telegram_message_id=row["telegram_message_id"],
            chat_id=row["chat_id"],
            chat_title=row["chat_title"],
            sender_id=row["sender_id"],
            sender_username=row.get("sender_username"),
            sender_display_name=row.get("sender_display_name"),
            message_text=row["message_text"],
            message_type=row.get("message_type", "text"),
            reply_to_message_id=row.get("reply_to_message_id"),
            matched_keywords=matched_keywords,
            keyword_category=row["keyword_category"],
            monitor_account_phone=row["monitor_account_phone"],
            message_date=row["message_date"],
            created_at=row.get("created_at", datetime.now()),
        )

    def keywords_to_json(self) -> str:
        """将 matched_keywords 列表序列化为 JSON 字符串（用于 MySQL JSON 字段写入）"""
        return json.dumps(self.matched_keywords, ensure_ascii=False)
