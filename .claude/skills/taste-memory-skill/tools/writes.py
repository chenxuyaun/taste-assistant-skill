"""写入类工具：record_meal / update_preference / mark_dislike。

全部走两段式确认（core.confirm.stage_write），从协议上杜绝“未确认就写”和“Agent 重试写两次”：
- 首次调用（confirmed=False）只创建 pending 并返回 NEEDS_CONFIRMATION + pending_id，不碰数据库。
- 带 confirmed=True + 同一 pending_id 的二次调用才真正写入；同一 pending_id 重放为幂等 no-op。
"""
from __future__ import annotations

from typing import Optional

from core.server import mcp
from core.guard import ToolResult, ToolStatus
from core.confirm import stage_write, mark_completed
from storage import db, preference_learning
from models.schemas import TASTE_DIMENSIONS


@mcp.tool()
def record_meal(
    dishName: str,
    rating: int,
    scene: str,
    timestamp: Optional[str] = None,
    confirmed: bool = False,
    pending_id: Optional[str] = None,
) -> dict:
    """记录一餐并触发隐式偏好更新。**必须用户确认后执行**（AC4）。

    首次调用不带 confirmed 时返回 NEEDS_CONFIRMATION 与确认话术，不写入。
    """
    prompt = f"我将记录你刚吃的[{dishName}]，评分[{rating}]，场景[{scene}]，确认吗？"
    res, should_write, _ = stage_write(
        "record_meal", {"dishName": dishName, "rating": rating, "scene": scene, "timestamp": timestamp},
        confirmed, pending_id, prompt,
    )
    if res.status != ToolStatus.OK:
        return res.to_dict()
    if should_write:
        ts = timestamp or _now()
        db.insert_meal(dishName, rating, scene, ts)
        learning = preference_learning.apply_meal_learning(dishName, rating)
        summary = {"dish": dishName, "rating": rating, "scene": scene, "learning": learning}
        mark_completed(pending_id, summary)
        return ToolResult(ToolStatus.OK, data=summary, hint="已记录，并触发隐式偏好更新").to_dict()
    return res.to_dict()  # 幂等重放：返回已完成的摘要，不重复写


@mcp.tool()
def update_preference(
    dimension: str,
    value: float,
    reason: Optional[str] = None,
    confirmed: bool = False,
    pending_id: Optional[str] = None,
) -> dict:
    """手动更新某个口味维度权重（1-5）。**必须用户确认后执行**。"""
    if dimension not in TASTE_DIMENSIONS:
        return ToolResult(ToolStatus.ERROR,
                          hint=f"未知维度: {dimension}，可选: {TASTE_DIMENSIONS}", retryable=False).to_dict()
    prompt = f"我将把[{dimension}]维度手动设为[{value}]（原因：{reason or '无'}），确认吗？"
    res, should_write, _ = stage_write(
        "update_preference", {"dimension": dimension, "value": value, "reason": reason},
        confirmed, pending_id, prompt,
    )
    if res.status != ToolStatus.OK:
        return res.to_dict()
    if should_write:
        out = preference_learning.apply_manual(dimension, value, reason or "")
        mark_completed(pending_id, out)
        return ToolResult(ToolStatus.OK, data=out).to_dict()
    return res.to_dict()


@mcp.tool()
def mark_dislike(
    dishName: str,
    reason: Optional[str] = None,
    confirmed: bool = False,
    pending_id: Optional[str] = None,
) -> dict:
    """标记不想再吃的菜，并降低相关口味权重。**必须用户确认后执行**。"""
    prompt = f"我将标记[{dishName}]为你不想再吃的菜（原因：{reason or '无'}），确认吗？"
    res, should_write, _ = stage_write(
        "mark_dislike", {"dishName": dishName, "reason": reason},
        confirmed, pending_id, prompt,
    )
    if res.status != ToolStatus.OK:
        return res.to_dict()
    if should_write:
        out = preference_learning.apply_dislike(dishName, reason or "")
        mark_completed(pending_id, out)
        return ToolResult(ToolStatus.OK, data=out).to_dict()
    return res.to_dict()


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")
