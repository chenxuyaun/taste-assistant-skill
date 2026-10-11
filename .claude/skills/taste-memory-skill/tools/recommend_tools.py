"""推荐类工具：recommend_dish / generate_weekly_menu / suggest_substitute。

异步包装，套硬墙钟超时（core.guard.with_timeout）。任何 DB 故障或超时都转成 ERROR
返回——如实上报，绝不静默降级到模拟数据（R6 / 任务书六）。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from core.server import mcp
from core.guard import ToolResult, ToolStatus, with_timeout
from core import config
from recommend import engine


@mcp.tool()
async def recommend_dish(
    scene: str,
    mealTime: Optional[str] = None,
    availableIngredients: Optional[list] = None,
    excludeItems: Optional[list] = None,
    include_recent: bool = False,
) -> dict:
    """结合口味档案、历史、场景给出个性化推荐。空库返回 EMPTY_NEEDS_INPUT（终态，勿重试）。"""
    try:
        result = await with_timeout(
            asyncio.to_thread(engine.recommend_dish_sync, scene, mealTime,
                               availableIngredients, excludeItems, include_recent),
            config.RECOMMEND_TIMEOUT, "recommend_dish",
        )
        return result.to_dict()
    except TimeoutError as e:
        return ToolResult(ToolStatus.ERROR, hint=str(e), retryable=True,
                          retry_after=1, fallback="safe_default_profile").to_dict()
    except Exception as e:  # DB/其他故障：如实报错，不造假
        return ToolResult(ToolStatus.ERROR, hint=f"推荐失败: {e}", retryable=False).to_dict()


@mcp.tool()
async def generate_weekly_menu(days: int = 7, diversityLevel: int = 2) -> dict:
    """生成一周菜单，避免重复、平衡口味。diversityLevel 1-3 控制多样性强度。"""
    try:
        result = await with_timeout(
            asyncio.to_thread(engine.generate_weekly_menu_sync, days, diversityLevel),
            config.WEEKLY_TIMEOUT, "generate_weekly_menu",
        )
        return result.to_dict()
    except TimeoutError as e:
        return ToolResult(ToolStatus.ERROR, hint=str(e), retryable=True,
                          retry_after=1, fallback="safe_default_profile").to_dict()
    except Exception as e:
        return ToolResult(ToolStatus.ERROR, hint=f"生成周菜单失败: {e}", retryable=False).to_dict()


@mcp.tool()
async def suggest_substitute(originalIngredient: str, reason: str = "") -> dict:
    """针对过敏或忌口给出食材替代建议（替代本身也会避开用户过敏/忌口）。"""
    try:
        result = await with_timeout(
            asyncio.to_thread(engine.suggest_substitute_sync, originalIngredient, reason),
            config.READ_TIMEOUT, "suggest_substitute",
        )
        return result.to_dict()
    except TimeoutError as e:
        return ToolResult(ToolStatus.ERROR, hint=str(e), retryable=True,
                          retry_after=1, fallback="safe_default_profile").to_dict()
    except Exception as e:
        return ToolResult(ToolStatus.ERROR, hint=f"替代建议失败: {e}", retryable=False).to_dict()


@mcp.tool()
async def compare_stores(storeCodes: list) -> dict:
    """多门店比价：对比同款菜品在多家门店的价格与可下单状态，按省价差排序。

    仅保留在 ≥2 家门店有报价的菜品（价差或售罄差异才有意义）。依赖真实麦当劳 MCP；
    未配置 Token 或拉取失败如实上报，绝不编造价格/库存。
    """
    try:
        result = await with_timeout(
            asyncio.to_thread(engine.compare_stores_sync, storeCodes),
            config.COMPARE_TIMEOUT, "compare_stores",
        )
        return result.to_dict()
    except TimeoutError as e:
        return ToolResult(ToolStatus.ERROR, hint=str(e), retryable=True,
                          retry_after=2, fallback="safe_default_profile").to_dict()
    except Exception as e:
        return ToolResult(ToolStatus.ERROR, hint=f"比价失败: {e}", retryable=False).to_dict()


@mcp.tool()
async def get_nutrition() -> dict:
    """查询麦当劳营养数据（list-nutrition-foods）。当前比赛 Token 权限下可能返回空，如实上报，不伪造。"""
    try:
        result = await with_timeout(
            asyncio.to_thread(engine.get_nutrition_sync),
            config.READ_TIMEOUT, "get_nutrition",
        )
        return result.to_dict()
    except TimeoutError as e:
        return ToolResult(ToolStatus.ERROR, hint=str(e), retryable=True,
                          retry_after=2, fallback="safe_default_profile").to_dict()
    except Exception as e:
        return ToolResult(ToolStatus.ERROR, hint=f"营养查询失败: {e}", retryable=False).to_dict()
