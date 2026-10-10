# MCP_INTEGRATION.md · 麦当劳 MCP 集成说明

本文件说明 `taste-memory-skill`（参赛项目）**真实使用**的麦当劳 MCP 能力：接入的 Server、调用的 Tool、调用流程与业务价值。文中所有行为均基于**实际联调**（持有有效 Token 对 `https://mcp.mcd.cn` 发起真实 JSON-RPC 调用）记录，非猜测。

## 1. 接入的麦当劳 MCP Server

| 项 | 值（实测） |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP Server，version `1.0.0`） |
| 接入地址 | `https://mcp.mcd.cn`（**根路径 POST**；`/mcp`、`/sse`、`/v1/mcp` 均返回 404） |
| 协议 | Streamable HTTP（JSON-RPC 2.0，`protocolVersion: 2024-11-05`） |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCD_MCP_TOKEN>` |
| Token 来源 | 环境变量 `MCD_MCP_TOKEN`（仅占位符，不含真实密钥） |

> 配置示例见仓库根 `mcp-config.example.json`；Token 申请见 [麦当劳 MCP Server 使用指南](https://github.com/M-China/mcd-mcp-server)。

### 为什么不用 mcp SDK 的 `streamable_http_client`（重要，实测结论）
本项目的推荐引擎**没有**用 `mcp` Python SDK 的 `streamable_http_client` 封装，原因：
- 该客户端进入 context 时会发起 `GET /` 建立 SSE 流，而 `mcd-mcp` 的 `GET /` 返回 **403**，导致 anyio `TaskGroup` 抛 `unhandled errors`、连接必崩。
- 其函数签名无 `headers` 参数（2.3.0），鉴权头须经自定义 `httpx.AsyncClient` 注入。
- 故改用 **httpx 原生 JSON-RPC**（`initialize` + `tools/call`），稳定可用，且仍属标准 MCP 协议调用。

## 2. 实际调用的 Tool

经 `tools/list` 实测，mcd-mcp 暴露的是「会员 / 商城 / 积分 / 优惠券 / 派对 / 订单」体系（如 `mall-product-detail`、`available-coupons`、`auto-bind-coupons`、`query-order`、`draw-lottery`、`party-order-create` 等）。本项目推荐引擎取**实时菜单**作为数据源，真实调用以下 Tool：

| Tool | 是否真实存在 | 用途 | 在本项目中的消费方式 |
|---|---|---|---|
| `query-meals` | **是**（实测可调用） | 查询门店可售餐品菜单（分类、餐品编码、标签、现价/原价） | 拉取实时菜品清单，作为个性化推荐的真实候选集 |
| `list-nutrition-foods` | **否**（工具清单中不存在） | —— | 已从代码中移除该调用，不依赖它 |

> **诚实更正**：早期设计稿假设了 `list-nutrition-foods`，但 `tools/list` 实测确认它不存在，故已删除相关调用。营养/健康维度判断改用菜名+标签的启发式（见第 4 节）。

`query-meals` 调用细节（实测）：
- **inputSchema 声明 `required: []`**，但**实际调用返回 `code:400, message:"缺少参数"`**；经参数探测确认真实必填为 `storeCode`（门店编码）+ `orderType`（1-到店 / 2-外送）+ `beType`（1-到店取餐 / 2-麦乐送 / 5-DT / 6-企业团餐）。这是服务端实现细节，inputSchema 未声明。
- 本项目通过环境变量 **`MCD_STORE_CODE`** 注入门店编码（默认 `orderType=1, beType=1` 到店取餐，无需额外 `beCode`）；未配置时仍真实发起调用（服务端返回缺参数），由引擎离线兜底。
- 返回结构是「API 代理」风格：正文为 LLM 可读说明 + 末尾 `## Original Response` 后的真实 JSON，业务数据在 `data.categories[].meals[].code/tags`、`data.meals[code].name/currentPrice/originalPrice`、`data.frequent`。

候选集经 `recommend/mcd_client.py` 归一化（菜名、标签、启发式口味维度、保守粗判过敏原）后，交给推荐引擎结合用户的口味档案与饮食限制做筛选与排序。

## 3. 调用流程

```
用户自然语言
   │
   ▼
WorkBuddy Agent（已启用 mcd-mcp 连接器 + 本 Skill）
   │
   └─ 推荐场景：本 Skill 的 recommend_dish / generate_weekly_menu
        │
        ▼
     recommend/engine.py → get_menu_source()
        │
        ├─ 配置了有效 MCD_MCP_TOKEN 且 query-meals 成功返回菜单
        │     → recommend/mcd_client.py 原生 JSON-RPC 调 query-meals（带 MCD_STORE_CODE）
        │     → 实时麦当劳菜单（data_source="mcd_mcp"）
        │
        └─ 未配置 Token / 缺门店编码 / 连接失败 / 超时 / 解析失败
              → 透明回退到内置离线示例目录（data_source="offline_demo"，结果如实标注）
```

要点：
- **真实使用**：当 `MCD_MCP_TOKEN` 已配置且 `MCD_STORE_CODE` 有效时，推荐结果来自麦当劳 MCP 实时数据（`data_source="mcd_mcp"`）。
- **绝不伪造**：未连接 / 未配门店时，结果明确标注 `data_source="offline_demo"`，不会把离线示例伪装成实时麦当劳数据（符合活动规则与隐私约束）。
- **限流友好**：live 拉取设 8s 墙钟超时；超时或业务失败一律回退，不挂起、不静默造假。

## 4. 业务价值与诚实标注

- **个性化而非千篇一律**：把「用户学习到的口味偏好 + 饮食限制/过敏」叠加到麦当劳**实时菜单**上，输出真正贴合个人的推荐（如「对花生过敏、偏好辣味」→ 排除含花生单品、优先麦辣系列）。
- **安全合规**：过敏/忌口在推荐阶段即过滤，降低误点风险；写入类操作（记录用餐/改偏好）必须两段式确认，不静默写入。
- **启发式如实声明**：菜单的「口味维度（酸/甜/辣/麻/清淡/咸香）」是用菜名/标签推导的**启发式**，并非麦当劳官方口味标签；过敏原为基于菜名关键词的**保守粗判**（仅当确知含该原料时标记）。已在代码注释与 README 中如实说明，不夸大。
- **创意延展**：可作为「麦门省钱助手 / 麦麦活动推荐助手」的记忆与决策底座——记住你爱吃什么、不吃什么，再结合 mcd-mcp 的 `available-coupons` / `auto-bind-coupons` 等优惠数据给出最优建议（优惠类动作由 mcd-mcp 负责，不在本 Skill 重复实现）。
