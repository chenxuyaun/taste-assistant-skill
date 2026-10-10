# 麦味记忆 · 后续路线规划（ROADMAP）

> 本文件沉淀项目执行规划，作为比赛评审的加分项（展示工程完整度与路线思考）。

## 当前状态一句话

**核心链路已跑通，工程完整度足够，比赛可交付**——真实麦当劳 MCP 接入、9 个 MCP 工具、防死循环两层防护、两段式确认、隐式偏好学习、36 测试全绿。当前短板不在代码，在**交付物呈现**和**时间节点**。

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

5. **冷启动 fallback**——目前未连 MCP 时是静态 `offline_demo` 目录，改为"基于口味档案的规则化推荐"，去掉"demo 感"。
6. **多门店比价**——同菜品跨门店价格/availability 对比，强 demo 亮点（依赖 Token 与 `query-meals` 多门店调用）。
7. **营养数据**——等 Token 权限放开后接入 `list-nutrition-foods`；接不上就写入 Known Limitations，不硬刚。

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
| 三 | 冷启动 fallback 改造 | ⏳ 待做（"继续"推进） |
| 三 | 多门店比价 | ⏳ 待做 |
| 三 | 营养数据接入评估 | ⏳ 待做（等 Token 权限） |
