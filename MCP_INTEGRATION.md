# MCP_INTEGRATION.md · 麦当劳 MCP 集成说明

本文件说明 `taste-memory-skill`（参赛项目）**真实使用**的麦当劳 MCP 能力：接入的 Server、调用的 Tool、调用流程与业务价值。

## 1. 接入的麦当劳 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（`streamablehttp`） |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCD_MCP_TOKEN>` |
| Token 来源 | 环境变量 `MCD_MCP_TOKEN`（仅占位符，不含真实密钥） |
| 频率限制 | 每 Token 每分钟 ≤ 600 次（超出返回 429） |
| 错误码 | `401` Token 无效/过期；`429` 触发限流 |

> 配置示例见仓库根目录 `mcp-config.example.json`；Token 申请方式见 [麦当劳 MCP Server 使用指南](https://github.com/M-China/mcd-mcp-server)。

## 2. 实际调用的 Tool

本项目在推荐引擎中取**实时麦当劳菜单与营养**作为数据源，真实调用以下两个 Tool：

| Tool | 用途 | 在本项目中的消费方式 |
|---|---|---|
| `query-meals` | 查询当前门店可售餐品菜单（分类、餐品编码、标签） | 拉取实时菜品清单，作为个性化推荐的真实候选集 |
| `list-nutrition-foods` | 查询常见餐品营养成分（能量/蛋白质/脂肪/碳水/钠/钙） | 辅助口味/健康维度判断与忌口提示（调用失败时不影响菜单推荐） |

候选集经 `recommend/mcd_client.py` 归一化（菜名、标签、启发式口味维度、粗判过敏原）后，交给推荐引擎结合用户的口味档案与饮食限制做筛选与排序。

> **诚实标注**：菜单的「口味维度（酸/甜/辣/麻/清淡/咸香）」是用菜名/标签/营养推导的**启发式**，并非麦当劳官方口味标签；过敏原为基于菜名关键词的**保守粗判**（仅当确知含该原料时标记）。这两点已在代码注释与 README 中如实说明，不夸大。

## 3. 调用流程

```
用户自然语言
   │
   ▼
WorkBuddy Agent（已启用 mcd-mcp 连接器 + 本 Skill）
   │
   ├─(A) 推荐场景：本 Skill 的 recommend_dish / generate_weekly_menu
   │        │
   │        ▼
   │     recommend/engine.py → get_menu_source()
   │        │
   │        ├─ 配置了有效 MCD_MCP_TOKEN 且连接成功
   │        │     → recommend/mcd_client.py 调 query-meals(+list-nutrition-foods)
   │        │     → 实时麦当劳菜单（data_source="mcd_mcp"）
   │        │
   │        └─ 未配置 Token / 连接失败 / 超时
   │              → 透明回退到内置离线示例目录（data_source="offline_demo"，结果如实标注）
   │
   └─(B) 点餐/优惠/活动场景（可选扩展）：Agent 直接调用 mcd-mcp 的
         calculate-price / create-order / available-coupons / campaign-calendar 等，
         结合本 Skill 的口味档案给出「既好吃又划算」的建议
```

要点：
- **真实使用**：当 `MCD_MCP_TOKEN` 已配置且 mcd-mcp 可达时，推荐结果 100% 来自麦当劳 MCP 实时数据。
- **绝不伪造**：未连接麦当劳 MCP 时，结果明确标注 `data_source="offline_demo"`，不会把离线示例伪装成实时麦当劳数据（符合活动规则与隐私约束）。
- **限流友好**：live 拉取设 4s 墙钟超时；推荐整体 2s 预算（见 `core/config.py`），避免挂起。

## 4. 业务价值

- **个性化而非千篇一律**：把「用户学习到的口味偏好 + 饮食限制/过敏」叠加到麦当劳**实时菜单**上，输出真正贴合个人的推荐（如「对花生过敏、偏好辣味」→ 排除含花生单品、优先麦辣系列）。
- **安全合规**：过敏/忌口在推荐阶段即过滤，降低误点风险；写入类操作（记录用餐/改偏好）必须两段式确认，不静默写入。
- **创意延展**：可作为「麦门省钱助手 / 麦麦活动推荐助手」的记忆与决策底座——记住你爱吃什么、不吃什么，再结合 mcd-mcp 的优惠与活动数据给出最优建议。
