"""用餐历史查询。只读；空库返回空列表且不报错（AC1）。"""
from __future__ import annotations

from typing import Optional

from core.server import mcp
from core.guard import ToolResult, ToolStatus
from storage import db


@mcp.tool()
def query_meal_history(dateRange: Optional[str] = None, limit: int = 20) -> dict:
    """按时间倒序返回用餐记录。dateRange 可选，形如 '2026-01-01..2026-01-31'。

    空库时返回空列表且不报错（AC1）；不会诱导 Agent 去“修复”空库（R4）。
    """
    rows = db.get_meals(dateRange=dateRange, limit=limit)
    if not rows:
        return ToolResult(ToolStatus.OK, data=[], hint="用餐记录为空，先记录几餐再查看历史").to_dict()
    return ToolResult(ToolStatus.OK, data=rows).to_dict()
