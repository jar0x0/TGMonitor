# TGMonitor/src/filters/keyword_filter.py
"""
关键词匹配引擎
负责：
1. 接收消息文本，遍历关键词列表进行匹配
2. 支持三种匹配方式：exact（精确）、regex（正则）、fuzzy（包含）
3. 返回匹配结果（命中关键词列表 + 最高优先级分类）

匹配策略：
- exact: word boundary + case-insensitive（如 `relinx` 匹配 "I like relinx" 但不匹配 "relinxyz"）
- regex: re.search(pattern, text, re.IGNORECASE)
- fuzzy: keyword.lower() in text.lower()（包含匹配）

使用方式：
    from filters.keyword_filter import keyword_filter

    result = await keyword_filter.match("I love relinx gift cards")
    if result:
        print(result.matched_keywords)  # ["relinx", "gift card"]
        print(result.category)          # "brand"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from models.keyword import Keyword
from services.keyword_service import keyword_service
from utils.logger import logger


@dataclass
class FilterResult:
    """
    关键词匹配结果

    Attributes:
        matched_keywords: 命中的关键词文本列表
        category: 最高优先级关键词的分类 (brand/risk/product/payment/affiliate/competitor)
        top_priority: 命中关键词中的最高优先级值
    """

    matched_keywords: List[str] = field(default_factory=list)
    category: str = ""
    top_priority: int = 0


class KeywordFilter:
    """
    关键词匹配引擎
    从 KeywordService 获取关键词列表，对消息文本进行匹配。

    依赖方向：filters/ → services/（读取关键词）
    """

    # 缓存已编译的正则表达式（避免重复编译）
    _regex_cache: dict[str, re.Pattern[str]] = {}

    def _preprocess_text(self, text: str) -> str:
        """
        文本预处理：小写化 + 去除多余空格。

        Args:
            text: 原始消息文本

        Returns:
            预处理后的文本
        """
        return re.sub(r"\s+", " ", text.strip().lower())

    def _exact_match(self, text: str, keyword_word: str) -> bool:
        """
        精确匹配（word boundary + case-insensitive）。

        `relinx` 可匹配 "I like relinx" 但不匹配 "relinxyz"。

        Args:
            text: 预处理后的消息文本（已小写）
            keyword_word: 关键词文本

        Returns:
            bool: 是否匹配
        """
        pattern = r"\b" + re.escape(keyword_word.lower()) + r"\b"
        return bool(re.search(pattern, text))

    def _regex_match(self, text: str, pattern_str: str) -> bool:
        """
        正则表达式匹配（case-insensitive）。

        Args:
            text: 原始消息文本（未小写，由 regex 自身处理大小写）
            pattern_str: 正则表达式字符串

        Returns:
            bool: 是否匹配
        """
        try:
            # 使用缓存的编译后正则
            if pattern_str not in self._regex_cache:
                self._regex_cache[pattern_str] = re.compile(pattern_str, re.IGNORECASE)
            compiled = self._regex_cache[pattern_str]
            return bool(compiled.search(text))
        except re.error as e:
            logger.warning("⚠️ Invalid regex pattern '{}': {}", pattern_str, e)
            return False

    def _fuzzy_match(self, text: str, keyword_word: str) -> bool:
        """
        模糊匹配（包含匹配，case-insensitive）。

        `gift card` 可匹配 "cheap Gift Cards here"。

        Args:
            text: 消息文本（函数内部会做小写化）
            keyword_word: 关键词文本

        Returns:
            bool: 是否匹配
        """
        return keyword_word.lower() in text.lower()

    def _match_keyword(self, text: str, preprocessed_text: str, keyword: Keyword) -> bool:
        """
        根据关键词的 match_type 选择匹配策略。

        Args:
            text: 原始消息文本
            preprocessed_text: 预处理后的消息文本（已小写）
            keyword: Keyword 实体

        Returns:
            bool: 是否匹配
        """
        if keyword.match_type == "exact":
            return self._exact_match(preprocessed_text, keyword.word)
        elif keyword.match_type == "regex":
            return self._regex_match(text, keyword.word)
        elif keyword.match_type == "fuzzy":
            return self._fuzzy_match(preprocessed_text, keyword.word)
        else:
            logger.warning("⚠️ Unknown match_type '{}' for keyword '{}'", keyword.match_type, keyword.word)
            return False

    async def match(self, text: str) -> Optional[FilterResult]:
        """
        对消息文本进行关键词匹配。

        遍历所有启用的关键词，返回命中结果。
        如果无任何命中，返回 None。

        Args:
            text: 消息文本

        Returns:
            FilterResult: 匹配结果（含命中关键词列表和最高优先级分类），或 None
        """
        if not text or not text.strip():
            return None

        # 从 KeywordService 获取所有启用的关键词
        keywords = await keyword_service.get_all_active_keywords()
        if not keywords:
            logger.debug("⚠️ No active keywords loaded, skipping match")
            return None

        preprocessed = self._preprocess_text(text)

        matched_keywords: List[str] = []
        top_priority: int = -1
        top_category: str = ""

        for kw in keywords:
            if self._match_keyword(text, preprocessed, kw):
                matched_keywords.append(kw.word)
                # 记录最高优先级的分类
                if kw.priority > top_priority:
                    top_priority = kw.priority
                    top_category = kw.category

        if not matched_keywords:
            return None

        result = FilterResult(
            matched_keywords=matched_keywords,
            category=top_category,
            top_priority=top_priority,
        )

        logger.debug(
            "🔍 Keyword match: {} keywords hit, category='{}', keywords={}",
            len(matched_keywords),
            top_category,
            matched_keywords,
        )

        return result


# 单例实例
keyword_filter = KeywordFilter()
