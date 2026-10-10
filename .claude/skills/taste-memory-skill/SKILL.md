---
name: taste-memory-skill
description: 当用户提到"今天吃什么""推荐个菜""记录这顿饭""我不吃xx""对xx过敏""安排一周菜单"等与个人口味、饮食限制、用餐记录相关的请求时触发。该 Skill 会读取用户口味档案、饮食限制和用餐历史，给出个性化推荐，并支持记录用餐和更新偏好。
---

# taste-memory-skill · 个人口味助手

读取并学习用户的口味偏好、饮食限制与用餐历史，给出个性化菜品推荐，而非千篇一律的菜谱列表。
数据默认存储在本地 SQLite，不上云、不联网、不存储任何凭据。

## 执行步骤（概览）

1. 判断用户意图属于哪类工具（见下方「工具路由」）。
2. 只读类请求：直接调用对应查询工具，拿到结果后回答。
3. 写入类请求（记录/改偏好/标记忌口）：**先调一次拿到确认话术，把话术原样交给用户，等用户说"确认"后再带 `confirmed=true` 与 `pending_id` 调第二次**。未确认绝不写入。
4. 推荐类请求：调用推荐工具；若返回 `EMPTY_NEEDS_INPUT`，停下并请用户先记录几餐或放宽条件，**不要自动重试**。

## 工具路由（每个工具的唯一触发条件）

| 用户意图 | 调用工具 | 是否需确认 |
|---|---|---|
| 看我的口味档案 | `get_taste_profile` | 否 |
| 我不能吃/忌口什么 | `query_dietary_restrictions` | 否 |
| 翻翻我吃过什么 | `query_meal_history` | 否 |
| 记录这顿饭 / 我刚吃了 X | `record_meal` | **是** |
| 把 X 维度调高/调低 | `update_preference` | **是** |
| 我再也不吃 X / 标记忌口 | `mark_dislike` | **是** |
| 今天吃什么 / 推荐个菜 | `recommend_dish` | 否 |
| 安排一周菜单 | `generate_weekly_menu` | 否 |
| X 过敏/忌口，拿什么替代 | `suggest_substitute` | 否 |

## 写入类工具的确认流程（硬性）

所有写入工具（`record_meal` / `update_preference` / `mark_dislike`）采用两段式：

- 第一次调用（不带 `confirmed`）返回：
  `{"status": "NEEDS_CONFIRMATION", "pending_id": "<稳定句柄>", "hint": "<确认话术>"}`
- **必须**把 `hint` 原样说给用户，然后停下等待。用户的任何进一步自然语言都不要被当成“已确认写入”。
- 用户明确确认后，第二次调用带上 `confirmed=true` 和第一次返回的同一个 `pending_id`，才真正写入。
- 同一 `pending_id` 重复调用是幂等 no-op（不会写两次）；`pending_id` 过期或缺失会返回 ERROR，需重新发起。

确认话术示例：
> 我将记录你刚吃的[菜品]，评分[评分]，场景[场景]，确认吗？

## 异常处理

- **数据库为空**：查询工具返回空列表不报错；推荐工具返回 `EMPTY_NEEDS_INPUT`，提示用户先记录几餐。不要试图“修复”空库。
- **推荐结果为空**：返回 `EMPTY_NEEDS_INPUT` 并建议放宽条件（去掉部分排除项、允许近期吃过、或先记录）。
- **上游/存储报错**：工具返回 `{"status": "ERROR", ...}`，如实告诉用户，不得假装成功，也不得用模拟数据填充。

## 防循环纪律（关键，务必遵守）

本 Skill 的服务端已把“停止条件 / 超时 / 幂等”做成硬边界，但你作为驱动 Agent 仍需遵守以下纪律，否则仍可能无谓空转：

1. **单轮调用预算 ≤ 8 次工具调用。** 超出即停，向用户总结已做的事。
2. **遇到终态即停**：任何返回 `NEEDS_CONFIRMATION` / `EMPTY_NEEDS_INPUT` / `ERROR` 的工具，都不要重试或换参数再调；把这些状态当作“本次任务的结束信号”，交还用户。
3. **禁止“记录后自动推荐”链式**：`record_meal` 会顺带更新偏好权重，但**不要**在记录同一步里紧接着自动调用 `recommend_dish`。只在用户明确要求推荐时才推荐。
4. **禁止 fan-out 乱调**：不要一次性把所有查询/推荐工具都调一遍。按“工具路由”表精准选一个。
5. **确认不是猜的**：未拿到 `NEEDS_CONFIRMATION` 的 `pending_id` 前，不得调用写入工具的第二次。

## 与麦当劳 MCP 的协作（真实数据来源）

本 Skill 的推荐结果**真实来自麦当劳 MCP**：当 WorkBuddy 已启用 `mcd-mcp` 连接器、配置了 `MCD_MCP_TOKEN`，
且通过 `MCD_STORE_CODE` 提供门店编码时，推荐引擎会调用 `query-meals`（实时菜单，需门店编码）结合本 Skill 的口味档案做个性化筛选。

- 调用方式为原生 JSON-RPC（`initialize` + `tools/call` 打到 `https://mcp.mcd.cn`），因为 mcp SDK 的 SSE 流封装在 `GET /` 会被 403。详见 `MCP_INTEGRATION.md`。
- 未配置 Token 或门店编码时，推荐工具返回 `data_source="offline_demo"`（离线示例目录），**不会**把离线数据伪装成实时麦当劳数据。
- 点餐/优惠/活动类动作由 mcd-mcp 负责（如 `available-coupons` / `auto-bind-coupons` / `query-order`），不在本 Skill 内重复实现。

详见仓库根 `MCP_INTEGRATION.md`。

## 完整调用示例

### 示例 1：记录一餐（含确认）
用户：「刚吃了麻婆豆腐，辣得真爽，打 5 分，工作日午餐」
- 调用 `record_meal(dishName="麻婆豆腐", rating=5, scene="工作日午餐")` → 返回 `NEEDS_CONFIRMATION` + `pending_id`
- 回复用户确认话术，等待
- 用户：「确认」→ 调用 `record_meal(..., confirmed=true, pending_id="<上面的id>")` → 写入并触发隐式偏好（辣 +0.3）

### 示例 2：个性化推荐
用户：「今晚聚餐推荐个菜，我对花生过敏」
- 调用 `recommend_dish(scene="周末聚餐", excludeItems=[])` → 结果已自动排除含花生的菜（宫保鸡丁/担担面/凉拌花生）
- 直接呈现 Top3 及理由

### 示例 3：空库引导
用户：「今天吃什么」
- 调用 `recommend_dish(scene="工作日午餐")` → 返回 `EMPTY_NEEDS_INPUT`
- 停下并说：「你还没记录过用餐，先告诉我今天吃了什么，我就能越推越准。」
