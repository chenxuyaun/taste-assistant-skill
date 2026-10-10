"""推荐引擎。纯函数，不依赖 fastmcp，全部返回 ToolResult（便于独立测试）。

知识来源是 DISH_CATALOG——一份**静态、合法的菜品数据库**，绝不是伪造的用户历史。
任何 DB 故障都向上抛出，由工具包装层转成 ERROR（绝不静默造假，R6 / 任务书六）。
"""
from __future__ import annotations

import logging
from typing import Optional

from core.guard import ToolResult, ToolStatus
from storage import db

logger = logging.getLogger("taste-memory.engine")

RECENT_DAYS = 3  # 推荐时规避最近 N 天内吃过的菜（除非用户明确要求）

# 静态菜品知识库：name / 各维度强度 / 场景标签 / 食材 / 过敏原
DISH_CATALOG = [
    {"name": "麻婆豆腐", "dims": {"辣": 5, "麻": 4, "咸香": 3}, "tags": ["share", "spicy"], "ingredients": ["豆腐", "牛肉末"], "allergens": []},
    {"name": "水煮鱼", "dims": {"辣": 5, "麻": 3, "咸香": 2}, "tags": ["share", "spicy"], "ingredients": ["鱼", "辣椒"], "allergens": []},
    {"name": "宫保鸡丁", "dims": {"辣": 4, "咸香": 3}, "tags": ["fast", "share"], "ingredients": ["鸡", "花生"], "allergens": ["花生"]},
    {"name": "凉拌花生", "dims": {"咸香": 3, "辣": 2}, "tags": ["fast"], "ingredients": ["花生"], "allergens": ["花生"]},
    {"name": "糖醋里脊", "dims": {"甜": 4, "酸": 3}, "tags": ["share"], "ingredients": ["猪肉"], "allergens": []},
    {"name": "清蒸鲈鱼", "dims": {"清淡": 5, "咸香": 2}, "tags": ["share"], "ingredients": ["鱼"], "allergens": []},
    {"name": "白灼菜心", "dims": {"清淡": 5}, "tags": ["fast"], "ingredients": ["菜心"], "allergens": []},
    {"name": "皮蛋瘦肉粥", "dims": {"清淡": 4, "咸香": 2}, "tags": ["fast"], "ingredients": ["皮蛋", "猪肉"], "allergens": []},
    {"name": "酸辣土豆丝", "dims": {"酸": 4, "辣": 3}, "tags": ["fast"], "ingredients": ["土豆"], "allergens": []},
    {"name": "红烧肉", "dims": {"咸香": 5, "甜": 2}, "tags": ["share"], "ingredients": ["猪肉"], "allergens": []},
    {"name": "番茄炒蛋", "dims": {"酸": 3, "甜": 2, "咸香": 2}, "tags": ["fast"], "ingredients": ["番茄", "鸡蛋"], "allergens": ["鸡蛋"]},
    {"name": "麻辣火锅", "dims": {"辣": 5, "麻": 5}, "tags": ["share", "spicy"], "ingredients": ["各种"], "allergens": []},
    {"name": "担担面", "dims": {"辣": 4, "麻": 3, "咸香": 3}, "tags": ["fast"], "ingredients": ["面", "花生"], "allergens": ["花生"]},
    {"name": "柠檬鸡", "dims": {"酸": 4, "甜": 2}, "tags": ["share"], "ingredients": ["鸡", "柠檬"], "allergens": []},
    {"name": "拔丝地瓜", "dims": {"甜": 5}, "tags": ["share"], "ingredients": ["地瓜"], "allergens": []},
    {"name": "卤味拼盘", "dims": {"咸香": 5, "麻": 2}, "tags": ["share"], "ingredients": ["牛", "豆干"], "allergens": []},
    {"name": "清炒时蔬", "dims": {"清淡": 5}, "tags": ["fast"], "ingredients": ["蔬菜"], "allergens": []},
    {"name": "辣子鸡", "dims": {"辣": 5, "麻": 3}, "tags": ["share"], "ingredients": ["鸡", "辣椒"], "allergens": []},
    {"name": "酸菜鱼", "dims": {"酸": 4, "辣": 3}, "tags": ["share"], "ingredients": ["鱼", "酸菜"], "allergens": []},
    {"name": "蛋炒饭", "dims": {"咸香": 3, "清淡": 2}, "tags": ["fast"], "ingredients": ["鸡蛋", "米"], "allergens": ["鸡蛋"]},
]

# 常见食材替代库（替代建议本身也会避开用户的过敏/忌口）
SUBSTITUTE_MAP = {
    "花生": ["南瓜子（无花生）", "焙煎芝麻（若无芝麻过敏）", "杏仁碎（若无坚果过敏）"],
    "牛奶": ["豆奶", "椰浆", "燕麦奶"],
    "鸡蛋": ["亚麻籽蛋（烘焙：1tbsp 亚麻籽粉+3tbsp 水≈1蛋）", "嫩豆腐泥"],
    "麸质": ["米粉", "荞麦面（若无荞麦过敏）", "玉米淀粉"],
    "虾": ["鸡肉粒", "豆腐块"],
    "牛肉": ["鸡肉", "豆腐（素食）"],
}


def _profile_or_raise() -> dict:
    p = db.get_profile()
    if p is None:
        p = db.default_profile_dict()  # 有用餐记录但档案恰好为空时的中性兜底
    return p


def get_menu_source() -> tuple[list, str]:
    """返回 (菜品列表, 数据来源)。

    - ``"mcd_mcp"``：来自麦当劳 MCP 的实时菜单（已配置 MCD_MCP_TOKEN 且连接成功）。
    - ``"offline_demo"``：离线示例目录（未连接麦当劳 MCP 时透明回退，结果如实标注）。
    绝不把离线目录伪装成实时麦当劳数据。
    """
    try:
        from recommend import mcd_client
        live = mcd_client.get_live_menu()
        if live:
            return live, "mcd_mcp"
    except Exception as e:  # 极端情况下连导入都失败，安全回退
        logger.warning("麦当劳 MCP 不可用，回退离线目录: %s", e)
    return DISH_CATALOG, "offline_demo"


def dominant(dish: dict) -> Optional[str]:
    if not dish["dims"]:
        return None
    return max(dish["dims"], key=lambda k: dish["dims"][k])


def _score(dish: dict, profile: dict, scene: str, available: set) -> float:
    s = 0.0
    for dim, w in profile["dimensions"].items():
        s += w * dish["dims"].get(dim, 0)
    if scene == "工作日午餐" and "fast" in dish["tags"]:
        s += 2.0
    if scene in ("周末聚餐", "其他") and "share" in dish["tags"]:
        s += 2.0
    if available and (available & set(dish.get("ingredients", []))):
        s += 3.0
    return s


def _matched(dish: dict, profile: dict) -> list:
    return [dim for dim, w in profile["dimensions"].items()
            if dish["dims"].get(dim, 0) >= 4 and w >= 3.5]


def _reason(dish: dict, profile: dict, scene: str, available: set) -> str:
    parts = []
    if "fast" in dish["tags"] and scene == "工作日午餐":
        parts.append("适合工作日快手的菜")
    if "share" in dish["tags"] and scene in ("周末聚餐", "其他"):
        parts.append("适合分享的聚餐菜")
    if available and (available & set(dish.get("ingredients", []))):
        parts.append("优先用了你提供的食材")
    top_dim = dominant(dish)
    if top_dim:
        parts.append(f"契合你偏好的{top_dim}味")
    return "；".join(parts) if parts else "综合匹配度较高"


def recommend_dish_sync(
    scene: str,
    mealTime: Optional[str] = None,
    availableIngredients: Optional[list] = None,
    excludeItems: Optional[list] = None,
    include_recent: bool = False,
) -> ToolResult:
    if not db.has_meaningful_profile():
        # 终态：停下，请用户先记录（不会无限重试，R2/R4）
        return ToolResult(ToolStatus.EMPTY_NEEDS_INPUT, data=[],
                          hint="口味档案或用餐记录为空，请先记录几餐，我再推荐")
    profile = _profile_or_raise()
    available = set(availableIngredients or [])
    exclude = set(excludeItems or [])
    disliked = set(profile["disliked_dishes"])
    allergens = set(profile["allergens"])
    avoid = set(profile["avoid_foods"])
    recent = set() if include_recent else set(db.get_recent_dish_names(RECENT_DAYS))

    catalog, source = get_menu_source()
    candidates = []
    for dish in catalog:
        name = dish["name"]
        if name in exclude or name in disliked:
            continue
        if allergens & set(dish.get("allergens", [])):   # 过敏排除（AC3）
            continue
        if avoid & set(dish.get("ingredients", [])):      # 忌口排除
            continue
        if name in recent:                                # 近期去重
            continue
        candidates.append((_score(dish, profile, scene, available), dish))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:3]
    if not top:
        return ToolResult(ToolStatus.EMPTY_NEEDS_INPUT, data=[],
                          hint="过滤后无候选菜品，建议放宽条件（如去掉部分排除项或允许近期吃过）")
    out = [
        {"dish": d["name"], "score": round(s, 2),
         "matched_dims": _matched(d, profile),
         "reason": _reason(d, profile, scene, available)}
        for s, d in top
    ]
    if source == "offline_demo":
        return ToolResult(ToolStatus.OK, data=out, data_source="offline_demo",
                          hint="当前未连接麦当劳 MCP，以下为离线示例菜品；配置 MCD_MCP_TOKEN 后将基于实时菜单推荐")
    return ToolResult(ToolStatus.OK, data=out, data_source="mcd_mcp")


def _scene_for_day(day: int) -> str:
    return "工作日午餐" if day % 2 == 1 else "周末聚餐"


def generate_weekly_menu_sync(days: int = 7, diversityLevel: int = 2) -> ToolResult:
    if not db.has_meaningful_profile():
        return ToolResult(ToolStatus.EMPTY_NEEDS_INPUT, data=[],
                          hint="请先记录几餐或设置口味档案，再生成周菜单")
    profile = _profile_or_raise()
    raw_catalog, source = get_menu_source()
    catalog = [
        d for d in raw_catalog
        if not (set(profile["allergens"]) & set(d.get("allergens", [])))
        and not (set(profile["avoid_foods"]) & set(d.get("ingredients", [])))
    ]
    menu = []
    used_names: set = set()
    last_dom = None
    for day in range(1, days + 1):
        best, best_score = None, -1.0
        for dish in catalog:
            if dish["name"] in used_names:
                continue
            dom = dominant(dish)
            penalty = 0.0
            # 口味多样性：diversityLevel>=2 时，不连续两天推荐相同主导口味
            if diversityLevel >= 2 and dom == last_dom:
                penalty = 5.0 * diversityLevel
            score = _score(dish, profile, _scene_for_day(day), set()) - penalty
            if score > best_score:
                best_score, best = score, dish
        if best is None:
            break
        menu.append({"day": day, "dish": best["name"], "dominant": dominant(best)})
        used_names.add(best["name"])
        last_dom = dominant(best)
    if not menu:
        return ToolResult(ToolStatus.EMPTY_NEEDS_INPUT, data=[],
                          hint="过滤后无足够候选，建议放宽饮食限制")
    if source == "offline_demo":
        return ToolResult(ToolStatus.OK, data=menu, data_source="offline_demo",
                          hint="当前未连接麦当劳 MCP，以下为离线示例菜单；配置 MCD_MCP_TOKEN 后将基于实时菜单生成")
    return ToolResult(ToolStatus.OK, data=menu, data_source="mcd_mcp")


def suggest_substitute_sync(originalIngredient: str, reason: str = "") -> ToolResult:
    key = (originalIngredient or "").strip()
    subs = SUBSTITUTE_MAP.get(key)
    if subs:
        profile = db.get_profile() or db.default_profile_dict()
        avoided = set(profile["allergens"]) | set(profile["avoid_foods"])
        filtered = [s for s in subs if not any(a in s for a in avoided)] or subs
        return ToolResult(ToolStatus.OK, data={"original": key, "substitutes": filtered,
                                                "reason": reason or "常见替代"})
    # 未知食材：给通用建议，不报错、不编造
    return ToolResult(ToolStatus.OK,
                      data={"original": key, "substitutes": [],
                            "reason": "未在替代库中，建议按同类口感/营养找替代，或告诉我你的限制我再细化"},
                      hint="未知食材，已给通用建议")
