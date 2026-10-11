# 麦味记忆 · 后续路线规划（ROADMAP）

> 本文件沉淀项目执行规划，作为比赛评审的加分项（展示工程完整度与路线思考）。

## 当前状态一句话

**核心链路已跑通，工程完整度足够，比赛可交付**——真实麦当劳 MCP 接入、11 个 MCP 工具、防死循环两层防护、两段式确认、隐式偏好学习、39 测试全绿。当前短板不在代码，在**交付物呈现**和**时间节点**。

---

## 建议执行顺序

### 第一阶段：锁定比赛交付物

1. **录 demo**——一条完整链路，建议脚本：
   - 用户说"今天中午吃什么" → 定位成都春熙路 → 返回联升巷餐厅（3450410）真实菜单（实测 124 道）
   - AI 结合口味档案推荐 2-3 道 → 用户确认 → 落盘 → 展示偏好权重变化
   - 再来一轮，展示"学到了"的效果（比如辣度权重提升）
   - 配套脚本：`demo/run_demo.py`（一键复现，`python demo/run_demo.py`）
2. **ROADMAP.md 入库**——即本文件，沉淀规划供评审查阅。

### 第二阶段：工程化加固

3. **CI**——`.github/workflows/ci.yml`：`pytest` 全绿 + 用 `monkeypatch` 模拟 MCP 的冒烟测试；真 Token 不进 CI（默认走 `offline_demo`）。
4. **Docker 化**——`Dockerfile` 对齐大赛"可运行交付物"评审口径，`README.md` 补一行 `docker run`；镜像不含 Token（`.dockerignore` 排除 `.env`）。

### 第三阶段：差异化叙事

5. **冷启动 fallback** ✅——空库时不再踢回 `EMPTY_NEEDS_INPUT`，改为返回 `OK` + `cold_start=true` 的规则化试探推荐（中性默认口味 3.0 + 当前菜单排序），带 reason/matched_dims，去掉"demo 感"，且仍是终态（Agent 不重试）。
6. **多门店比价** ✅——新增 `compare_stores` 工具：跨门店同款菜品价格与可下单（`canWithOrder`）状态对比，按省价差排序；同城同价时差异主要在售罄可下单性（如某店售罄、附近店有货），是强 demo 亮点。
7. **营养数据** ✅（评估报告，如实降级）——实测当前比赛 Token 下 `list-nutrition-foods` 返回空（会员/参数限制），已落地 `get_nutrition` 工具并**如实降级**（`EMPTY_NEEDS_INPUT` + 说明原因），能力就绪待权限放开即自动接入；绝不伪造营养数据。

---

## 关键风险提醒

- **Token 别进 CI / 镜像**：`.env` 已 gitignore；CI 用 mock，Docker 用 `-e` 注入，真 Token 只走本地/demo。
- **`normalize_meals` 保持健壮**：麦当劳 MCP 非公开 API，返回结构可能变，解析失败要透明降级（`offline_demo`）不崩。
- **录屏前先跑一遍全链路**：确认 `MCD_STORE_CODE` 留空时能自动定位，避免 demo 现场翻车。
- **营养数据当前 Token 返空**：仅暴露能力、不硬依赖；比赛时间节点——报名/排名截止 **2026-10-25 23:59**，定榜 10-26 00:00，兑奖 11-14。

---

## 进度看板

| 阶段 | 项 | 状态 |
|---|---|---|
| 一 | ROADMAP.md 入库 | ✅ 已完成 |
| 一 | demo 脚本（可复现） | ✅ 已完成 |
| 二 | CI（GitHub Actions + pytest mock） | ✅ 已完成 |
| 二 | Docker 化 + README docker run | ✅ 已完成 |
| 三 | 冷启动 fallback 改造 | ✅ 已完成 |
| 三 | 多门店比价 | ✅ 已完成 |
| 三 | 营养数据接入评估 | ✅ 已完成（如实降级，待权限接入） |

---

## 已知限制（Known Limitations）

- **营养数据**：当前比赛 Token 下 `list-nutrition-foods` 返回空（会员/参数限制）。`get_nutrition` 工具已就绪并如实降级，不会用离线数据伪装官方营养数据；待 Token 权限放开后自动接入。
- **多门店比价依赖真实 Token**：`compare_stores` 需 `MCD_MCP_TOKEN` 且门店编码有效（如 `['3450410','3450339','3450069003']`）；未配置或拉取失败如实转 `EMPTY_NEEDS_INPUT`/`ERROR`。
- **冷启动推荐为中性试探**：空库推荐基于默认口味（各维度 3.0），仅作"先给几个"的引导；个性化需用户记录/评分后才生效（隐式学习已验证：辣度 3.0→4.4 等）。
- **麦当劳 MCP 非公开 API**：返回结构可能变动，`normalize_meals` 保留健壮解析 + 透明降级（`offline_demo`），解析失败不崩。
- **定位为语义定位**：无 GPS 工具，门店选择基于 `MCD_CITY`+`MCD_KEYWORD` 由 `query-nearby-stores` 按距离选最近，非真实经纬度定位。
