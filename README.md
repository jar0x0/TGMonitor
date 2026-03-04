# TGMonitor — Telegram 群组舆情监听系统

基于 [Telethon](https://github.com/LonamiWebs/Telethon) 的 Telegram 群组实时消息监听系统。使用普通 Telegram 账号加入目标群组，当群内消息命中预设关键词时自动捕获并持久化存储。

## 功能特性

- **多账号监听** — 支持多个 Telegram 账号并行监听，互为备份
- **多群组覆盖** — 每个账号可监听多个群组 / 超级群组 / 频道
- **关键词引擎** — 支持精确 (exact)、正则 (regex)、模糊 (fuzzy) 三种匹配模式
- **关键词热加载** — 修改数据库关键词后无需重启，自动生效（默认 5 分钟刷新）
- **两级存储** — Redis 一级缓存 + MySQL 持久化，消息自动去重
- **PM2 管理** — 进程守护、自动重启、日志轮转
- **完整日志** — 按级别分文件输出，支持自动轮转与压缩

## 系统架构

```
Telegram MTProto
    ├── TelethonClient (Account #1)
    ├── TelethonClient (Account #2)
    └── TelethonClient (Account #N)
            │
            ▼
      MessageRouter → KeywordFilter → MonitorService
                                          │
                                    ┌─────┴─────┐
                                    ▼           ▼
                                  Redis      MySQL 8
                               (一级缓存)    (持久化)
```

三层代码架构：

| 层级 | 目录 | 职责 |
|------|------|------|
| 数据实体 | `models/` | Pydantic 数据模型、字段校验、序列化 |
| 业务逻辑 | `services/` | Redis 缓存、去重、关键词管理 |
| 数据操作 | `repositories/` | MySQL CRUD、SQL 语句 |

## 目录结构

```
TGMonitor/
├── src/
│   ├── main.py                  # 入口：启动监听
│   ├── auth.py                  # 首次登录认证（生成 session）
│   ├── config/
│   │   ├── settings.py          # 全局配置（.env 加载）
│   │   ├── database.py          # MySQL 异步连接池
│   │   └── redis_client.py      # Redis 客户端管理
│   ├── models/                  # 数据实体（Pydantic）
│   │   ├── message.py           # MonitoredMessage
│   │   ├── keyword.py           # Keyword
│   │   ├── account.py           # MonitorAccount
│   │   └── monitored_chat.py    # MonitoredChat
│   ├── services/                # 业务逻辑层
│   │   ├── monitor_service.py   # 消息记录 + Redis 缓存
│   │   ├── keyword_service.py   # 关键词管理 + 热加载
│   │   ├── account_service.py   # 账号管理
│   │   └── entity_cache_service.py
│   ├── repositories/            # 数据库操作层
│   │   ├── monitor_repository.py
│   │   ├── keyword_repository.py
│   │   ├── account_repository.py
│   │   └── monitored_chat_repository.py
│   ├── handlers/
│   │   └── message_handler.py   # NewMessage 事件处理
│   ├── filters/
│   │   └── keyword_filter.py    # 关键词匹配引擎
│   ├── core/
│   │   ├── client_manager.py    # 多账号客户端管理
│   │   └── message_router.py    # 消息路由
│   ├── scripts/
│   │   └── list_chats.py        # 辅助脚本：列出已加入的群组
│   ├── tests/                   # 测试
│   │   ├── test_repositories.py
│   │   ├── test_services.py
│   │   ├── test_phase4.py
│   │   └── test_phase5_integration.py
│   └── utils/
│       └── logger.py            # 日志系统（loguru）
├── sessions/                    # Telethon session 文件（.gitignore）
├── logs/                        # 日志文件
├── doc/
│   └── TGMONITOR_TECHNICAL_PLAN.md
├── .env                         # 环境变量（.gitignore）
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
├── ecosystem.config.js          # PM2 配置
└── README.md                    # 本文档
```

## 快速开始

### 前置要求

- Python 3.9+
- MySQL 8（需要已有 `hello` 数据库）
- Redis 6+
- Node.js + PM2（进程管理）
- Telegram API 凭证（从 https://my.telegram.org 获取）

### 1. 安装依赖

```bash
cd TGMonitor

# 创建虚拟环境（推荐）
python3 -m venv ../.venv
source ../.venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 PM2（如果尚未安装）
npm install -g pm2
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 填写：

| 配置项 | 说明 |
|--------|------|
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接信息 |
| `REDIS_URL` / `REDIS_DB` | Redis 连接信息 |
| `TG_ACCOUNT_1_PHONE` | Telegram 手机号（含国际区号） |
| `TG_ACCOUNT_1_API_ID` | Telegram API ID |
| `TG_ACCOUNT_1_API_HASH` | Telegram API Hash |
| `TG_ACCOUNT_1_SESSION_NAME` | Session 文件名（如 `account_1`） |

多账号配置：复制 `TG_ACCOUNT_1_*` 系列为 `TG_ACCOUNT_2_*`，以此类推。

### 3. 创建数据库表

在 MySQL 中执行建表语句（4 张表 + 种子关键词），详见 [TGMONITOR_TECHNICAL_PLAN.md](doc/TGMONITOR_TECHNICAL_PLAN.md) 第 6、8 节，或在项目首次启动后手动执行：

```bash
cd src && python3 -c "
import asyncio
from config.database import init_pool, close_pool
asyncio.run(init_pool())
print('Tables should already exist from Phase 1 setup')
asyncio.run(close_pool())
"
```

> 数据库表以 `tgm_` 前缀命名（`tgm_message`、`tgm_keyword`、`tgm_account`、`tgm_monitored_chat`），与 bot 项目的表完全隔离。

### 4. 认证 Telegram 账号

```bash
cd src && python3 auth.py
```

按提示操作：
1. 选择要认证的账号（从 `.env` 读取）
2. 输入 Telegram 发送的**验证码**
3. 如有两步验证，输入**两步验证密码**（非验证码）
4. 认证成功后 session 文件保存在 `sessions/` 目录

### 5. 配置监听群组

先查看账号已加入的群组：

```bash
cd src && python3 scripts/list_chats.py
```

输出示例：

```
📋 已加入的群组和频道:
  chat_id           | type       | members | title
  -5026789353       | group      |       5 | Testing
  -529631173        | supergroup |   12000 | Dapp-Learning
```

将需要监听的群组配置到 `.env`：

```bash
# 格式: chat_id:群名:类型（逗号分隔多个）
TG_MONITOR_CHATS=-5026789353:Testing:group,-529631173:Dapp-Learning:supergroup
```

### 6. 启动监听

**方式 A: 直接运行（调试用）**

```bash
cd src && python3 main.py
```

**方式 B: PM2 守护进程（推荐）**

```bash
cd TGMonitor && pm2 start ecosystem.config.js
```

启动成功后你将看到：

```
✅ TGMonitor is running!
   Clients: 1/1 connected
```

## PM2 常用命令

```bash
# 查看状态
pm2 status

# 查看实时日志
pm2 logs tg-monitor

# 重启
pm2 restart tg-monitor

# 停止
pm2 stop tg-monitor

# 删除进程
pm2 delete tg-monitor

# 开机自启
pm2 startup
pm2 save
```

## 关键词管理

关键词存储在 `tgm_keyword` 表中，支持三种匹配模式：

| match_type | 说明 | 示例 |
|-----------|------|------|
| `exact` | 精确匹配（大小写不敏感，词边界） | `TGMonitor` 匹配 "I like TGMonitor" |
| `regex` | 正则表达式 | `re[-_]?linx` 匹配 "re-linx" |
| `fuzzy` | 包含匹配（大小写不敏感） | `gift card` 匹配 "cheap Gift Cards" |

关键词分类及优先级：

| category | priority | 说明 |
|----------|----------|------|
| `brand` | 100 | 品牌直接相关 |
| `risk` | 90 | 风控/欺诈 |
| `competitor` | 70 | 竞品名称 |
| `product` | 50 | 产品/商品 |
| `affiliate` | 40 | 推广体系 |
| `payment` | 30 | 支付相关 |

**添加关键词**（直接操作 MySQL）：

```sql
INSERT INTO tgm_keyword (word, category, match_type, priority, is_active)
VALUES ('new_keyword', 'brand', 'exact', 100, 1);
```

修改后无需重启服务，系统每 5 分钟自动重新加载（可通过 `KEYWORD_RELOAD_INTERVAL` 配置）。

## 日志文件

```
logs/
├── app.log           # 全量日志（DEBUG 及以上）
├── error.log         # 仅 ERROR 级别
├── message.log       # 捕获的消息记录专用日志
├── pm2-out.log       # PM2 标准输出
└── pm2-error.log     # PM2 错误输出
```

日志轮转：单文件最大 10MB，保留 5 个备份，自动压缩。

## Redis Key 设计

所有 Key 使用 `monitor:` 前缀，与 bot 项目隔离：

| Key 模式 | 类型 | 说明 |
|---------|------|------|
| `monitor:msg:id:{id}` | STRING | 消息 JSON 缓存 |
| `monitor:msg:chat:{chat_id}` | SET | 群组消息 ID 索引 |
| `monitor:msg:sender:{sender_id}` | SET | 发送者消息 ID 索引 |
| `monitor:msg:category:{cat}` | SET | 分类消息 ID 索引 |
| `monitor:dedup:{chat_id}:{msg_id}` | STRING | 消息去重标记（TTL 7 天） |
| `monitor:keyword:all` | HASH | 全部关键词缓存 |
| `monitor:keyword:reload` | STRING | 上次加载时间 |
| `monitor:entity:user:{id}` | STRING | 用户信息缓存（TTL 24h） |
| `monitor:entity:chat:{id}` | STRING | 群组信息缓存（TTL 24h） |

## 数据库表

| 表名 | 说明 |
|------|------|
| `tgm_message` | 监听到的消息记录 |
| `tgm_keyword` | 关键词配置 |
| `tgm_account` | 监听账号配置 |
| `tgm_monitored_chat` | 被监听群组配置 |

## 测试

```bash
cd src

# 运行阶段 2 Repository 测试
python3 -m tests.test_repositories

# 运行阶段 3 Service 测试
python3 -m tests.test_services

# 运行阶段 4 核心模块测试
python3 -m tests.test_phase4

# 运行阶段 5 集成测试（需要已认证的 Telegram 账号）
python3 -m tests.test_phase5_integration
```

## 运维指南

### 添加新监听账号

1. 在 `.env` 中添加 `TG_ACCOUNT_N_*` 配置
2. 运行 `python3 src/auth.py` 完成认证
3. 重启服务：`pm2 restart tg-monitor`

### 添加新监听群组

1. 用监听账号 **手动加入** 目标群组
2. 运行 `python3 src/scripts/list_chats.py` 获取 `chat_id`
3. 在 `.env` 的 `TG_MONITOR_CHATS` 中追加新群组
4. 重启服务：`pm2 restart tg-monitor`

### 清除 Redis 缓存

```bash
redis-cli -n 1 KEYS "monitor:*" | xargs redis-cli -n 1 DEL
```

### 账号被封处理

1. 在 `tgm_account` 表中将该账号 `is_active` 设为 `0`
2. 新注册账号后添加到 `.env` 并认证
3. 重启服务

### 查看监听统计

```sql
-- 按群组统计消息数
SELECT chat_title, COUNT(*) as msg_count
FROM tgm_message
GROUP BY chat_title
ORDER BY msg_count DESC;

-- 按关键词分类统计
SELECT keyword_category, COUNT(*) as hit_count
FROM tgm_message
GROUP BY keyword_category
ORDER BY hit_count DESC;

-- 最近 24 小时消息
SELECT * FROM tgm_message
WHERE created_at > NOW() - INTERVAL 24 HOUR
ORDER BY created_at DESC
LIMIT 50;
```

## 性能指标

| 指标 | 实测值 |
|------|--------|
| 消息写入吞吐 | **327 msg/s**（Phase 5 压力测试） |
| 消息处理延迟 | < 500ms |
| 内存占用 | ~57MB（单进程运行） |
| 支持群组数 | 单账号 500+，多账号无上限 |

## 技术栈

| 组件 | 版本 |
|------|------|
| Python | 3.9+ |
| Telethon | ≥ 1.36 |
| aiomysql | ≥ 0.2.0 |
| redis-py (async) | ≥ 5.0 |
| pydantic | ≥ 2.0 |
| loguru | ≥ 0.7 |
| python-dotenv | ≥ 1.0 |
| PM2 | latest |

## 许可

内部项目，仅限 TGMonitor 团队使用。
