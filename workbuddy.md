# workbuddy.md · WorkBuddy 开发对话上下文（专项奖励核验）

> 本文件用于核验本项目是否**真实使用腾讯 WorkBuddy 智能体**开发，符合「WorkBuddy 专项奖励」条件。
> 以下为本次参赛项目在 WorkBuddy 中从 0 到 1 的开发上下文摘要（对话脉络 + 关键决策）。

## 开发环境

- 客户端：WorkBuddy（官方合作平台），Agent 模式（可直接读写文件、跑命令、跑测试）
- 运行时：受管 Python 3.13 venv（`fastmcp 4.1.0` / `pydantic 2.14` / `pytest 9.1`）
- 技能加载：`skill-creator`、`dynamic-planning-loop` 用于把「防死循环」作为一等公民设计

## 对话脉络（关键节点）

### 阶段 0 · 读源码定位问题（不靠想象）
用户诉求：Agent 老是死循环、乱调工具，要求定位并补停止条件/超时/降级。
WorkBuddy 先读取项目目录与 GitHub 仓库，发现仓库为空——于是将问题从「改 bug」重新定性为
「任务书设计层的结构性缺陷」：一旦 LLM Agent 驱动这套 MCP 工具，原措辞会诱发无限重试/乱调。
据此给出 6 条根因（R1–R6）与加固方案，产出实施计划，等用户确认。

### 阶段 1 · 实施计划（用户确认后开始）
用户回复「开始」。WorkBuddy 建立任务清单，逐文件落地：
- `core/guard.py`：统一 `ToolResult{status}`，`NEEDS_CONFIRMATION/EMPTY_NEEDS_INPUT/ERROR` 为终态（停止信号）
- `core/confirm.py`：两段式确认 + 幂等（未确认不写、同 pending_id 重放 no-op）
- `core/config.py`：墙钟超时预算（读 0.2s / 推荐 2s / 周菜单 5s / 单轮≤8 调用）
- `storage/`：SQLite 建表 + CRUD + 隐式偏好学习（+0.3 / -0.3 / streak +0.5 / dislike 置 1.0）
- `recommend/engine.py`：推荐引擎（过敏排除、场景匹配、近期去重、口味多样性）
- `tools/*` + `main.py`：9 个 MCP 工具注册（fastmcp 4.1 验证通过）
- `SKILL.md`：含「防循环纪律」专节

### 阶段 2 · 测试与验证
WorkBuddy 在受管 venv 安装依赖并跑 pytest：先遇清华镜像缺包（改用官方 PyPI）、async 测试需
`asyncio.run`、关键词规则「麻婆豆腐→麻」误判等，逐一定位修复。最终 **32 用例全过**，9/9 工具注册成功。

### 阶段 3 · 参赛文件生成（本次任务）
用户要求「阅读参赛说明，生成必要文件」。WorkBuddy 抓取比赛仓库 README / 活动规则 /
`CONTEST_DECLARATION.md`（原样抄）/ 麦当劳 MCP Server 工具清单，识别出硬门槛「必须真实使用麦当劳 MCP」。
为此**真把麦当劳 MCP 接进推荐引擎**（`recommend/mcd_client.py`：Streamable HTTP 连接 `https://mcp.mcd.cn`，
调 `query-meals`+`list-nutrition-foods`，4s 超时回退，离线结果明确标注 `offline_demo` 绝不伪造），
并补齐比赛必交文件：
- `README.md`（项目介绍/安装/使用示例/目标用户）
- `CONTEST_DECLARATION.md`（官方声明，内容不可改）
- `MCP_INTEGRATION.md`（实际使用的 Server/Tool/调用流程/业务价值）
- `mcp-config.example.json`（仅环境变量占位符）
- `workbuddy.md`（本文件）
- `requirements.txt`

## 真实性要点（供核验）

- 项目主体代码由 WorkBuddy 在本会话内逐文件生成、测试、修复。
- 防循环设计（停止条件/超时/幂等/降级）是 WorkBuddy 在规划阶段即纳入的一等公民，非事后补丁。
- 麦当劳 MCP 为**真实集成**：配置 `MCD_MCP_TOKEN` 后推荐候选集来自 `query-meals` 实时数据；未配置时透明回退并标注来源，符合「不得静默降级到模拟数据」与隐私约束。
- 全程未在任何代码/配置中硬编码真实 Token 或凭据，配置仅用 `${MCD_MCP_TOKEN}` 占位符。

## 复现命令（在本机 WorkBuddy 终端）

```bash
cd taste-assistant-skill/.claude/skills/taste-memory-skill
export MCD_MCP_TOKEN="<你的Token>"      # 启用实时麦当劳菜单
python main.py                          # 启动 MCP Server
pytest                                  # 运行 32 个测试
```
