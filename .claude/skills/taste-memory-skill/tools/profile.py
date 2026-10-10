"""只读类工具：口味档案与饮食限制查询。无副作用，永不进入写入确认流程。"""
from __future__ import annotations

from typing import Optional

from core.server import mcp
from core.guard import ToolResult, ToolStatus
from storage import db


@mcp.tool()
def get_taste_profile() -> dict:
    """返回完整口味档案 JSON（维度评分 + 饮食限制 + 更新时间）。只读，无副作用。"""
    p = db.get_profile()
    if p is None:
        return ToolResult(ToolStatus.OK, data=db.default_profile_dict(),
                          hint="尚未建立口味档案，记录几餐后自动生成").to_dict()
    return ToolResult(ToolStatus.OK, data=p).to_dict()


@mcp.tool()
def query_dietary_restrictions() -> dict:
    """返回过敏原、忌口食材、宗教饮食规则、不想再吃的菜。只读。"""
    p = db.get_profile() or db.default_profile_dict()
    return ToolResult(ToolStatus.OK, data={
        "allergens": p["allergens"],
        "avoid_foods": p["avoid_foods"],
        "religious_rules": p["religious_rules"],
        "disliked_dishes": p["disliked_dishes"],
    }).to_dict()
