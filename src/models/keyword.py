# TGMonitor/src/models/keyword.py
"""
关键词实体
对应数据库表: tgm_keyword
参照 bot/src/types/product.ts 的 Product class 定义模式。

使用方式：
    from models.keyword import Keyword
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Keyword(BaseModel):
    """
    关键词实体
    对应数据库表: tgm_keyword
    """

    id: Optional[int] = None

    word: str                             # 关键词文本
    category: str                         # 分类: brand / product / risk / affiliate / competitor / payment
    match_type: str = "exact"             # 匹配方式: exact(精确) / regex(正则) / fuzzy(模糊)
    priority: int = 0                     # 优先级（数字越大越高）
    is_active: bool = True                # 是否启用

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True

    @staticmethod
    def from_db_row(row: Dict[str, Any]) -> Keyword:
        """
        从数据库行构建 Keyword 实例。

        Args:
            row: 数据库查询返回的字典

        Returns:
            Keyword 实例
        """
        return Keyword(
            id=row.get("id"),
            word=row["word"],
            category=row["category"],
            match_type=row.get("match_type", "exact"),
            priority=row.get("priority", 0),
            is_active=bool(row.get("is_active", True)),
            created_at=row.get("created_at", datetime.now()),
            updated_at=row.get("updated_at", datetime.now()),
        )
