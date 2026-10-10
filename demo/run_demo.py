"""麦味记忆 端到端 Demo 脚本（可一键复现，便于录屏）。

运行：
    python demo/run_demo.py

- 若仓库根 .env 配置了 MCD_MCP_TOKEN，则演示真实麦当劳 MCP（自动定位成都春熙路最近门店 + 实时菜单）。
- 否则演示离线示例（offline_demo），逻辑完全一致，仅候选集不同，并如实标注。
- 使用独立的临时 SQLite（demo/demo_run.db），不污染你的真实口味档案。

演示链路：
  ① 定位 + 拉取菜单
  ② 空档案推荐（应引导先记录，终态不重试）
  ③ 记录几餐，触发隐式学习
  ④ 再推荐（已有档案）
  ⑤ 展示口味权重变化
  ⑥ 连续辣菜触发 streak 奖励（连续高评分同维度 +0.5）
  ⑦ 第三轮推荐，展示「学到了」
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, ".claude", "skills", "taste-memory-skill")
sys.path.insert(0, SKILL_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except Exception:
    pass

from storage import db, preference_learning
from recommend import engine
from core.guard import ToolStatus

DEMO_DB = os.path.join(REPO_ROOT, "demo", "demo_run.db")
os.environ["TASTE_DB_PATH"] = DEMO_DB
if os.path.exists(DEMO_DB):
    os.remove(DEMO_DB)
db.init()


def hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def show_profile() -> None:
    p = db.get_profile() or db.default_profile_dict()
    print("口味维度权重：")
    for k, v in p["dimensions"].items():
        filled = int(round(v))
        bar = "#" * filled + "-" * (5 - filled)
        print(f"  {k:>4} [{bar}] {v:.2f}")
    if p["allergens"]:
        print("  过敏原:", p["allergens"])
    if p["disliked_dishes"]:
        print("  忌口:", p["disliked_dishes"])


def record(name: str, rating: int, scene: str) -> None:
    db.insert_meal(name, rating, scene, "2026-10-10T12:00:00")
    learn = preference_learning.apply_meal_learning(name, rating)
    print(f"  [记录] {name}  评分{rating}（{scene}）")
    if learn["deltas"]:
        print(f"     -> 隐式偏好更新: {learn['deltas']}")
    else:
        print("     -> 该菜未匹配到已知口味维度，权重不变")


def recommend(scene: str):
    res = engine.recommend_dish_sync(scene=scene)
    print(f"  [recommend_dish] status={res.status} source={res.data_source}")
    if res.hint:
        print(f"     hint: {res.hint}")
    if res.status == ToolStatus.OK:
        for i, item in enumerate(res.data, 1):
            print(f"     {i}. {item['dish']}  评分{item['score']}  匹配维度{item['matched_dims']}")
            print(f"        理由: {item['reason']}")
    return res


def main() -> None:
    hr("麦味记忆 · 端到端 Demo")
    token = os.getenv("MCD_MCP_TOKEN")
    print("模式:", "真实麦当劳 MCP（已配置 Token）" if token else "离线示例 offline_demo（未配置 Token，逻辑一致）")

    hr("① 定位 + 拉取菜单")
    catalog, source, store = engine.get_menu_source()
    if store:
        print(f"  定位门店: {store.get('store_name')}（距约 {store.get('distance')} 米）")
    print(f"  数据来源: {source}  候选菜品数: {len(catalog)}")
    print("  示例菜品:", "、".join(d["name"] for d in catalog[:5]), "…")

    hr("② 用户：今天中午吃什么？ -> 推荐（空档案，应引导先记录，终态不重试）")
    recommend("工作日午餐")

    hr("③ 用户：刚吃了几道菜（触发隐式学习）")
    record("白灼菜心", 4, "工作日午餐")
    record("番茄炒蛋", 4, "工作日午餐")

    hr("④ 再推荐（此时已有档案）")
    recommend("工作日午餐")

    hr("⑤ 口味权重变化（记录后）")
    show_profile()

    hr("⑥ 用户又连吃三道辣菜 -> streak 奖励（连续高评分同维度 +0.5）")
    record("辣子鸡", 5, "工作日午餐")
    record("水煮鱼", 5, "工作日午餐")
    record("麻辣火锅", 5, "工作日午餐")
    show_profile()
    print("  preference_log 最近变化：")
    for row in db.get_pref_log(8):
        print(f"    {row['rule']:>12} {row['dimension'] or '':>4} Δ{row['delta']}  {row['reason']}")

    hr("⑦ 第三轮推荐（展示「学到了」：辣味权重更高，辣菜更靠前）")
    recommend("工作日午餐")

    hr("Demo 结束 · 真实链路已跑通，录屏可直接用以上输出")
    print("录屏建议：从 ① 开始到 ⑦ 结束，重点展示 ⑤⑥ 权重变化与 ⑦ 推荐排序变化。")


if __name__ == "__main__":
    main()
