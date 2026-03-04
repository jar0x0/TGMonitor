#!/usr/bin/env python3
# TGMonitor/src/scripts/init_db.py
"""
数据库初始化脚本
创建 TGMonitor 所需的 4 张表并插入初始关键词种子数据。

使用方式：
    cd TGMonitor
    python3 src/scripts/init_db.py

注意：
- 使用 IF NOT EXISTS，可重复执行，不会覆盖现有数据
- 使用 INSERT IGNORE 避免种子数据重复插入
- 所有表名使用 tgm_ 前缀，与 bot 项目的表隔离
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将 src/ 加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiomysql

from config.settings import settings
from utils.logger import logger


# ==================== DDL: 4 张表 ====================

SQL_CREATE_TGM_MESSAGE = """
CREATE TABLE IF NOT EXISTS tgm_message (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    telegram_message_id     BIGINT NOT NULL                          COMMENT 'Telegram 消息 ID',
    chat_id                 BIGINT NOT NULL                          COMMENT '群组 ID',
    chat_title              VARCHAR(255) NOT NULL                    COMMENT '群组名称',
    sender_id               BIGINT NOT NULL                          COMMENT '发送者 Telegram ID',
    sender_username         VARCHAR(255) DEFAULT NULL                COMMENT '发送者用户名',
    sender_display_name     VARCHAR(255) DEFAULT NULL                COMMENT '发送者显示名',
    message_text            TEXT NOT NULL                            COMMENT '消息文本内容',
    message_type            VARCHAR(20) DEFAULT 'text'               COMMENT '消息类型: text/caption/reply',
    reply_to_message_id     BIGINT DEFAULT NULL                      COMMENT '回复的消息 ID',
    matched_keywords        JSON NOT NULL                            COMMENT '命中的关键词列表',
    keyword_category        VARCHAR(50) NOT NULL                     COMMENT '最高优先级分类',
    monitor_account_phone   VARCHAR(20) NOT NULL                     COMMENT '执行监听的账号',
    message_date            DATETIME NOT NULL                        COMMENT '消息原始发送时间',
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP       COMMENT '记录创建时间',

    UNIQUE KEY uk_chat_msg (chat_id, telegram_message_id),
    INDEX idx_chat_id (chat_id),
    INDEX idx_sender_id (sender_id),
    INDEX idx_keyword_category (keyword_category),
    INDEX idx_message_date (message_date),
    INDEX idx_monitor_account (monitor_account_phone),
    INDEX idx_created_at (created_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='TGMonitor 监听消息表';
"""

SQL_CREATE_TGM_KEYWORD = """
CREATE TABLE IF NOT EXISTS tgm_keyword (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    word            VARCHAR(255) NOT NULL                    COMMENT '关键词文本',
    category        VARCHAR(50) NOT NULL                     COMMENT '分类: brand/product/risk/affiliate/competitor',
    match_type      VARCHAR(20) DEFAULT 'exact'              COMMENT '匹配方式: exact/regex/fuzzy',
    priority        INT DEFAULT 0                            COMMENT '优先级（数字越大越高）',
    is_active       TINYINT(1) DEFAULT 1                     COMMENT '是否启用',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_word_category (word, category),
    INDEX idx_category (category),
    INDEX idx_is_active (is_active)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='TGMonitor 关键词表';
"""

SQL_CREATE_TGM_ACCOUNT = """
CREATE TABLE IF NOT EXISTS tgm_account (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    phone               VARCHAR(20) NOT NULL UNIQUE              COMMENT '手机号',
    api_id              INT NOT NULL                             COMMENT 'Telegram API ID',
    api_hash            VARCHAR(64) NOT NULL                     COMMENT 'Telegram API Hash',
    session_name        VARCHAR(100) NOT NULL                    COMMENT 'Session 文件名',
    display_name        VARCHAR(100) DEFAULT NULL                COMMENT '备注名称',
    is_active           TINYINT(1) DEFAULT 1                     COMMENT '是否启用',
    status              VARCHAR(20) DEFAULT 'offline'            COMMENT '状态: online/offline/banned/flood_wait',
    last_connected_at   DATETIME DEFAULT NULL                    COMMENT '最后连接时间',
    last_error          TEXT DEFAULT NULL                        COMMENT '最近错误信息',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='TGMonitor 监听账号表';
"""

SQL_CREATE_TGM_MONITORED_CHAT = """
CREATE TABLE IF NOT EXISTS tgm_monitored_chat (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    chat_id                 BIGINT NOT NULL UNIQUE                   COMMENT 'Telegram 群组 ID',
    chat_title              VARCHAR(255) NOT NULL                    COMMENT '群组名称',
    chat_username           VARCHAR(255) DEFAULT NULL                COMMENT '群组用户名',
    chat_type               VARCHAR(20) DEFAULT 'group'              COMMENT '类型: group/supergroup/channel',
    assigned_account_phone  VARCHAR(20) DEFAULT NULL                 COMMENT '分配的监听账号手机号',
    is_active               TINYINT(1) DEFAULT 1                     COMMENT '是否启用监听',
    joined_at               DATETIME DEFAULT NULL                    COMMENT '加入时间',
    note                    VARCHAR(500) DEFAULT NULL                COMMENT '备注',
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_assigned_account (assigned_account_phone),
    INDEX idx_is_active (is_active)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='TGMonitor 被监听群组表';
"""

# ==================== DML: 种子关键词 ====================

SQL_SEED_KEYWORDS = """
INSERT IGNORE INTO tgm_keyword (word, category, match_type, priority, is_active) VALUES
-- brand（品牌）
('relinx',          'brand',      'exact', 100, 1),
('re-linx',         'brand',      'exact', 100, 1),
('re_linx',         'brand',      'exact', 100, 1),

-- risk（风控）
('scam',            'risk',       'fuzzy',  90, 1),
('fraud',           'risk',       'fuzzy',  90, 1),
('chargeback',      'risk',       'fuzzy',  90, 1),
('骗',              'risk',       'fuzzy',  90, 1),
('不发货',          'risk',       'fuzzy',  90, 1),
('fake',            'risk',       'fuzzy',  80, 1),

-- product（产品）
('gift card',       'product',    'fuzzy',  50, 1),
('game key',        'product',    'fuzzy',  50, 1),
('netflix',         'product',    'fuzzy',  50, 1),
('spotify',         'product',    'fuzzy',  50, 1),
('steam',           'product',    'fuzzy',  50, 1),

-- payment（支付）
('USDT',            'payment',    'exact',  30, 1),
('TRC20',           'payment',    'exact',  30, 1);
"""


ALL_DDL = [
    ("tgm_message", SQL_CREATE_TGM_MESSAGE),
    ("tgm_keyword", SQL_CREATE_TGM_KEYWORD),
    ("tgm_account", SQL_CREATE_TGM_ACCOUNT),
    ("tgm_monitored_chat", SQL_CREATE_TGM_MONITORED_CHAT),
]


async def init_database() -> None:
    """
    执行数据库初始化：建表 + 插入种子数据
    """
    logger.info("🚀 Starting TGMonitor database initialization...")

    conn = await aiomysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        db=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=True,
    )

    try:
        async with conn.cursor() as cur:
            # 1. 创建表
            for table_name, ddl in ALL_DDL:
                await cur.execute(ddl)
                logger.info("✅ Table '{}' ensured", table_name)

            # 2. 插入种子关键词
            await cur.execute(SQL_SEED_KEYWORDS)
            affected = cur.rowcount
            logger.info("✅ Seed keywords inserted ({} new rows)", affected)

            # 3. 验证
            await cur.execute("SELECT COUNT(*) FROM tgm_keyword")
            (keyword_count,) = await cur.fetchone()
            logger.info("📊 Total keywords in tgm_keyword: {}", keyword_count)

    finally:
        conn.close()
        logger.info("✅ Database initialization completed")


if __name__ == "__main__":
    asyncio.run(init_database())
