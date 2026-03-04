# TGMonitor 项目开发规则

---

# 核心原则

## 1. 数据访问层规则

- **禁止直接操作数据库**：所有数据操作必须通过 Redis 缓存层
- **必须使用 Service 层**：不允许直接调用 Repository，必须通过 Service 操作
- **保持 Redis 和数据库同步**：任何更新操作必须同时更新数据库和 Redis 缓存

```
正确的调用链：
  Handler / Filter → Service → Redis + Repository → MySQL

❌ 禁止：
  Handler → Repository（跳过 Service）
  Handler → 直接操作 Redis（跳过 Service）
  Service → 直接写 SQL（跳过 Repository）
```

## 2. 配置管理规则

- **禁止硬编码**：所有配置项必须写入配置文件或 `.env` 文件
- **敏感信息**：Telegram API 凭证（api_id、api_hash）、数据库密码等敏感信息只能放在 `.env` 文件中
- **环境变量**：使用 `settings.py` 统一加载 `.env` 配置，全局通过 `settings` 对象访问
- **禁止在代码中直接读取 `os.environ`**：统一通过 `config/settings.py` 的 `settings` 对象获取

```python
# ❌ 错误：直接读取环境变量
import os
db_host = os.environ.get('DB_HOST')

# ✅ 正确：通过 settings 对象
from config.settings import settings
db_host = settings.DB_HOST
```

---

## 3. 代码架构规则

### 3.1 分层架构（强制）

> 🚨 强制规范 (Mandatory)
> 所有业务代码必须严格遵守三层架构，违背此原则将直接导致代码审查 (Code Review) 不通过。

| 层级 | 目录 | 职责 | 允许调用 |
|------|------|------|---------|
| **数据实体层** | `models/` | pydantic 数据模型定义，字段映射，序列化/反序列化（Python 中 `types` 是标准库模块，故命名为 `models`） | 无依赖 |
| **数据库操作层** | `repositories/` | 纯 SQL CRUD 操作，事务管理 | `models/`、`config/database.py` |
| **业务逻辑层** | `services/` | 业务逻辑、Redis 缓存管理、调用 Repository | `models/`、`repositories/`、`config/redis_client.py` |
| **事件处理器** | `handlers/` | Telethon 事件处理，调用 Service | `services/`、`filters/` |
| **过滤引擎** | `filters/` | 关键词匹配逻辑 | `services/`（读取关键词） |
| **核心模块** | `core/` | 客户端管理、消息路由 | `handlers/`、`services/` |
| **配置** | `config/` | 数据库/Redis/全局配置 | 无依赖 |
| **工具** | `utils/` | 日志、通用工具函数 | 无依赖 |

```
依赖方向（单向，不可反向）：

  core/ → handlers/ → services/ → repositories/ → MySQL
                         ↕
                       Redis
```

### 3.2 层级调用规则

```python
# ❌ 错误：Handler 直接调用 Repository
class MessageHandler:
    async def on_message(self, event):
        await monitor_repository.insert(message)  # 跳过 Service

# ❌ 错误：Repository 操作 Redis
class MonitorRepository:
    async def insert(self, message):
        await redis.set(...)  # Repository 不应知道 Redis

# ✅ 正确：Handler → Service → Repository + Redis
class MessageHandler:
    async def on_message(self, event):
        await monitor_service.save_message(message)  # 调用 Service

class MonitorService:
    async def save_message(self, message):
        await self._save_to_redis(message)            # Service 管理 Redis
        await monitor_repository.insert(message)       # Service 调用 Repository
```

### 3.3 主键原则

- **数据库唯一主键是 `id`**（自增 BIGINT）
- **业务键不作为主键**：如 `telegram_message_id` 是 Telegram 的消息 ID，仅作为唯一约束用于去重，不作为主键
- **Redis 缓存键使用 `id`**：`monitor:msg:id:{id}` 使用数据库主键

---

## 4. 数据同步规则

### 4.1 两级存储规则

- **Redis 优先读取**：读取数据时优先从 Redis 获取
- **写入时双写**：写入数据时必须同时更新 MySQL 和 Redis
- **Redis 未命中时回源**：Redis 查不到时从 MySQL 查询，查到后回写 Redis

```python
# ✅ 标准读取模式
async def get_message_by_id(self, message_id: int) -> MonitoredMessage | None:
    # 1. 先查 Redis
    cached = await redis.get(f"monitor:msg:id:{message_id}")
    if cached:
        return MonitoredMessage.model_validate_json(cached)
    
    # 2. Redis 未命中，查 MySQL
    message = await monitor_repository.get_by_id(message_id)
    if message:
        # 3. 回写 Redis
        await redis.set(f"monitor:msg:id:{message.id}", message.model_dump_json())
    
    return message
```

```python
# ✅ 标准写入模式
async def save_message(self, message: MonitoredMessage) -> MonitoredMessage:
    # 1. 写入 MySQL（获取自增 ID）
    message.id = await monitor_repository.insert(message)
    
    # 2. 写入 Redis 缓存
    await redis.set(f"monitor:msg:id:{message.id}", message.model_dump_json())
    
    # 3. 更新索引
    await redis.sadd(f"monitor:msg:chat:{message.chat_id}", str(message.id))
    
    # 4. 标记去重
    await redis.setex(f"monitor:dedup:{message.chat_id}:{message.telegram_message_id}", 
                      DEDUP_TTL, "1")
    
    return message
```

### 4.2 Redis Key 规范

> 🚨 强制规范 (Mandatory)
> 所有 Redis Key 必须使用 `monitor:` 前缀，与 bot 项目的 `product:`、`order:` 等前缀隔离。

| 前缀 | 用途 | 示例 |
|------|------|------|
| `monitor:msg:id:` | 消息主数据 | `monitor:msg:id:12345` |
| `monitor:msg:chat:` | 按群组索引 | `monitor:msg:chat:987654` |
| `monitor:msg:sender:` | 按发送者索引 | `monitor:msg:sender:111222` |
| `monitor:msg:category:` | 按分类索引 | `monitor:msg:category:brand` |
| `monitor:dedup:` | 消息去重 | `monitor:dedup:987654:55555` |
| `monitor:keyword:` | 关键词缓存 | `monitor:keyword:all` |
| `monitor:entity:user:` | 用户信息缓存 | `monitor:entity:user:111222` |
| `monitor:entity:chat:` | 群组信息缓存 | `monitor:entity:chat:987654` |
| `monitor:stats` | 统计数据 | `monitor:stats` |

**命名规则**：
- 全部小写
- 使用 `:` 分隔层级
- 前缀统一为 `monitor:`
- Key 中的变量部分放在最后

---

## 5. 数据库和 Redis 配置

- TGMonitor 使用独立的 `.env` 文件（`TGMonitor/.env`），但配置值与 bot 项目保持一致，连接相同的 MySQL 和 Redis 实例
- **MySQL 配置**：
  ```
  DB_HOST=localhost
  DB_PORT=3306
  DB_USER=hello
  DB_PASSWORD=123456
  DB_NAME=hello
  ```
- **Redis 配置**：
  ```
  USE_REDIS=true
  REDIS_URL=redis://localhost:6379
  REDIS_DB=1
  ```
- MySQL 连接池使用 `config/database.py`（aiomysql 异步连接池）
- Redis 客户端使用 `config/redis_client.py`（redis-py async）
- **禁止在代码中自行创建数据库连接或 Redis 客户端**，必须使用上述模块

---

## 6. 目录设置

| 用途 | 目录 |
|------|------|
| 源代码 | `TGMonitor/src/` |
| 文档 | `TGMonitor/doc/` |
| Telethon Session 文件 | `TGMonitor/sessions/` |
| 日志文件 | `TGMonitor/logs/` |
| 环境变量 | `TGMonitor/.env` |

---

## 7. 数据库表命名规范

### 7.1 表名规范

> 🚨 强制规范 (Mandatory)
> TGMonitor 项目的所有数据库表必须使用 `tgm_` 前缀，与 bot 项目的 `TGMonitor_` 前缀隔离。

| 表 | 用途 |
|---|------|
| `tgm_message` | 监听到的消息记录 |
| `tgm_keyword` | 关键词配置 |
| `tgm_account` | 监听账号配置 |
| `tgm_monitored_chat` | 被监听群组配置 |

### 7.2 字段命名规范

- **使用 snake_case**：`message_text`、`chat_id`、`created_at`
- **主键统一命名 `id`**：BIGINT AUTO_INCREMENT
- **时间字段**：`created_at`、`updated_at` 使用 DATETIME，默认 `CURRENT_TIMESTAMP`
- **布尔字段**：使用 `TINYINT(1)`，字段名以 `is_` 开头，如 `is_active`
- **JSON 字段**：使用 MySQL JSON 类型，如 `matched_keywords`
- **字符集**：统一 `utf8mb4`，排序规则 `utf8mb4_unicode_ci`

### 7.3 索引命名规范

| 类型 | 命名格式 | 示例 |
|------|---------|------|
| 唯一索引 | `uk_表名简写_字段` | `uk_chat_msg` |
| 普通索引 | `idx_字段名` | `idx_chat_id` |
| 联合索引 | `idx_字段1_字段2` | `idx_chat_date` |

---

## 8. Python 代码规范

### 8.1 类型标注（强制）

所有函数、方法的参数和返回值必须有类型标注。

```python
# ❌ 错误：无类型标注
async def get_message(id):
    pass

# ✅ 正确：完整类型标注
async def get_message(self, message_id: int) -> MonitoredMessage | None:
    pass
```

### 8.2 数据实体规范

使用 pydantic v2 定义数据实体，参照 bot 项目中 `bot/src/types/product.ts` 的 class 定义模式。

```python
from pydantic import BaseModel, Field
from datetime import datetime

class MonitoredMessage(BaseModel):
    """
    监听消息实体
    对应数据库表: tgm_message
    """
    id: int | None = None
    telegram_message_id: int
    chat_id: int
    chat_title: str
    # ... 其他字段

    class Config:
        from_attributes = True  # 支持从 ORM/dict 创建
```

**规则**：
- 每个数据库表对应一个 pydantic Model
- Model 文件放在 `models/` 目录
- 文件名使用对应实体的 snake_case 名称
- 必须写 docstring 注明对应的数据库表名

### 8.3 Repository 规范

Repository 层只负责纯 SQL 操作，不涉及 Redis 和业务逻辑。

```python
class MonitorRepository:
    """
    监听消息数据库操作层
    对应表: tgm_message
    """

    async def insert(self, message: MonitoredMessage) -> int:
        """插入消息，返回自增 ID"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO tgm_message (...) VALUES (%s, %s, ...)",
                    (message.telegram_message_id, message.chat_id, ...)
                )
                return cur.lastrowid
```

**规则**：
- 每个数据库表对应一个 Repository 类
- 文件名：`{entity}_repository.py`
- 使用参数化查询（`%s` 占位符），**严禁字符串拼接 SQL**
- 使用 `async with` 管理连接，确保归还连接池
- 只能被 Service 层调用

### 8.4 Service 规范

Service 层负责业务逻辑和 Redis 缓存管理。

```python
class MonitorService:
    """
    消息监听业务逻辑层
    负责 Redis 缓存管理和调用 MonitorRepository
    """

    REDIS_PREFIX = "monitor:"
    REDIS_KEYS = {
        "MSG_BY_ID": "monitor:msg:id:",
        # ...
    }

    async def save_message(self, message: MonitoredMessage) -> MonitoredMessage:
        """保存消息：写 Redis + 写 MySQL"""
        ...

    async def get_message_by_id(self, message_id: int) -> MonitoredMessage | None:
        """获取消息：先查 Redis，未命中查 MySQL"""
        ...
```

**规则**：
- Redis Key 定义为类常量 `REDIS_KEYS`
- 所有 Redis 操作在 Service 层完成
- Service 导出为单例实例：`monitor_service = MonitorService()`

### 8.5 异步规范

TGMonitor 基于 asyncio 运行，所有 I/O 操作必须使用 async/await。

```python
# ❌ 错误：使用同步库
import mysql.connector
conn = mysql.connector.connect(...)  # 阻塞事件循环

# ✅ 正确：使用异步库
import aiomysql
pool = await aiomysql.create_pool(...)
```

**禁止项**：
- 禁止在 async 函数中调用同步阻塞 I/O（如 `time.sleep()`、同步数据库驱动）
- 禁止使用 `requests` 库，需要 HTTP 请求时使用 `aiohttp`
- 阻塞操作必须使用 `asyncio.to_thread()` 包装

### 8.6 异常处理规范

```python
# ✅ 正确：捕获特定异常，记录日志，不吞掉异常
async def save_message(self, message: MonitoredMessage) -> MonitoredMessage:
    try:
        message.id = await monitor_repository.insert(message)
        await self._cache_to_redis(message)
        return message
    except aiomysql.Error as e:
        logger.error(f"❌ MySQL insert failed for message {message.telegram_message_id}: {e}")
        raise
    except redis.RedisError as e:
        # Redis 失败不影响主流程，MySQL 已写入成功
        logger.warning(f"⚠️ Redis cache failed for message {message.id}: {e}")
        return message
```

**规则**：
- 捕获特定异常，不使用裸 `except:` 或 `except Exception:`
- MySQL 写入失败必须抛出，不能吞掉
- Redis 失败可以降级（仅告警），不影响主流程
- 所有异常必须记录日志

---

## 9. 日志规范

### 9.1 日志框架

使用 **loguru**，配置参照 bot 项目 `bot/src/utils/logger.ts` 的分级模式。

### 9.2 日志文件规划

| 文件 | 内容 | 级别 |
|------|------|------|
| `logs/app.log` | 全量日志 | DEBUG+ |
| `logs/error.log` | 仅错误日志 | ERROR+ |
| `logs/message.log` | 消息监听记录 | INFO（消息专用） |
| `logs/client.log` | Telethon 客户端连接/断线 | INFO（客户端专用） |

### 9.3 日志轮转配置

- 单文件最大 **10MB**
- 保留 **5** 个备份
- 启用 **gzip 压缩**

### 9.4 日志格式

```
[2026-03-03 14:30:25.123] [INFO] [module_name] 消息内容
```

### 9.5 日志使用规范

```python
from utils.logger import logger

# ✅ 正确：使用模块级 logger
logger.info("✅ Account {} connected", phone)
logger.error("❌ MySQL insert failed: {}", error)
logger.warning("⚠️ Redis cache miss for message {}", msg_id)
logger.debug("📩 Processing message {} from chat {}", msg_id, chat_id)

# ❌ 错误：使用 print
print("connected")  # 禁止使用 print 输出日志
```

**级别使用规范**：

| 级别 | 使用场景 |
|------|---------|
| `DEBUG` | 详细调试信息：Redis 操作、SQL 语句、消息处理细节 |
| `INFO` | 关键业务事件：连接成功、消息命中、关键词加载 |
| `WARNING` | 非关键性异常：Redis 缓存失败、FloodWait、Entity 获取失败 |
| `ERROR` | 严重错误：MySQL 写入失败、客户端连接失败 |

---

## 10. Telethon 使用规范

### 10.1 账号安全规则

> 🚨 红色警报 (Critical)
> 违反以下规则可能导致 Telegram 账号被封禁。

- **只读不写**：监听进程只接收消息，**严禁发送任何消息、回复、点赞**
- **不加群**：代码中**严禁自动加入群组**，所有加群操作必须由人工完成
- **不拉人**：**严禁邀请用户进群**
- **限制 API 调用频率**：`get_entity()` 等调用必须做 Redis 缓存，避免频繁请求

### 10.2 Session 文件安全

- Session 文件存放在 `TGMonitor/sessions/` 目录
- **Session 文件必须加入 `.gitignore`**
- Session 文件权限设置为 `600`（仅 owner 可读写）
- **禁止将 Session 内容存入环境变量或数据库**

### 10.3 Entity 缓存规则

每次查询用户/群组信息都会消耗 Telegram API 额度。必须缓存。

```python
# ❌ 错误：每次都调用 API
sender = await client.get_entity(sender_id)

# ✅ 正确：先查缓存
sender_info = await entity_cache_service.get_user(sender_id)
if not sender_info:
    sender = await client.get_entity(sender_id)
    await entity_cache_service.cache_user(sender_id, sender)
```

**缓存 TTL**：
- 用户信息：24 小时
- 群组信息：24 小时

### 10.4 断线重连

- Telethon 内置自动重连机制，无需自行实现
- 使用 PM2 作为兜底重启策略
- 重连后必须更新 `tgm_account.status` 和 `tgm_account.last_connected_at`

---

## 11. 关键词管理规范

### 11.1 关键词存储

- 关键词存储在 `tgm_keyword` 表中
- 通过 `KeywordService` 加载到 Redis 缓存
- **禁止在代码中硬编码关键词**

### 11.2 关键词分类

| 分类 | 优先级 | 说明 |
|------|--------|------|
| `brand` | 100 | 品牌直接相关 |
| `risk` | 90 | 风控/欺诈 |
| `competitor` | 70 | 竞品 |
| `product` | 50 | 产品/商品 |
| `affiliate` | 40 | 推广体系 |
| `payment` | 30 | 支付相关 |

### 11.3 热加载规则

- 关键词支持热加载（默认每 5 分钟检查更新）
- 修改 `tgm_keyword` 表后无需重启服务
- 热加载由 `KeywordService.reload_if_needed()` 自动触发

---

## 12. 文件命名与编码规范

### 12.1 文件命名

| 类型 | 命名规则 | 示例 |
|------|---------|------|
| Python 模块 | snake_case | `monitor_service.py` |
| pydantic Model | snake_case 文件名，PascalCase 类名 | `message.py` → `class MonitoredMessage` |
| Repository | `{entity}_repository.py` | `monitor_repository.py` |
| Service | `{entity}_service.py` | `monitor_service.py` |
| 配置文件 | snake_case | `settings.py`、`database.py` |
| 数据库表 | `tgm_` 前缀 + snake_case | `tgm_message` |

### 12.2 导入顺序

```python
# 1. 标准库
import asyncio
import re
from datetime import datetime

# 2. 第三方库
from loguru import logger
from pydantic import BaseModel
import aiomysql
import redis.asyncio as redis

# 3. 项目内部模块
from config.settings import settings
from config.database import get_pool
from models.message import MonitoredMessage
from repositories.monitor_repository import monitor_repository
```

### 12.3 代码文档

- 所有类必须有 docstring
- 所有 public 方法必须有 docstring
- docstring 中注明对应的数据库表（Repository/Service）
- 复杂逻辑必须有行内注释

---

## 13. Git 规范

### 13.1 .gitignore 要求

以下文件/目录必须加入 `.gitignore`：

```
# 环境配置
.env

# Session 文件（包含 Telegram 登录凭证）
sessions/

# 日志
logs/

# Python 缓存
__pycache__/
*.pyc
*.pyo

# IDE
.idea/
.vscode/
*.swp
```

### 13.2 禁止提交的内容

- `.env` 文件（包含数据库密码、API 凭证）
- `sessions/` 目录（包含 Telegram 登录凭证）
- `logs/` 目录
- `__pycache__/` 目录

---

## 14. 进程管理规范

- 使用 **PM2** 管理 TGMonitor 进程，与 bot 项目统一管理
- PM2 配置文件：`TGMonitor/ecosystem.config.js`
- 日志输出到 `TGMonitor/logs/` 目录

---

## 15. 检查清单

在提交代码前，确认以下各项：

- [ ] 所有数据操作通过 Service 层，未直接调用 Repository
- [ ] Redis Key 使用 `monitor:` 前缀
- [ ] 所有函数有完整类型标注
- [ ] 所有 I/O 操作使用 async/await
- [ ] SQL 使用参数化查询，无字符串拼接
- [ ] 异常已捕获并记录日志
- [ ] 未使用 `print()`，全部使用 `logger`
- [ ] Telegram API 调用做了 Entity 缓存
- [ ] 关键词未硬编码在代码中
- [ ] Session 文件和 .env 文件在 .gitignore 中
- [ ] 新数据库表使用 `tgm_` 前缀
- [ ] 新 Redis Key 使用 `monitor:` 前缀

---

**文档版本**: v1.0
**最后更新**: 2026-03-03
**作者**: GitHub Copilot
**审核状态**: 待审核
