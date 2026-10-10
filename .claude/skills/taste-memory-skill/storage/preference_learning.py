"""隐式偏好学习（R3）。

规则（来自任务书 4.4）：
- 记录一餐且评分 ≥ 4：该菜品主要口味维度权重 +0.3（上限 5.0）
- 评分 ≤ 2：对应维度权重 -0.3（下限 1.0）
- 连续 3 次同维度且评分 ≥ 4：额外 +0.5（streak 奖励，任务书 4.1）
- mark_dislike：对应维度权重直接置 1.0

关键点（防循环）：权重更新是 record_meal 的**纯副作用**，本模块绝不反向触发推荐。
每次更新都写 preference_log，可查询变化历史。
"""
from __future__ import annotations

from typing import Optional

from storage import db
from models.schemas import TASTE_DIMENSIONS, DIM_MIN, DIM_MAX

DIM_STEP = 0.3
STREAK_BONUS = 0.5
STREAK_THRESHOLD = 3


def classify_dimension(dish_name: str) -> Optional[str]:
    """把菜名映射到其主要口味维度（启发式关键词，覆盖常见情况）。

    任务书 4.4 的“该菜品主要口味维度”需要这一步；AC2 要求 '川菜' -> '辣'。
    无法识别时返回 None（不更新权重，也不误伤）。
    """
    rules = [
        ("辣", ["辣", "麻辣", "川", "火锅", "水煮", "剁椒", "泡椒"]),
        ("麻", ["麻", "花椒", "藤椒"]),
        ("甜", ["甜", "糖", "蜜", "糕", "奶", "布丁", "糖水"]),
        ("酸", ["酸", "醋", "柠檬", "酸菜", "番茄"]),
        ("清淡", ["清淡", "粥", "蒸", "白灼", "沙拉", "汤", "清炒"]),
        ("咸香", ["咸", "酱", "卤", "咸菜", "腊肉", "红烧"]),
    ]
    for dim, kws in rules:
        if any(k in dish_name for k in kws):
            return dim
    return None


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _clamp(v: float) -> float:
    return max(DIM_MIN, min(DIM_MAX, round(v, 2)))


def apply_meal_learning(dish_name: str, rating: int, reason: str = "") -> dict:
    profile = db.get_profile() or db.default_profile_dict()
    dim = classify_dimension(dish_name)
    start = dict(profile["dimensions"])  # 记录起点，便于算净增量

    # 单次评分带来的维度变化
    meal_delta = None
    if dim and dim in profile["dimensions"]:
        cur = profile["dimensions"][dim]
        if rating >= 4:
            profile["dimensions"][dim] = _clamp(cur + DIM_STEP)
        elif rating <= 2:
            profile["dimensions"][dim] = _clamp(cur - DIM_STEP)
        meal_delta = round(profile["dimensions"][dim] - cur, 2)

    # 连续高评分同维度的额外奖励
    bonus_dim = _check_streak(dim)
    bonus_delta = None
    if bonus_dim:
        cur = profile["dimensions"][bonus_dim]
        profile["dimensions"][bonus_dim] = _clamp(cur + STREAK_BONUS)
        bonus_delta = round(profile["dimensions"][bonus_dim] - cur, 2)

    profile["updated_at"] = _now()
    db.upsert_profile(profile)

    # 净增量（单次 + streak 合并）
    deltas: dict = {}
    if meal_delta is not None and meal_delta != 0:
        deltas[dim] = meal_delta
    if bonus_delta is not None and bonus_delta != 0:
        deltas[bonus_dim] = round(deltas.get(bonus_dim, 0) + bonus_delta, 2)

    if meal_delta is not None and meal_delta != 0:
        db.log_pref(_now(), "meal_rating", dim, meal_delta, reason or f"rating={rating}")
    if bonus_dim:
        db.log_pref(_now(), "streak_bonus", bonus_dim, bonus_delta, reason or "连续高评分")
    return {"dimension": dim, "deltas": deltas}


def _check_streak(dim: Optional[str]) -> Optional[str]:
    if not dim:
        return None
    rows = db.get_recent_meals(limit=STREAK_THRESHOLD)
    if len(rows) < STREAK_THRESHOLD:
        return None
    for r in rows:  # rows 已倒序：最近 STREAK_THRESHOLD 餐
        if classify_dimension(r["dish_name"]) != dim or r["rating"] < 4:
            return None
    return dim


def apply_manual(dimension: str, value: float, reason: str = "") -> dict:
    if dimension not in TASTE_DIMENSIONS:
        raise ValueError(f"未知维度: {dimension}")
    profile = db.get_profile() or db.default_profile_dict()
    new = _clamp(value)
    delta = round(new - profile["dimensions"][dimension], 2)
    profile["dimensions"][dimension] = new
    profile["updated_at"] = _now()
    db.upsert_profile(profile)
    db.log_pref(_now(), "manual", dimension, delta, reason)
    return {"dimension": dimension, "value": new}


def apply_dislike(dish_name: str, reason: str = "") -> dict:
    profile = db.get_profile() or db.default_profile_dict()
    if dish_name not in profile["disliked_dishes"]:
        profile["disliked_dishes"].append(dish_name)
    dim = classify_dimension(dish_name)
    delta = None
    if dim and dim in profile["dimensions"]:
        delta = round(DIM_MIN - profile["dimensions"][dim], 2)
        profile["dimensions"][dim] = DIM_MIN  # 直接降至下限
        db.log_pref(_now(), "dislike", dim, delta, reason or dish_name)
    profile["updated_at"] = _now()
    db.upsert_profile(profile)
    return {"dish": dish_name, "dimension": dim, "dimension_set_to": dim and DIM_MIN}
