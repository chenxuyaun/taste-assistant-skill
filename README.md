# 麦味记忆 · McDonald's Taste Memory Skill

> 麦当劳程序员创意开发大赛参赛项目 · 基于麦当劳 MCP 的个人口味助手

**麦味记忆** 是一个个人口味助手 Skill：它记住你的口味偏好、饮食限制与用餐历史，并结合**麦当劳 MCP 的实时菜单与营养数据**，给出真正个性化的麦当劳点餐推荐——而不是千篇一律的菜谱列表。

- 隐私优先：口味档案默认存**本地 SQLite**，不上云、不联网、不存任何凭据。
- 真实使用麦当劳 MCP：配置 Token 后，推荐候选集来自 `query-meals` 实时菜单。门店可二选一指定：显式 `MCD_STORE_CODE`，或配 `MCD_CITY`+`MCD_KEYWORD` 自动定位最近门店；未配置时透明回退离线目录并如实标注（详见 `MCP_INTEGRATION.md`）。
- 防死循环设计：停止条件 / 超时 / 幂等 / 降级都在工具边界上做硬，让驱动它的 Agent 不乱调、不空转。

---

## 项目介绍

| 维度 | 说明 |
|---|---|
| 名称 | 麦味记忆（McDonald's Taste Memory Skill） |
| 类型 | MCP 工具集（9 个工具）+ 本地记忆层 + 推荐引擎 |
| 核心能力 | 记录用餐、学习口味、饮食限制管理、个性化麦当劳推荐、周菜单、食材替代 |
| 数据来源 | 用户本地口味档案 + 麦当劳 MCP 实时菜单（live，支持按城市+地标自动定位最近门店）/ 离线示例（fallback） |
| 技术栈 | Python ≥ 3.11、fastmcp、pydantic v2、SQLite |
| 运行形态 | 既可作为独立 MCP Server（`python main.py`），也可作为 WorkBuddy Skill 被 Agent 调用 |

### 目录结构

```
taste-assistant-skill/
├── README.md                      # 本文
├── CONTEST_DECLARATION.md         # 参赛声明（官方文件，不可改）
├── MCP_INTEGRATION.md             # 麦当劳 MCP 集成说明
├── mcp-config.example.json        # 脱敏 MCP 配置示例（仅环境变量占位符）
├── workbuddy.md                   # WorkBuddy 开发对话上下文（专项奖励核验）
└── .claude/skills/taste-memory-skill/
    ├── SKILL.md                   # Skill 定义（含防循环纪律）
    ├── main.py                    # MCP Server 入口
    ├── core/                      # guard（终态/超时）/ confirm（两段式确认）/ config
    ├── models/                    # Pydantic 数据模型
    ├── storage/                   # SQLite 建表 + CRUD + 隐式偏好学习
    ├── recommend/                 # 推荐引擎 + mcd_client（麦当劳 MCP 客户端）
    ├── tools/                     # 9 个 MCP 工具实现
    └── tests/                     # pytest，36 用例全过
```

---

## 安装方法

### 1. 准备 Python 环境（≥ 3.11）

```bash
cd taste-assistant-skill
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # 或：fastmcp pydantic pytest
```

> `requirements.txt` 内容：`fastmcp>=2.0.0`、`pydantic>=2.0.0`、`python-dotenv>=1.0.0`、`httpx>=0.28.0`、`pytest>=8.0.0`。

### 2. 配置麦当劳 MCP Token（推荐，启用实时菜单）

向麦当劳 MCP 申请 Token 后，用环境变量注入（**绝不写入代码/配置明文**）：

```bash
export MCD_MCP_TOKEN="你的_真实_Token"   # Windows: set MCD_MCP_TOKEN=...
```

未配置 Token 时，Skill 仍可运行，但推荐结果会明确标注 `data_source="offline_demo"`（离线示例目录），不会伪装成实时麦当劳数据。

### 3. 在 WorkBuddy 中启用（参赛推荐路径）

1. 左侧栏【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】；
2. 粘贴 `mcp-config.example.json` 内容，把 `${MCD_MCP_TOKEN}` 替换为你的真实 Token（或让 WorkBuddy 读取环境变量），保存并启用 `mcd-mcp`；
3. 将本仓库的 `.claude/skills/taste-memory-skill/` 作为 Skill 加载；
4. 在对话框中用自然语言提出需求即可。

---

## 使用示例

### 示例 1：记录一餐（两段式确认，防误写）

```
用户：刚吃了麦辣鸡腿堡，打 5 分，工作日午餐
→ record_meal(dishName="麦辣鸡腿堡", rating=5, scene="工作日午餐")
  返回 NEEDS_CONFIRMATION + pending_id，话术：「我将记录你刚吃的麦辣鸡腿堡，评分5，场景工作日午餐，确认吗？」
用户：确认
→ record_meal(..., confirmed=true, pending_id="<同上>")
  写入并触发隐式偏好（辣味权重 +0.3）
```

### 示例 2：个性化麦当劳推荐（过敏自动排除）

```
用户：今晚聚餐推荐个麦当劳的菜，我对花生过敏
→ recommend_dish(scene="周末聚餐")
  实时拉取麦当劳菜单 → 过滤含花生单品 → 按口味档案排序 → 返回 Top3 及理由
  返回 data_source="mcd_mcp"（来自麦当劳 MCP 实时数据）
```

### 示例 3：一周麦麦菜单（口味多样性）

```
用户：帮我安排一周麦当劳菜单
→ generate_weekly_menu(days=7, diversityLevel=2)
  返回 7 天不重样、主导口味不连续的菜单，data_source 标明数据来源
```

### 示例 4：忌口替代

```
用户：我对牛奶过敏，拿铁拿什么替代
→ suggest_substitute(originalIngredient="牛奶")
  返回无奶替代建议，且自动避开你的其他过敏原
```

---

## 目标用户

- **麦当劳常客**：想在不重样的前提下，按自己口味高效点餐的人。
- **有饮食限制 / 过敏体质者**：需要推荐阶段就排除花生、鸡蛋、牛奶等过敏原与忌口食材的人。
- **健康管理人群**：基于菜名/标签的启发式口味维度，在偏好与健康之间找平衡。
- **省钱/活动党**：可结合 mcd-mcp 的 `available-coupons` / `auto-bind-coupons`，让记忆层给出「既好吃又划算」的建议。

---

## 防死循环设计（节选）

本项目从设计上杜绝「Agent 死循环 / 乱调工具」：

- 每个工具返回 `ToolResult{status}`，`NEEDS_CONFIRMATION` / `EMPTY_NEEDS_INPUT` / `ERROR` 都是**终态**——Agent 必须停下交还用户。
- 写入类工具采用**两段式确认 + 幂等**：未确认不写；同一 `pending_id` 重放是 no-op。
- 推荐设**墙钟超时**（单菜 2s / 周菜单 5s），超时转 `ERROR`，绝不静默降级到模拟数据。
- `record_meal` 的隐式学习是纯副作用，Server **不反向自动调用推荐**，避免记录→推荐→再记录循环。

详见 `SKILL.md` 的「防循环纪律」专节与 `MCP_INTEGRATION.md`。

---

## 测试

```bash
cd .claude/skills/taste-memory-skill
.venv/Scripts/python.exe -m pytest     # 36 用例全过（含 AC1–AC5 与防循环用例）
```

---

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。
餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准；输出不构成医疗、营养或专业建议。

---

## Demo 一键运行（录屏 / 自测）

```bash
cd taste-assistant-skill
# 可选：在仓库根 .env 配置 MCD_MCP_TOKEN，启用真实麦当劳实时菜单
python demo/run_demo.py
```

脚本跑通完整链路：定位最近门店 → 拉取菜单 → 空档案引导记录 → 记录触发隐式学习 → 推荐 Top3 → 展示权重变化 → 连续辣菜触发 streak 奖励 → 再次推荐展示「学到了」。未配置 Token 时自动走 `offline_demo`，逻辑完全一致，结果如实标注。

---

## Docker 运行（比赛「可运行交付物」口径）

```bash
docker build -t taste-memory .
docker run --rm \
  -e MCD_MCP_TOKEN=你的真实Token \
  -e MCD_CITY=成都市 -e MCD_KEYWORD=春熙路 \
  taste-memory
```

镜像不含任何 Token / 凭据（`.dockerignore` 已排除 `.env`）；Token 通过 `-e` 或 `--env-file` 注入。启动即拉起 MCP Server。
