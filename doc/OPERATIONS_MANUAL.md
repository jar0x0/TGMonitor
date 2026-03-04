# TGMonitor 操作手册

## 使用场景

TGMonitor 是一套 Telegram 群组舆情监听系统。它使用**普通 Telegram 账号**（非 Bot）加入目标群组，实时监听群内消息。当消息命中预设的关键词时，系统会自动捕获消息内容、发送者信息、群组来源，并持久化到 MySQL 数据库。

典型使用场景包括：

| 场景 | 说明 |
|------|------|
| **品牌舆情监控** | 监控社区群组中关于 TGMonitor 品牌的讨论，及时发现正面/负面评价 |
| **风控预警** | 捕获群内 "scam"、"fraud"、"骗"、"不发货" 等关键词，提前发现潜在欺诈讨论 |
| **竞品动态** | 追踪竞品品牌名在社区中的出现频率和讨论内容 |
| **产品反馈** | 监控 "gift card"、"steam"、"netflix" 等产品关键词，了解用户需求和反馈 |
| **推广效果** | 通过 "referral"、"commission"、"推广" 等关键词追踪推广体系的讨论热度 |

---

## 第一部分：系统设置

### 1.1 获取 Telegram API 凭证

每个监听账号都需要一组 API 凭证。

1. 打开浏览器访问 https://my.telegram.org
2. 输入手机号登录（使用你准备用来监听的 Telegram 账号）
3. 点击 **API development tools**
4. 填写应用信息（App title、Short name 随意填写）
5. 记下生成的 **API ID**（纯数字）和 **API Hash**（32 位字母数字）

> ⚠️ 注意：建议使用专门注册的号码作为监听号，**不要使用运营号或个人主号**。监听账号只读不写，不发消息、不回复。

### 1.2 配置环境变量

从模板创建配置文件：

```bash
cd TGMonitor
cp .env.example .env
```

打开 `.env` 文件，按如下说明填写：

#### 数据库配置

```bash
DB_HOST=localhost
DB_PORT=3306
DB_USER=hello
DB_PASSWORD=123456
DB_NAME=hello
```

与 bot 项目共享同一个 MySQL 实例。TGMonitor 的表以 `tgm_` 前缀命名，不会与 bot 的表冲突。

#### Redis 配置

```bash
USE_REDIS=true
REDIS_URL=redis://localhost:6379
REDIS_DB=1
```

与 bot 项目共享同一个 Redis 实例。TGMonitor 的所有 Key 以 `monitor:` 前缀命名，不会冲突。

#### Telegram 账号配置

```bash
# 账号 1
TG_ACCOUNT_1_PHONE=+13239025485
TG_ACCOUNT_1_API_ID=31253936
TG_ACCOUNT_1_API_HASH=ff64cbe3e5972fa9bb913fcd33ab14b8
TG_ACCOUNT_1_SESSION_NAME=account_1
TG_ACCOUNT_1_DISPLAY_NAME=监听号1
```

各字段说明：

| 字段 | 必填 | 说明 |
|------|------|------|
| `PHONE` | 是 | 手机号，含国际区号（如 `+13239025485`、`+8613800138000`） |
| `API_ID` | 是 | 纯数字，从 my.telegram.org 获取 |
| `API_HASH` | 是 | 32 位字符串，从 my.telegram.org 获取 |
| `SESSION_NAME` | 否 | Session 文件名，默认 `account_1`。不含路径和扩展名 |
| `DISPLAY_NAME` | 否 | 备注名称，仅用于日志显示 |

**添加多个账号**：复制上述 5 行，将编号递增：

```bash
# 账号 2
TG_ACCOUNT_2_PHONE=+8613900139000
TG_ACCOUNT_2_API_ID=87654321
TG_ACCOUNT_2_API_HASH=fedcba0987654321fedcba0987654321
TG_ACCOUNT_2_SESSION_NAME=account_2
TG_ACCOUNT_2_DISPLAY_NAME=监听号2
```

规则：编号从 1 开始连续递增。中间不能跳号（有 1、2 就不能跳到 4）。注释掉即可禁用某个账号。

### 1.3 安装依赖

```bash
# 创建 Python 虚拟环境（首次操作）
python3 -m venv ../.venv
source ../.venv/bin/activate

# 安装 Python 包
pip install -r requirements.txt

# 安装 PM2（如果尚未安装）
npm install -g pm2
```

### 1.4 认证 Telegram 账号

配置好 `.env` 后，运行认证脚本：

```bash
cd TGMonitor/src
python3 auth.py
```

**操作流程**：

```
╔══════════════════════════════════════════╗
║   TGMonitor — Telegram 账号认证          ║
╚══════════════════════════════════════════╝

📋 可用账号:
  [1] +13239025485 (监听号1)

请选择要认证的账号 [1-1]: 1

📲 正在向 +13239025485 发送验证码...
请输入收到的验证码: 12345
```

- 如果账号开启了**两步验证 (2FA)**，会额外提示输入两步验证密码：

```
🔐 此账号已开启两步验证（2FA）
   下面要输入的是你设置的两步验证密码，不是刚才的短信验证码。
请输入两步验证密码: ********
```

- 认证成功后：

```
✅ 认证成功！
👤 已认证账号: Supporter (@TGMonitor_supporter)
📁 Session 文件: sessions/account_1.session
```

Session 文件保存在 `sessions/` 目录，后续启动时自动使用，**不需要重复认证**。

> ⚠️ Session 文件等同于登录凭证，请妥善保管，不要提交到 Git。已在 `.gitignore` 中排除。

---

## 第二部分：监控群组

### 2.1 查看已加入的群组

监听账号必须**先手动加入**目标群组（与正常用户一样搜索群名或点击邀请链接加入）。

加入群组后，运行以下命令查看账号所在的所有群组和频道：

```bash
cd TGMonitor/src
python3 scripts/list_chats.py
```

输出示例：

```
================================================================================
  群组 (3 个)
================================================================================
  chat_id              类型          成员     名称
  -------------------- ------------ -------- ------------------------------
  -5026789353          group              5  Testing
  -529631173           supergroup     12000  Dapp-Learning
  -757106573           supergroup      3500  Follo One

================================================================================
  频道 (1 个)
================================================================================
  chat_id              类型          成员     名称
  -------------------- ------------ -------- ------------------------------
  -1003858100250       channel        800    加密貨幣生活消費|TGMonitor

================================================================================
📋 可直接复制到 .env 的配置行:
TG_MONITOR_CHATS=-5026789353:Testing:group,-529631173:Dapp-Learning:supergroup,-757106573:Follo One:supergroup,-1003858100250:加密貨幣生活消費|TGMonitor:channel
================================================================================
```

### 2.2 配置监听群组

将需要监听的群组添加到 `.env` 的 `TG_MONITOR_CHATS` 中：

```bash
# 格式: chat_id:群名:类型
# 多个群组用逗号分隔
# 类型: group / supergroup / channel（省略默认为 supergroup）
TG_MONITOR_CHATS=-5026789353:Testing:group,-529631173:Dapp-Learning:supergroup
```

格式规则：

| 部分 | 说明 | 示例 |
|------|------|------|
| `chat_id` | 群组 ID，由 `list_chats.py` 获取，通常为负数 | `-5026789353` |
| `chat_title` | 群名，仅用于显示，不影响匹配 | `Testing` |
| `chat_type` | 类型，可选值：`group`、`supergroup`、`channel` | `group` |

**启动或重启服务后生效**。系统每 5 分钟会自动刷新群组列表。

### 2.3 动态增减群组

**添加新群组：**

1. 用监听账号手动加入那个群组
2. 运行 `python3 scripts/list_chats.py` 找到新群组的 `chat_id`
3. 在 `.env` 的 `TG_MONITOR_CHATS` 后面追加 `,chat_id:群名:类型`
4. 重启服务：`pm2 restart tg-monitor`

**停止监听某个群组：**

在 `.env` 的 `TG_MONITOR_CHATS` 中删掉对应群组段，然后重启服务。

**也可以在数据库中操作**（无需修改 .env）：

```sql
-- 启用/禁用群组（不需要重启，5 分钟内自动生效）
UPDATE tgm_monitored_chat SET is_active = 0 WHERE chat_id = -5026789353;
UPDATE tgm_monitored_chat SET is_active = 1 WHERE chat_id = -5026789353;

-- 查看所有已配置的群组
SELECT id, chat_id, chat_title, chat_type, is_active, assigned_account_phone
FROM tgm_monitored_chat ORDER BY id;
```

---

## 第三部分：监控关键词

### 3.1 关键词匹配模式

系统支持三种匹配模式：

| match_type | 名称 | 匹配逻辑 | 适用场景 |
|-----------|------|---------|---------|
| `exact` | 精确匹配 | 大小写不敏感，匹配完整单词（词边界） | 品牌名、专有名词 |
| `regex` | 正则匹配 | 正则表达式，大小写不敏感 | 变体写法、复杂模式 |
| `fuzzy` | 模糊匹配 | 大小写不敏感，只要文本中**包含**关键词即命中 | 短语、中文词汇 |

匹配示例：

```
关键词: "TGMonitor", match_type: exact
  ✅ "I love TGMonitor"          → 命中（完整词）
  ✅ "TGMonitor is great"        → 命中（大小写不敏感）
  ❌ "TGMonitoryz"               → 不命中（不是完整词）

关键词: "re[-_]?linx", match_type: regex
  ✅ "re-linx"                → 命中
  ✅ "re_linx"                → 命中
  ✅ "TGMonitor"                 → 命中

关键词: "gift card", match_type: fuzzy
  ✅ "cheap Gift Cards here"  → 命中（包含，大小写不敏感）
  ✅ "buy a gift card"        → 命中
  ❌ "gifted a card"          → 不命中（不包含 "gift card" 连续字串）
```

### 3.2 关键词分类与优先级

每个关键词有一个 `category`（分类）和 `priority`（优先级）。当一条消息同时命中多个关键词时，系统取 **优先级最高** 的分类作为该消息的 `keyword_category`。

| category | 推荐 priority | 用途 |
|----------|:----------:|------|
| `brand` | 100 | 品牌直接提及（TGMonitor、re-linx 等） |
| `risk` | 90 | 风控/欺诈相关（scam、fraud、骗、不发货） |
| `competitor` | 70 | 竞品品牌名 |
| `product` | 50 | 产品/商品名（gift card、steam、netflix） |
| `affiliate` | 40 | 推广体系（commission、referral、推广） |
| `payment` | 30 | 支付相关（USDT、TRC20、充值） |

### 3.3 查看当前关键词

```sql
SELECT id, word, category, match_type, priority, is_active
FROM tgm_keyword
ORDER BY priority DESC, category, word;
```

输出示例：

```
+----+-----------+----------+------------+----------+-----------+
| id | word      | category | match_type | priority | is_active |
+----+-----------+----------+------------+----------+-----------+
|  1 | TGMonitor    | brand    | exact      |      100 |         1 |
|  2 | re-linx   | brand    | exact      |      100 |         1 |
|  3 | re_linx   | brand    | exact      |      100 |         1 |
|  4 | scam      | risk     | fuzzy      |       90 |         1 |
|  5 | fraud     | risk     | fuzzy      |       90 |         1 |
|  6 | chargeback| risk     | fuzzy      |       90 |         1 |
|  7 | 骗        | risk     | fuzzy      |       90 |         1 |
|  8 | 不发货    | risk     | fuzzy      |       90 |         1 |
|  9 | fake      | risk     | fuzzy      |       80 |         1 |
| 10 | gift card | product  | fuzzy      |       50 |         1 |
| 11 | game key  | product  | fuzzy      |       50 |         1 |
| 12 | netflix   | product  | fuzzy      |       50 |         1 |
| 13 | spotify   | product  | fuzzy      |       50 |         1 |
| 14 | steam     | product  | fuzzy      |       50 |         1 |
| 15 | USDT      | payment  | exact      |       30 |         1 |
| 16 | TRC20     | payment  | exact      |       30 |         1 |
+----+-----------+----------+------------+----------+-----------+
```

### 3.4 添加关键词

```sql
-- 添加一个精确匹配关键词
INSERT INTO tgm_keyword (word, category, match_type, priority, is_active)
VALUES ('new_brand', 'brand', 'exact', 100, 1);

-- 添加一个正则匹配关键词
INSERT INTO tgm_keyword (word, category, match_type, priority, is_active)
VALUES ('re[-_.]?linx', 'brand', 'regex', 100, 1);

-- 添加一个模糊匹配的中文关键词
INSERT INTO tgm_keyword (word, category, match_type, priority, is_active)
VALUES ('退款', 'risk', 'fuzzy', 90, 1);

-- 批量添加竞品关键词
INSERT INTO tgm_keyword (word, category, match_type, priority, is_active) VALUES
('competitor_a', 'competitor', 'exact', 70, 1),
('competitor_b', 'competitor', 'exact', 70, 1),
('competitor_c', 'competitor', 'fuzzy', 70, 1);
```

> 💡 **无需重启服务**。系统默认每 5 分钟自动检查关键词变化并重新加载。可通过 `.env` 中 `KEYWORD_RELOAD_INTERVAL` 调整间隔（单位：秒）。

### 3.5 修改关键词

```sql
-- 修改匹配模式
UPDATE tgm_keyword SET match_type = 'fuzzy' WHERE word = 'TGMonitor';

-- 调整优先级
UPDATE tgm_keyword SET priority = 95 WHERE word = 'chargeback';

-- 修改分类
UPDATE tgm_keyword SET category = 'risk' WHERE word = 'fake';
```

### 3.6 禁用/启用关键词

```sql
-- 暂时禁用（不删除）
UPDATE tgm_keyword SET is_active = 0 WHERE word = 'USDT';

-- 重新启用
UPDATE tgm_keyword SET is_active = 1 WHERE word = 'USDT';

-- 批量禁用某分类下的所有关键词
UPDATE tgm_keyword SET is_active = 0 WHERE category = 'payment';
```

### 3.7 删除关键词

```sql
DELETE FROM tgm_keyword WHERE word = 'old_keyword' AND category = 'brand';
```

---

## 第四部分：启动与停止

### 4.1 使用 PM2 启动（推荐）

```bash
cd TGMonitor
pm2 start ecosystem.config.js
```

启动成功后日志输出：

```
✅ MySQL connection pool initialized
✅ Redis client initialized
🔄 Loaded 16 active keywords to Redis
📋 Found 1 active account(s)
📋 Monitored chat IDs loaded: 2 groups
🚀 Starting 1 account client(s)...
✅ Client connected: phone=+13239025485, session=account_1
✅ TGMonitor is running!
   Clients: 1/1 connected
```

### 4.2 常用 PM2 命令

```bash
# 查看进程状态
pm2 status

# 查看实时日志
pm2 logs tg-monitor

# 查看最近 100 行日志
pm2 logs tg-monitor --lines 100

# 重启（修改 .env 后需要重启）
pm2 restart tg-monitor

# 停止
pm2 stop tg-monitor

# 删除进程
pm2 delete tg-monitor

# 设置开机自启
pm2 startup
pm2 save
```

### 4.3 直接运行（调试用）

```bash
cd TGMonitor/src
python3 main.py
```

按 `Ctrl+C` 可优雅停止。

---

## 第五部分：查询监控结果

所有被关键词命中的消息都存储在 `tgm_message` 表中。以下是常用查询。

### 5.1 查看最新捕获的消息

```sql
-- 最近 20 条消息
SELECT
    id,
    chat_title AS '群组',
    sender_username AS '发送者',
    LEFT(message_text, 80) AS '消息内容',
    keyword_category AS '分类',
    matched_keywords AS '命中关键词',
    message_date AS '消息时间'
FROM tgm_message
ORDER BY created_at DESC
LIMIT 20;
```

### 5.2 按群组查询

```sql
-- 查看某个群组的所有捕获消息
SELECT
    sender_display_name AS '发送者',
    LEFT(message_text, 100) AS '内容',
    matched_keywords AS '关键词',
    keyword_category AS '分类',
    message_date AS '时间'
FROM tgm_message
WHERE chat_title = 'Dapp-Learning'
ORDER BY message_date DESC
LIMIT 50;
```

### 5.3 按关键词分类查询

```sql
-- 查看所有风控相关消息
SELECT
    chat_title AS '群组',
    sender_username AS '发送者',
    LEFT(message_text, 100) AS '内容',
    matched_keywords AS '命中关键词',
    message_date AS '时间'
FROM tgm_message
WHERE keyword_category = 'risk'
ORDER BY message_date DESC
LIMIT 50;
```

### 5.4 按时间范围查询

```sql
-- 最近 24 小时的消息
SELECT * FROM tgm_message
WHERE created_at > NOW() - INTERVAL 24 HOUR
ORDER BY created_at DESC;

-- 指定日期范围
SELECT * FROM tgm_message
WHERE message_date BETWEEN '2026-03-01' AND '2026-03-04'
ORDER BY message_date DESC;
```

### 5.5 搜索特定关键词命中

```sql
-- 查看哪些消息命中了 "TGMonitor"
SELECT
    chat_title AS '群组',
    sender_display_name AS '发送者',
    LEFT(message_text, 100) AS '内容',
    message_date AS '时间'
FROM tgm_message
WHERE JSON_CONTAINS(matched_keywords, '"TGMonitor"')
ORDER BY message_date DESC;
```

### 5.6 按发送者查询

```sql
-- 查看某个用户的所有被捕获消息
SELECT
    chat_title AS '群组',
    LEFT(message_text, 100) AS '内容',
    keyword_category AS '分类',
    message_date AS '时间'
FROM tgm_message
WHERE sender_username = 'some_user'
ORDER BY message_date DESC;
```

### 5.7 统计分析

```sql
-- 按群组统计消息数量
SELECT
    chat_title AS '群组',
    COUNT(*) AS '捕获消息数'
FROM tgm_message
GROUP BY chat_title
ORDER BY COUNT(*) DESC;

-- 按关键词分类统计
SELECT
    keyword_category AS '分类',
    COUNT(*) AS '数量'
FROM tgm_message
GROUP BY keyword_category
ORDER BY COUNT(*) DESC;

-- 按天统计消息趋势
SELECT
    DATE(message_date) AS '日期',
    COUNT(*) AS '数量'
FROM tgm_message
GROUP BY DATE(message_date)
ORDER BY DATE(message_date) DESC
LIMIT 30;

-- 最活跃的发送者（触发关键词最多的用户）
SELECT
    sender_username AS '用户',
    sender_display_name AS '显示名',
    COUNT(*) AS '触发次数'
FROM tgm_message
WHERE sender_username IS NOT NULL
GROUP BY sender_username, sender_display_name
ORDER BY COUNT(*) DESC
LIMIT 20;

-- 各群组 × 各分类的交叉统计
SELECT
    chat_title AS '群组',
    keyword_category AS '分类',
    COUNT(*) AS '数量'
FROM tgm_message
GROUP BY chat_title, keyword_category
ORDER BY chat_title, COUNT(*) DESC;
```

### 5.8 查看完整消息详情

```sql
-- 通过 ID 查看完整内容
SELECT
    id,
    telegram_message_id,
    chat_id,
    chat_title,
    sender_id,
    sender_username,
    sender_display_name,
    message_text,
    message_type,
    reply_to_message_id,
    matched_keywords,
    keyword_category,
    monitor_account_phone,
    message_date,
    created_at
FROM tgm_message
WHERE id = 123;
```

---

## 第六部分：日志与排障

### 6.1 日志文件

| 文件 | 内容 | 说明 |
|------|------|------|
| `logs/app.log` | 全量日志 | DEBUG 及以上所有日志 |
| `logs/error.log` | 错误日志 | 仅 ERROR 级别 |
| `logs/message.log` | 消息日志 | 每条被捕获的消息单独记录 |
| `logs/pm2-out.log` | PM2 标准输出 | PM2 托管时的 stdout |
| `logs/pm2-error.log` | PM2 错误输出 | PM2 托管时的 stderr |

日志自动轮转：单文件最大 10MB，保留 5 个备份。

### 6.2 查看实时日志

```bash
# PM2 实时日志
pm2 logs tg-monitor

# 只看错误
pm2 logs tg-monitor --err

# 看最近 200 行
pm2 logs tg-monitor --lines 200 --nostream
```

### 6.3 常见问题

**Q: 服务启动后没有捕获任何消息？**

1. 确认群组已配置：`SELECT * FROM tgm_monitored_chat WHERE is_active=1;`
2. 确认关键词已加载：`SELECT COUNT(*) FROM tgm_keyword WHERE is_active=1;`
3. 看日志是否有 "Monitored chat IDs loaded" 和 "Loaded N active keywords"
4. 在被监听的群里发一条包含关键词的测试消息

**Q: 账号被 Telegram 封禁了？**

1. 在数据库中禁用该账号：`UPDATE tgm_account SET is_active=0 WHERE phone='+xxx';`
2. 注册新号，在 `.env` 中配置新账号
3. 运行 `python3 src/auth.py` 认证新账号
4. 重启服务

**Q: 关键词加了但没有生效？**

- 关键词热加载间隔默认 5 分钟。等几分钟后再试，或重启服务立即生效。
- 检查关键词的 `is_active` 是否为 `1`
- 检查 `match_type` 是否正确（中文建议用 `fuzzy`，英文品牌名用 `exact`）

**Q: 如何清除 Redis 缓存？**

```bash
# 使用 Python（因为 redis-cli 可能不在 PATH）
python3 -c "
import redis
r = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
keys = r.keys('monitor:*')
if keys:
    r.delete(*keys)
    print(f'Deleted {len(keys)} keys')
else:
    print('No monitor keys found')
"
```

---

## 第七部分：系统维护

### 7.1 查看系统状态

```bash
# PM2 进程状态
pm2 status

# 查看账号状态
mysql -u hello -p123456 hello -e "
SELECT phone, display_name, status, is_active, last_connected_at
FROM tgm_account;"

# 查看监控群组
mysql -u hello -p123456 hello -e "
SELECT chat_id, chat_title, chat_type, is_active
FROM tgm_monitored_chat;"

# 运行部署检查
cd TGMonitor
python3 src/scripts/deployment_check.py
```

### 7.2 数据清理

```sql
-- 删除 30 天前的消息（保留近期数据）
DELETE FROM tgm_message WHERE created_at < NOW() - INTERVAL 30 DAY;

-- 查看数据量
SELECT
    COUNT(*) AS '总消息数',
    MIN(message_date) AS '最早消息',
    MAX(message_date) AS '最新消息'
FROM tgm_message;
```

### 7.3 后台定时任务说明

系统在运行时自动执行以下后台任务，**无需手动配置**：

| 任务 | 执行间隔 | 说明 |
|------|:--------:|------|
| 关键词热加载 | 5 分钟 | 检查 MySQL 中关键词是否有变化，有则自动刷新 |
| 群组 ID 刷新 | 5 分钟 | 重新加载活跃群组列表 |
| 健康检查 | 1 分钟 | 检测客户端连接状态，断线时自动重连 |
