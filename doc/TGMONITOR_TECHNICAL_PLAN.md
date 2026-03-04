# TGMonitor — Telegram 群组舆情监听系统技术方案

## 📋 文档信息

- **创建日期**: 2026-03-03
- **版本**: v1.0
- **目标**: 基于 Telethon 实现 Telegram 群组消息监听，捕获与 TGMonitor 业务相关的对话并持久化存储
- **核心策略**: 多账号监听、关键词过滤、Redis + MySQL 两级存储、三层架构

---

## 1. 需求描述

### 1.1 业务需求

使用普通 Telegram 账户（非 Bot），手工加入目标群组后，实时监听群内消息。当消息命中与 TGMonitor 业务相关的关键词时，记录：

1. **消息内容** — 完整文本
2. **发送者信息** — Telegram ID、用户名、显示名
3. **群组信息** — 群组 ID、群组名称
4. **命中关键词** — 触发记录的关键词及其分类
5. **消息时间** — 原始发送时间

### 1.2 技术要求

| 要求项 | 说明 |
|--------|------|
| 开发语言 | Python（Telethon） |
| 监听账号 | 支持**多个**普通 Telegram 账号，可配置 |
| 监听群组 | 支持**多个**群组，可配置，支持热加载 |
| 存储架构 | Redis（一级缓存） + MySQL 8（持久化），两级存储 |
| 代码架构 | types（数据实体） → services（业务逻辑） → repositories（数据库操作），三层结构 |
| 日志系统 | 成熟完整的日志体系，分级输出、文件轮转 |
| 可扩展性 | 模块化架构，支持后续扩展更多功能 |
| 数据库 | 复用现有 MySQL 8，与 bot 项目共享 |
| Redis | 复用现有 Redis 实例，与 bot 项目共享 |

### 1.3 配置复用

数据库和 Redis 使用与 bot 项目相同的实例：

```
# MySQL
DB_HOST=localhost
DB_PORT=3306
DB_USER=hello
DB_PASSWORD=123456
DB_NAME=hello

# Redis
USE_REDIS=true
REDIS_URL=redis://localhost:6379
REDIS_DB=1
```

---

## 2. 技术选型

### 2.1 核心依赖

| 组件 | 选型 | 版本 | 说明 |
|------|------|------|------|
| Telegram MTProto 客户端 | **[Telethon](https://github.com/LonamiWebs/Telethon)** | ≥1.36 | ⭐10k+，最成熟的 Python userbot 库 |
| 异步 MySQL 驱动 | **[aiomysql](https://github.com/aio-libs/aiomysql)** | ≥0.2.0 | 异步 MySQL 连接池，配合 asyncio |
| 异步 Redis 驱动 | **[redis-py](https://github.com/redis/redis-py)** (async) | ≥5.0 | 官方 Redis 客户端，原生支持 async |
| 配置管理 | **[python-dotenv](https://github.com/theskumar/python-dotenv)** | ≥1.0 | 读取 .env 文件 |
| 日志系统 | **Python logging** + **[loguru](https://github.com/Delgan/loguru)** | ≥0.7 | 成熟日志框架，支持轮转、分级、结构化 |
| 数据校验 | **[pydantic](https://github.com/pydantic/pydantic)** | ≥2.0 | 数据实体定义与校验 |
| 进程管理 | **PM2** | — | 与 bot 项目统一管理 |
| Python | **3.10+** | — | async/await、type hints 完整支持 |

### 2.2 选型理由

#### 为什么用 Telethon 而不是 GramJS？

| 对比维度 | Telethon (Python) | GramJS (TypeScript) |
|---------|-------------------|---------------------|
| GitHub Stars | ⭐ 10k+ | ⭐ 1.5k+ |
| 项目历史 | 8 年，久经考验 | 较新，社区案例少 |
| 断线重连 | 内置自动重连，长期运行稳定 | 偶有连接问题报告 |
| FloodWait 处理 | 内置自动等待，开发者无需关心 | 需要手动处理 |
| 文档 | 非常完善，StackOverflow 大量案例 | 文档一般，需参照 Telethon 推断 |
| 多账号支持 | 原生支持多客户端并行 | 支持但案例少 |

#### 为什么用 loguru 而不是 log4js？

bot 项目使用 TypeScript + log4js。TGMonitor 是独立 Python 进程，使用 Python 生态最成熟的 loguru：

- **零配置开箱即用**，同时支持高度定制
- 内置文件轮转、压缩、分级过滤
- 结构化日志输出（JSON 格式）
- 异步安全，不阻塞事件循环
- 日志风格参考 bot 项目的 `ref/logger.ts`：分级、文件轮转、独立错误日志

#### 为什么用 pydantic 做数据实体？

参考 bot 项目中 `ref/product.ts` 使用 class 定义数据实体的模式。Python 中 pydantic 是等价的最佳实践：

- 类型安全，运行时自动校验
- 支持 JSON 序列化/反序列化（Redis 存取）
- 支持与数据库字段映射
- IDE 自动补全友好

---

## 3. 系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Telegram MTProto                            │
└───────────┬─────────────────────┬─────────────────────┬─────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
│  TelethonClient   │ │  TelethonClient   │ │  TelethonClient   │
│  Account #1       │ │  Account #2       │ │  Account #N       │
│  (session_1.sess) │ │  (session_2.sess) │ │  (session_N.sess) │
└─────────┬─────────┘ └─────────┬─────────┘ └─────────┬─────────┘
          │                     │                     │
          └──────────┬──────────┴──────────┬──────────┘
                     │                     │
                     ▼                     ▼
          ┌────────────────┐    ┌────────────────────┐
          │  MessageRouter │    │  AccountManager    │
          │  消息路由分发    │    │  多账号管理         │
          └───────┬────────┘    └────────────────────┘
                  │
                  ▼
        ┌───────────────────┐
        │  KeywordFilter    │
        │  关键词匹配引擎    │
        │  - 精确匹配       │
        │  - 正则匹配       │
        │  - 分类标记       │
        └───────┬───────────┘
                │ 命中                │ 未命中 → 丢弃
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Services 业务逻辑层                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ MonitorService   │  │ KeywordService   │  │ AccountService   │  │
│  │ 消息记录业务逻辑   │  │ 关键词管理        │  │ 账号管理         │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
└───────────┼──────────────────────┼──────────────────────┼───────────┘
            │                      │                      │
            ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Redis 一级存储                                   │
│  monitor:msg:{id}     keyword:all          account:{id}            │
│  monitor:dedup:{key}  keyword:category:*   entity_cache:user:*     │
│  monitor:stats        keyword:last_reload  entity_cache:chat:*     │
└───────────┬──────────────────────┬──────────────────────┬───────────┘
            │                      │                      │
            ▼                      ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Repositories 数据库操作层                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │MonitorRepository │  │KeywordRepository │  │AccountRepository │  │
│  │  tgm_message     │  │  tgm_keyword     │  │  tgm_account     │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     MySQL 8 (hello 数据库)                          │
│  tgm_message | tgm_keyword | tgm_account | tgm_monitored_chat     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 三层架构详解

参照 bot 项目的架构模式：

| 层级 | bot 项目参考 | TGMonitor 对应 | 职责 |
|------|-------------|---------------|------|
| **数据实体层 (Models)** | `ref/product.ts` | `src/models/*.py` | 定义数据结构（pydantic Model），字段映射，序列化/反序列化 |
| **业务逻辑层 (Services)** | `ref/productService.ts` | `src/services/*.py` | 业务逻辑处理，Redis 缓存管理，调用 Repository |
| **数据库操作层 (Repositories)** | `ref/productRepository.ts` | `src/repositories/*.py` | 纯数据库 CRUD 操作，SQL 语句，事务管理 |

#### 数据流向

```
消息进入 → Handler 调用 Service
               ↓
         Service 先查/写 Redis
               ↓
         需要持久化时调用 Repository
               ↓
         Repository 操作 MySQL
```

### 3.3 两级存储详解

参照 `ref/productService.ts` 的 Redis + MySQL 两级存储模式：

```
写入流程：
  消息命中关键词
    → MonitorService.saveMessage(message_entity)
      → Redis SET monitor:msg:{id} (JSON序列化)
      → Redis SADD monitor:dedup:{chat_id}:{msg_id}
      → monitorRepository.insertMessage(message_entity) → MySQL

读取流程：
  查询消息记录
    → MonitorService.getMessageById(id)
      → Redis GET monitor:msg:{id}
        → 命中：反序列化返回
        → 未命中：monitorRepository.getById(id) → MySQL
          → 查到：写入 Redis 缓存，返回
          → 未查到：返回 None
```

**Redis Key 设计**（参照 `productService.ts` 的 `REDIS_KEYS` 模式）：

```python
REDIS_KEYS = {
    # 主数据存储
    "MSG_BY_ID": "monitor:msg:id:",              # STRING: 完整消息 JSON
    
    # 索引
    "MSG_BY_CHAT": "monitor:msg:chat:",           # SET: 按群组索引消息ID
    "MSG_BY_SENDER": "monitor:msg:sender:",       # SET: 按发送者索引消息ID
    "MSG_BY_CATEGORY": "monitor:msg:category:",   # SET: 按关键词分类索引
    "MSG_BY_DATE": "monitor:msg:date:",           # SORTED SET: 按时间排序
    
    # 去重
    "MSG_DEDUP": "monitor:dedup:",                # SET: chat_id:message_id，TTL 7天
    
    # 关键词缓存
    "KEYWORD_ALL": "monitor:keyword:all",         # HASH: 全部关键词
    "KEYWORD_RELOAD": "monitor:keyword:reload",   # STRING: 上次加载时间
    
    # 实体缓存（用户/群组信息，避免频繁调用 Telegram API）
    "ENTITY_USER": "monitor:entity:user:",        # STRING: 用户信息 JSON, TTL 24h
    "ENTITY_CHAT": "monitor:entity:chat:",        # STRING: 群组信息 JSON, TTL 24h
    
    # 统计
    "STATS": "monitor:stats",                     # HASH: 各类统计数据
}
```

---

## 4. 目录结构

```
TGMonitor/
├── doc/
│   └── TGMONITOR_TECHNICAL_PLAN.md       # 本文档
├── src/
│   ├── main.py                            # 入口：初始化并启动所有账号的监听
│   ├── auth.py                            # 首次登录认证脚本（生成 session）
│   │
│   ├── config/                            # 配置模块
│   │   ├── __init__.py
│   │   ├── settings.py                    # 全局配置（从 .env 加载）
│   │   ├── database.py                    # MySQL 连接池（参照 ref/database.ts）
│   │   ├── redis_client.py                # Redis 客户端管理（参照 ref/redisClient.ts）
│   │   └── accounts.py                    # 多账号配置加载
│   │
│   ├── models/                            # 数据实体层（参照 ref/product.ts，Python 中 types 是标准库模块，故命名为 models）
│   │   ├── __init__.py
│   │   ├── message.py                     # MonitoredMessage 实体
│   │   ├── keyword.py                     # Keyword 实体
│   │   ├── account.py                     # MonitorAccount 实体
│   │   └── monitored_chat.py              # MonitoredChat 实体
│   │
│   ├── services/                          # 业务逻辑层（参照 ref/productService.ts）
│   │   ├── __init__.py
│   │   ├── monitor_service.py             # 消息记录业务逻辑 + Redis 缓存
│   │   ├── keyword_service.py             # 关键词管理 + 热加载
│   │   ├── account_service.py             # 账号管理
│   │   └── entity_cache_service.py        # Telegram 用户/群组信息缓存
│   │
│   ├── repositories/                      # 数据库操作层（参照 ref/productRepository.ts）
│   │   ├── __init__.py
│   │   ├── monitor_repository.py          # tgm_message 表 CRUD
│   │   ├── keyword_repository.py          # tgm_keyword 表 CRUD
│   │   ├── account_repository.py          # tgm_account 表 CRUD
│   │   └── monitored_chat_repository.py   # tgm_monitored_chat 表 CRUD
│   │
│   ├── handlers/                          # 事件处理器
│   │   ├── __init__.py
│   │   └── message_handler.py             # NewMessage 事件处理（过滤 + 分发到 Service）
│   │
│   ├── filters/                           # 过滤引擎
│   │   ├── __init__.py
│   │   └── keyword_filter.py              # 关键词匹配引擎（精确 + 正则 + 分类）
│   │
│   ├── core/                              # 核心模块
│   │   ├── __init__.py
│   │   ├── client_manager.py              # Telethon 多客户端管理（创建、连接、断线重连）
│   │   └── message_router.py              # 消息路由（从 Handler 到 Filter 到 Service）
│   │
│   └── utils/                             # 工具模块
│       ├── __init__.py
│       └── logger.py                      # 日志配置（参照 ref/logger.ts 的分级模式）
│
├── sessions/                              # Telethon session 文件（.gitignore）
├── logs/                                  # 日志文件目录
├── .env                                   # 环境变量配置
├── .env.example                           # 环境变量模板
├── requirements.txt                       # Python 依赖
├── ecosystem.config.js                    # PM2 配置
└── .gitignore
```

---

## 5. 数据实体定义

### 5.1 MonitoredMessage — 监听到的消息

**对应数据库表**: `tgm_message`

**参照**: `ref/product.ts` 中 `Product` 类的定义方式

```python
class MonitoredMessage(BaseModel):
    """
    监听消息实体
    对应数据库表: tgm_message
    """
    # 数据库主键
    id: int | None = None

    # Telegram 原始信息
    telegram_message_id: int          # Telegram 消息 ID
    chat_id: int                      # 群组 ID
    chat_title: str                   # 群组名称
    sender_id: int                    # 发送者 Telegram ID
    sender_username: str | None       # 发送者用户名 (@xxx)
    sender_display_name: str | None   # 发送者显示名（first_name + last_name）

    # 消息内容
    message_text: str                 # 消息文本内容
    message_type: str = "text"        # 消息类型: text / caption / reply
    reply_to_message_id: int | None   # 回复的消息 ID（如有）

    # 关键词匹配结果
    matched_keywords: list[str]       # 命中的关键词列表
    keyword_category: str             # 最高优先级分类: brand / product / risk / affiliate / competitor

    # 账号信息
    monitor_account_phone: str        # 执行监听的账号手机号（标识哪个账号捕获的）

    # 时间戳
    message_date: datetime            # 消息原始发送时间
    created_at: datetime              # 记录创建时间
```

### 5.2 Keyword — 关键词

**对应数据库表**: `tgm_keyword`

```python
class Keyword(BaseModel):
    """
    关键词实体
    对应数据库表: tgm_keyword
    """
    id: int | None = None

    word: str                         # 关键词文本
    category: str                     # 分类: brand / product / risk / affiliate / competitor
    match_type: str = "exact"         # 匹配方式: exact(精确) / regex(正则) / fuzzy(模糊)
    priority: int = 0                 # 优先级（数字越大越高，用于确定 keyword_category）
    is_active: bool = True            # 是否启用

    created_at: datetime
    updated_at: datetime
```

### 5.3 MonitorAccount — 监听账号

**对应数据库表**: `tgm_account`

```python
class MonitorAccount(BaseModel):
    """
    监听账号实体
    对应数据库表: tgm_account
    """
    id: int | None = None

    phone: str                        # 手机号（唯一标识）
    api_id: int                       # Telegram API ID
    api_hash: str                     # Telegram API Hash
    session_name: str                 # Session 文件名（不含路径和扩展名）
    display_name: str | None          # 备注名称

    is_active: bool = True            # 是否启用
    status: str = "offline"           # 状态: online / offline / banned / flood_wait
    last_connected_at: datetime | None
    last_error: str | None            # 最近一次错误信息

    created_at: datetime
    updated_at: datetime
```

### 5.4 MonitoredChat — 监听的群组

**对应数据库表**: `tgm_monitored_chat`

```python
class MonitoredChat(BaseModel):
    """
    被监听群组实体
    对应数据库表: tgm_monitored_chat
    """
    id: int | None = None

    chat_id: int                      # Telegram 群组 ID
    chat_title: str                   # 群组名称
    chat_username: str | None         # 群组 @用户名（如有）
    chat_type: str = "group"          # 类型: group / supergroup / channel

    # 分配给哪个监听账号
    assigned_account_phone: str | None  # 分配的监听账号手机号

    is_active: bool = True            # 是否启用监听
    joined_at: datetime | None        # 加入时间
    note: str | None                  # 备注

    created_at: datetime
    updated_at: datetime
```

---

## 6. 数据库表设计

### 6.1 tgm_message — 监听消息表

```sql
CREATE TABLE tgm_message (
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

    -- 唯一约束：同一群组同一消息只记录一次
    UNIQUE KEY uk_chat_msg (chat_id, telegram_message_id),

    -- 查询索引
    INDEX idx_chat_id (chat_id),
    INDEX idx_sender_id (sender_id),
    INDEX idx_keyword_category (keyword_category),
    INDEX idx_message_date (message_date),
    INDEX idx_monitor_account (monitor_account_phone),
    INDEX idx_created_at (created_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='TGMonitor 监听消息表';
```

### 6.2 tgm_keyword — 关键词表

```sql
CREATE TABLE tgm_keyword (
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
```

### 6.3 tgm_account — 监听账号表

```sql
CREATE TABLE tgm_account (
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
```

### 6.4 tgm_monitored_chat — 被监听群组表

```sql
CREATE TABLE tgm_monitored_chat (
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
```

### 6.5 表关系

```
tgm_account (1) ──── (N) tgm_monitored_chat     一个账号监听多个群组
tgm_monitored_chat (1) ──── (N) tgm_message      一个群组产生多条消息
tgm_keyword (N) ──── (N) tgm_message             多对多：消息命中多个关键词
```

---

## 7. 核心模块详细设计

### 7.1 config/database.py — MySQL 连接池

**参照**: `ref/database.ts`

```python
# 职责：创建和管理 aiomysql 异步连接池
# 与 bot 项目使用相同的数据库实例和配置模式

pool = await aiomysql.create_pool(
    host=settings.DB_HOST,         # localhost
    port=settings.DB_PORT,         # 3306
    user=settings.DB_USER,         # hello
    password=settings.DB_PASSWORD, # 123456
    db=settings.DB_NAME,           # hello
    charset='utf8mb4',
    maxsize=10,
    minsize=2,
    autocommit=True
)
```

**关键设计**：
- 单例模式，全局共享连接池
- `get_pool()` 方法获取连接池（懒初始化）
- `close_pool()` 方法优雅关闭

### 7.2 config/redis_client.py — Redis 客户端

**参照**: `ref/redisClient.ts` 中的 `RedisClientManager` 单例模式

```python
# 职责：创建和管理 Redis 异步客户端
# 与 bot 项目使用相同的 Redis 实例

redis_client = redis.asyncio.Redis(
    host='localhost',
    port=6379,
    db=settings.REDIS_DB,          # 1
    decode_responses=True
)
```

**关键设计**：
- 单例模式，`get_redis()` 获取客户端
- 支持 `USE_REDIS=false` 时降级为纯 MySQL 模式
- 连接检测与自动重连

### 7.3 services/monitor_service.py — 消息记录业务逻辑

**参照**: `ref/productService.ts` 的完整模式

```python
class MonitorService:
    """
    消息监听业务逻辑层
    负责：
    1. Redis 缓存管理（读写一级存储）
    2. 调用 MonitorRepository 操作数据库（二级存储）
    3. 消息去重
    4. Entity 缓存管理（Telegram 用户/群组信息）
    """

    REDIS_PREFIX = "monitor:"
    REDIS_KEYS = { ... }  # 参见 3.3 节

    async def save_message(self, message: MonitoredMessage) -> MonitoredMessage:
        """
        保存监听到的消息
        流程：
        1. 检查去重（Redis SISMEMBER）
        2. 写入 Redis 缓存
        3. 写入 MySQL（调用 repository）
        4. 标记去重
        """

    async def get_message_by_id(self, message_id: int) -> MonitoredMessage | None:
        """
        获取消息（先查 Redis，未命中查 MySQL）
        """

    async def get_messages_by_chat(self, chat_id: int, limit: int, offset: int) -> list[MonitoredMessage]:
        """
        按群组查询消息
        """

    async def is_duplicate(self, chat_id: int, telegram_message_id: int) -> bool:
        """
        检查消息是否已处理（Redis 去重集合）
        """
```

### 7.4 services/keyword_service.py — 关键词管理

```python
class KeywordService:
    """
    关键词业务逻辑层
    负责：
    1. 从 MySQL 加载关键词到 Redis
    2. 支持热加载（定时或按需重新加载）
    3. 提供关键词查询接口给 KeywordFilter
    """

    async def load_keywords(self) -> None:
        """从数据库加载所有启用的关键词到 Redis"""

    async def get_all_active_keywords(self) -> list[Keyword]:
        """获取所有启用的关键词（先查 Redis）"""

    async def reload_if_needed(self, interval_seconds: int = 300) -> None:
        """定时检查是否需要重新加载（默认 5 分钟）"""
```

### 7.5 repositories/monitor_repository.py — 消息数据库操作

**参照**: `ref/productRepository.ts` 的模式

```python
class MonitorRepository:
    """
    监听消息数据库操作层
    职责：纯 SQL 操作，不涉及 Redis 和业务逻辑
    """

    async def insert(self, message: MonitoredMessage) -> int:
        """插入一条消息记录，返回自增 ID"""

    async def get_by_id(self, message_id: int) -> MonitoredMessage | None:
        """按 ID 查询"""

    async def get_by_chat_id(self, chat_id: int, limit: int, offset: int) -> list[MonitoredMessage]:
        """按群组 ID 分页查询"""

    async def get_by_date_range(self, start: datetime, end: datetime, limit: int) -> list[MonitoredMessage]:
        """按时间范围查询"""

    async def get_by_keyword_category(self, category: str, limit: int, offset: int) -> list[MonitoredMessage]:
        """按关键词分类查询"""

    async def count_by_chat_id(self, chat_id: int) -> int:
        """统计某群组消息数量"""
```

### 7.6 core/client_manager.py — 多客户端管理

```python
class ClientManager:
    """
    Telethon 多客户端管理器
    职责：
    1. 根据 tgm_account 配置创建多个 TelegramClient 实例
    2. 管理连接/断线重连/状态上报
    3. 为每个 Client 注册 MessageHandler
    """

    clients: dict[str, TelegramClient]  # phone -> client

    async def start_all(self) -> None:
        """启动所有启用的账号客户端"""

    async def stop_all(self) -> None:
        """优雅停止所有客户端"""

    async def restart_client(self, phone: str) -> None:
        """重启指定账号的客户端"""

    def _create_client(self, account: MonitorAccount) -> TelegramClient:
        """创建单个 Telethon 客户端实例"""
```

### 7.7 filters/keyword_filter.py — 关键词匹配引擎

```python
class KeywordFilter:
    """
    关键词匹配引擎
    职责：
    1. 接收消息文本
    2. 遍历关键词列表进行匹配
    3. 返回匹配结果（命中关键词 + 最高优先级分类）
    """

    async def match(self, text: str) -> FilterResult | None:
        """
        匹配消息文本
        返回 FilterResult(matched_keywords=["TGMonitor", "gift card"], category="brand")
        返回 None 表示未命中任何关键词
        """

    def _exact_match(self, text: str, keyword: str) -> bool:
        """精确匹配（大小写不敏感）"""

    def _regex_match(self, text: str, pattern: str) -> bool:
        """正则匹配"""
```

### 7.8 handlers/message_handler.py — 消息事件处理器

```python
async def on_new_message(event, account_phone: str):
    """
    Telethon NewMessage 事件处理函数
    
    流程：
    1. 提取消息文本（跳过空消息、纯媒体）
    2. 检查消息来源是否为被监听的群组
    3. 调用 KeywordFilter.match() 进行关键词匹配
    4. 未命中 → 丢弃
    5. 命中 → 构建 MonitoredMessage 实体
    6. 调用 MonitorService.save_message() 持久化
    7. (可选) 高优先级触发告警
    """
```

### 7.9 utils/logger.py — 日志系统

**参照**: `ref/logger.ts` 的日志分级和文件轮转模式

```python
# 使用 loguru 实现，日志分级与 bot 项目保持一致风格

# 日志文件结构：
# TGMonitor/logs/
# ├── app.log           # 全量日志（DEBUG/INFO/WARNING/ERROR）
# ├── error.log         # 仅错误日志
# ├── message.log       # 消息监听专用日志（捕获的消息记录）
# └── client.log        # Telethon 客户端连接/断线日志

# 配置项：
# - 控制台输出：开发环境彩色输出，生产环境关闭
# - 文件轮转：单文件最大 10MB，保留 5 个备份，自动压缩
# - 分级过滤：ERROR 级别单独输出到 error.log
# - 结构化格式：[时间] [级别] [模块] 消息内容
```

日志格式示例：

```
[2026-03-03 14:30:25.123] [INFO] [client_manager] ✅ Account +8613800138000 connected
[2026-03-03 14:30:26.456] [INFO] [message_handler] 📩 Message matched in "Crypto交流群" | keywords: ["TGMonitor"] | category: brand
[2026-03-03 14:30:26.500] [DEBUG] [monitor_service] 💾 Saved message ID: 12345 to Redis + MySQL
[2026-03-03 14:31:00.000] [WARNING] [client_manager] ⚠️ Account +8613800138000 FloodWait: 30s
[2026-03-03 14:35:00.000] [ERROR] [monitor_repository] ❌ MySQL insert failed: Connection lost
```

---

## 8. 关键词体系设计

### 8.1 关键词分类

根据 TGMonitor 业务（加密货币支付电商平台、Gift Card / Game Key 销售），定义以下分类：

| 分类 (category) | 优先级 | 说明 | 示例关键词 |
|-----------------|--------|------|-----------|
| `brand` | 100 | 品牌直接相关 | `TGMonitor`, `re-linx`, Bot 用户名 |
| `risk` | 90 | 风控/欺诈相关 | `scam`, `fraud`, `骗`, `不发货`, `chargeback` |
| `competitor` | 70 | 竞品名称 | 竞品品牌名（按需配置） |
| `product` | 50 | 产品/商品相关 | `gift card`, `game key`, `netflix`, `steam`, `spotify` |
| `affiliate` | 40 | 推广体系相关 | `commission`, `referral`, `返佣`, `推广` |
| `payment` | 30 | 支付相关 | `USDT`, `BTC`, `TRC20`, `充值`, `提现` |

### 8.2 关键词匹配策略

| 匹配方式 (match_type) | 说明 | 示例 |
|----------------------|------|------|
| `exact` | 精确匹配（大小写不敏感，word boundary） | `TGMonitor` 匹配 "I like TGMonitor" 但不匹配 "TGMonitoryz" |
| `regex` | 正则表达式匹配 | `re[-_]?linx` 匹配 "re-linx", "re_linx", "TGMonitor" |
| `fuzzy` | 包含匹配（大小写不敏感） | `gift card` 匹配 "cheap Gift Cards here" |

### 8.3 关键词热加载

- 关键词存储在 `tgm_keyword` 表中
- `KeywordService` 启动时从 MySQL 全量加载到 Redis
- 每 5 分钟自动检查是否有更新（比对 `updated_at`）
- 管理员修改关键词后无需重启服务

### 8.4 初始关键词（种子数据）

```sql
INSERT INTO tgm_keyword (word, category, match_type, priority, is_active) VALUES
-- brand（品牌）
('TGMonitor',          'brand',      'exact', 100, 1),
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
```

---

## 9. 业务流程

### 9.1 系统启动流程

```
main.py 启动
  │
  ├── 1. 加载 .env 配置
  ├── 2. 初始化日志系统 (loguru)
  ├── 3. 初始化 MySQL 连接池 (database.py)
  ├── 4. 初始化 Redis 客户端 (redis_client.py)
  ├── 5. KeywordService.load_keywords() — 从 MySQL 加载关键词到 Redis
  ├── 6. AccountService.load_accounts() — 从 MySQL 加载启用的监听账号
  ├── 7. ClientManager.start_all()
  │       ├── 为每个账号创建 TelegramClient
  │       ├── 使用 session 文件免登录连接
  │       ├── 注册 NewMessage 事件处理器 (message_handler)
  │       ├── 更新账号状态为 online
  │       └── 启动监听循环 (client.run_until_disconnected)
  └── 8. 启动定时任务
          ├── 关键词热加载 (每 5 分钟)
          └── 健康检查 (每 1 分钟)
```

### 9.2 消息处理流程

```
群组消息到达
  │
  ▼
Telethon NewMessage Event
  │
  ├── 1. 提取消息文本
  │      ├── 纯文本消息 → message.text
  │      ├── 带 caption 的媒体消息 → message.text (Telethon 自动处理)
  │      └── 空消息 / 系统消息 → 跳过
  │
  ├── 2. 检查消息来源
  │      ├── 来自已配置的监听群组 → 继续
  │      └── 来自未配置的群组 → 丢弃
  │
  ├── 3. 关键词匹配 (KeywordFilter.match)
  │      ├── 文本预处理：小写化、去除多余空格
  │      ├── 遍历关键词列表：
  │      │   ├── exact → word boundary + case-insensitive
  │      │   ├── regex → re.search(pattern, text, re.IGNORECASE)
  │      │   └── fuzzy → keyword.lower() in text.lower()
  │      ├── 未命中任何关键词 → 丢弃
  │      └── 命中 → 返回 FilterResult(matched_keywords, category)
  │
  ├── 4. 消息去重 (MonitorService.is_duplicate)
  │      ├── Redis SISMEMBER monitor:dedup:{chat_id}:{msg_id}
  │      ├── 已处理 → 跳过
  │      └── 未处理 → 继续
  │
  ├── 5. 解析发送者信息
  │      ├── 先查 Redis 缓存 (entity_cache:user:{sender_id})
  │      ├── 缓存命中 → 使用缓存
  │      └── 缓存未命中 → client.get_entity(sender_id)
  │            → 写入 Redis 缓存 (TTL 24h)
  │
  ├── 6. 构建 MonitoredMessage 实体
  │
  ├── 7. 持久化 (MonitorService.save_message)
  │      ├── 写入 Redis（一级缓存）
  │      ├── 写入 MySQL（持久化）
  │      └── 标记去重（Redis SADD, TTL 7天）
  │
  └── 8. (可选) 高优先级告警
         └── category == "risk" + brand → 推送通知
```

### 9.3 首次登录认证流程

```
运行 auth.py
  │
  ├── 1. 输入手机号
  ├── 2. Telethon 发送验证码到手机
  ├── 3. 输入验证码
  ├── 4. (可能) 输入两步验证密码
  ├── 5. 认证成功
  ├── 6. 生成 session 文件保存到 sessions/ 目录
  └── 7. 将账号信息写入 tgm_account 表

后续启动直接使用 session 文件，无需重复登录
```

---

## 10. 配置文件设计

### 10.1 .env 文件

```bash
# ==================== TGMonitor 配置 ====================

# 运行环境
NODE_ENV=development

# ==================== MySQL 配置（与 bot 共享） ====================
DB_HOST=localhost
DB_PORT=3306
DB_USER=hello
DB_PASSWORD=123456
DB_NAME=hello

# ==================== Redis 配置（与 bot 共享） ====================
USE_REDIS=true
REDIS_URL=redis://localhost:6379
REDIS_DB=1

# ==================== 日志配置 ====================
LOG_LEVEL=DEBUG
LOG_DIR=./logs

# ==================== 监听配置 ====================
# 关键词刷新间隔（秒）
KEYWORD_RELOAD_INTERVAL=300

# 消息去重 TTL（秒，默认 7 天）
DEDUP_TTL=604800

# Entity 缓存 TTL（秒，默认 24 小时）
ENTITY_CACHE_TTL=86400

# ==================== 告警配置（可选） ====================
# 通过现有 bot 发送告警
ALERT_ENABLED=false
ALERT_BOT_TOKEN=
ALERT_CHAT_ID=
```

### 10.2 .env.example

与 `.env` 内容相同但密码和 Token 为空，供新环境参考。

### 10.3 ecosystem.config.js（PM2 配置）

```javascript
module.exports = {
  apps: [
    {
      name: 'tg-monitor',
      script: 'src/main.py',
      interpreter: 'python3',
      cwd: '/Users/james/git/TGMonitor/TGMonitor',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'development'
      },
      env_production: {
        NODE_ENV: 'production'
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: './logs/pm2-error.log',
      out_file: './logs/pm2-out.log',
      merge_logs: true
    }
  ]
};
```

---

## 11. 风险评估与缓解

### 11.1 潜在风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 监听账号被 Telegram 封禁 | 高 | 中 | 使用专用号；只读不写不回复；多账号备份；避免短时间加入大量群 |
| FloodWait 限制 | 中 | 高 | Telethon 内置自动等待处理；Entity 信息做 Redis 缓存减少 API 调用 |
| Session 文件泄露 | 高 | 低 | session 文件权限 600；加入 .gitignore；环境变量不存敏感数据 |
| 群消息量过大导致写入压力 | 中 | 中 | 关键词先过滤再写库；aiomysql 批量 INSERT；Redis 队列缓冲 |
| MySQL 连接池耗尽 | 中 | 低 | 合理配置 maxsize=10；Repository 层使用 async with 确保连接归还 |
| Redis 与 bot 项目 Key 冲突 | 高 | 低 | 所有 Key 使用 `monitor:` 前缀，与 bot 项目的 `product:`、`order:` 等前缀隔离 |
| 断网/服务器重启导致中断 | 中 | 中 | PM2 自动重启；Telethon 自动重连；启动时不丢失已保存数据 |

### 11.2 回滚计划

| 场景 | 回滚方案 |
|------|---------|
| 代码缺陷 | Git revert，PM2 restart |
| 数据库表异常 | 所有表独立（tgm_ 前缀），可单独 DROP 不影响 bot 业务 |
| Redis 数据异常 | 清除 `monitor:*` 前缀的所有 Key，重启服务自动重建 |
| 账号被封 | 从 tgm_account 禁用该账号，新账号认证后启用 |

---

## 12. 实施步骤

### 阶段 1: 基础设施搭建（预计 2 小时）

- [ ] **步骤 1.1**: 创建目录结构
  - 按照第 4 节创建所有目录和 `__init__.py` 文件
  - 创建 `.env`、`.env.example`、`requirements.txt`、`.gitignore`

- [ ] **步骤 1.2**: 实现配置模块
  - `config/settings.py` — 从 .env 加载全局配置
  - `config/database.py` — MySQL 异步连接池（参照 `ref/database.ts`）
  - `config/redis_client.py` — Redis 客户端管理（参照 `ref/redisClient.ts`）

- [ ] **步骤 1.3**: 实现日志系统
  - `utils/logger.py` — loguru 配置（参照 `ref/logger.ts` 的分级模式）

- [ ] **步骤 1.4**: 创建数据库表
  - 执行第 6 节的 4 条 CREATE TABLE SQL
  - 插入第 8.4 节的初始关键词种子数据

### 阶段 2: 数据实体与存储层（预计 2 小时）

- [ ] **步骤 2.1**: 实现数据实体层
  - `models/message.py` — MonitoredMessage
  - `models/keyword.py` — Keyword
  - `models/account.py` — MonitorAccount
  - `models/monitored_chat.py` — MonitoredChat

- [ ] **步骤 2.2**: 实现数据库操作层
  - `repositories/monitor_repository.py` — tgm_message CRUD
  - `repositories/keyword_repository.py` — tgm_keyword CRUD
  - `repositories/account_repository.py` — tgm_account CRUD
  - `repositories/monitored_chat_repository.py` — tgm_monitored_chat CRUD

- [ ] **步骤 2.3**: 单元测试 Repository 层
  - 验证所有 CRUD 操作正确
  - 验证连接池正常工作

### 阶段 3: 业务逻辑层（预计 2 小时）

- [ ] **步骤 3.1**: 实现 Service 层
  - `services/monitor_service.py` — 消息记录 + Redis 缓存
  - `services/keyword_service.py` — 关键词管理 + 热加载
  - `services/account_service.py` — 账号管理
  - `services/entity_cache_service.py` — Telegram 实体缓存

- [ ] **步骤 3.2**: 验证两级存储
  - 测试 Redis + MySQL 写入流程
  - 测试先查 Redis、未命中查 MySQL 的读取流程
  - 测试消息去重逻辑

### 阶段 4: 核心监听功能（预计 3 小时）

- [ ] **步骤 4.1**: 实现关键词匹配引擎
  - `filters/keyword_filter.py` — exact / regex / fuzzy 三种匹配

- [ ] **步骤 4.2**: 实现消息事件处理器
  - `handlers/message_handler.py` — NewMessage 处理全流程

- [ ] **步骤 4.3**: 实现多客户端管理
  - `core/client_manager.py` — 多账号 Telethon 客户端管理
  - `core/message_router.py` — 消息路由

- [ ] **步骤 4.4**: 实现认证脚本
  - `auth.py` — 交互式登录 + session 生成

- [ ] **步骤 4.5**: 实现主入口
  - `main.py` — 启动流程编排

### 阶段 5: 集成测试（预计 2 小时）

- [ ] **步骤 5.1**: 单账号测试
  - 认证一个账号
  - 加入测试群组
  - 发送测试消息，验证监听和存储

- [ ] **步骤 5.2**: 多账号测试
  - 认证第二个账号
  - 验证多个客户端并行监听

- [ ] **步骤 5.3**: 压力测试
  - 模拟高频消息
  - 验证去重、连接池、Redis 缓存

- [ ] **步骤 5.4**: 稳定性测试
  - 使用 PM2 部署
  - 模拟断网重连
  - 运行 24 小时观察日志

### 阶段 6: 文档与部署（预计 1 小时）

- [ ] **步骤 6.1**: 编写 README.md
  - 安装说明、配置说明、使用说明

- [ ] **步骤 6.2**: 配置 PM2
  - 创建 ecosystem.config.js
  - 与 bot 项目统一管理

---

## 13. 前后对比（引入监听前 vs 后）

### 13.1 能力对比

| 能力 | 引入前 | 引入后 |
|------|--------|--------|
| 品牌舆情感知 | ❌ 无 | ✅ 实时监听多个群组 |
| 竞品分析 | ❌ 无 | ✅ 捕获竞品讨论 |
| 风控预警 | ❌ 仅订单层面 | ✅ 群组层面提前发现欺诈讨论 |
| 推广效果追踪 | ❌ 仅看数据 | ✅ 观察推广讨论热度 |
| 用户反馈收集 | ❌ 手动翻群 | ✅ 自动记录相关讨论 |

### 13.2 技术指标

| 指标 | 预期值 |
|------|--------|
| 消息处理延迟 | < 500ms（从收到到写库） |
| 关键词匹配吞吐 | > 1000 msg/s |
| 支持监听群组数 | 单账号 500+，多账号无上限 |
| 存储成本 | 约 1KB/条消息，每日万条约 10MB |
| 内存占用 | < 200MB（单进程） |

---

## 14. 后续扩展方向

当前方案预留了以下扩展能力：

| 扩展方向 | 实现方式 | 涉及模块 |
|---------|---------|---------|
| 自动回复 | 在 MessageHandler 中增加回复逻辑 | handlers/ |
| NLP 语义分析 | 新增 `filters/nlp_filter.py`，调用 LLM API | filters/ |
| Web 管理后台 | 新增 FastAPI 层，查询 MySQL 数据 | 新建 api/ 目录 |
| 告警推送 | 新增 `services/alert_service.py` | services/ |
| 消息导出 | 新增 `services/export_service.py` | services/ |
| 群组自动发现 | 新增 `core/chat_discovery.py` | core/ |
| 数据统计仪表盘 | 读取 `tgm_message` 表做聚合分析 | 新建 analytics/ |

---

## 15. 检查清单

### 开发前检查

- [ ] Python 3.10+ 已安装
- [ ] 已获取 Telegram API 凭证 (api_id, api_hash)
- [ ] 已准备专用 Telegram 监听账号（非 bot 运营号）
- [ ] MySQL hello 数据库可连接
- [ ] Redis 实例可连接

### 开发中检查

- [ ] 每完成一个模块立即编写测试
- [ ] 每个 Repository 方法确认 SQL 正确
- [ ] 每个 Service 方法确认 Redis 操作正确
- [ ] Session 文件已加入 .gitignore
- [ ] .env 已加入 .gitignore
- [ ] Redis Key 全部使用 `monitor:` 前缀

### 部署前检查

- [ ] 所有测试通过
- [ ] PM2 配置正确
- [ ] 日志轮转配置正确
- [ ] 错误日志独立输出
- [ ] 监听账号状态正常
- [ ] 初始关键词已导入

---

## 16. 总结

| 维度 | 说明 |
|------|------|
| 核心技术 | Python + Telethon (MTProto userbot) |
| 架构 | 三层架构 (Types → Services → Repositories) + 两级存储 (Redis + MySQL) |
| 多账号 | ClientManager 管理多个 TelegramClient，支持配置化 |
| 多群组 | tgm_monitored_chat 表配置，支持热加载 |
| 关键词 | tgm_keyword 表配置，支持 exact/regex/fuzzy 三种匹配，热加载 |
| 日志 | loguru 分级输出、文件轮转、独立错误日志 |
| 进程管理 | PM2 统一管理 |
| 代码量预估 | ~1500 行 Python |
| 预计开发周期 | 12 小时 |

---

**文档版本**: v1.0
**最后更新**: 2026-03-03
**作者**: GitHub Copilot
**审核状态**: 待审核
