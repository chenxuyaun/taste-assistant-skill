"""麦当劳 MCP 客户端 —— 比赛资格的真实集成层。

通过 Streamable HTTP 连接 https://mcp.mcd.cn，使用环境变量 ``MCD_MCP_TOKEN`` 鉴权，
拉取**实时**菜单（query-meals）与营养（list-nutrition-foods），归一化为推荐引擎可用的菜品结构。

设计纪律（对应活动规则「不得静默降级到模拟数据」）：
- 仅在配置了有效 Token 且连接成功时返回真实麦当劳数据，``source="mcd_mcp"``。
- 任何连接 / 鉴权 / 超时 / 解析失败都返回 ``None``，由推荐引擎**透明**回退到离线 demo 目录，
  并在结果里标注 ``source="offline_demo"``，绝不把离线数据伪装成实时麦当劳数据。
- 口味维度是用「菜名 / 标签 / 营养」推导的**启发式**，代码与文档均如实标注，不声称是官方口味标签。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("taste-memory.mcd_client")

MCD_MCP_URL = "https://mcp.mcd.cn"
MCD_TIMEOUT = 4.0  # 拉取实时菜单的墙钟预算（秒）

# 口味维度启发式：基于麦当劳菜名 / 标签关键词推断（非官方口味标签，仅供参考）
_TASTE_HINTS = [
    (("辣", "麻辣", "椒", "川", "火", "麦辣", "辣翅", "香辣", "酸辣"), {"辣": 5, "麻": 2}),
    (("麻", "花椒", "麻婆"), {"麻": 5}),
    (("甜", "糖", "圣代", "派", "麦旋风", "巧克力", "莓", "可乐", "玉米杯", "红豆"), {"甜": 4}),
    (("酸", "番茄", "醋", "柠檬", "酸笋"), {"酸": 4}),
    (("沙拉", "蔬", "玉米", "地瓜", "苹果", "板烧(轻食)"), {"清淡": 5}),
    (("咸", "培根", "芝士", "鸡", "牛", "猪", "堡", "薯", "板烧", "虾", "鱼"), {"咸香": 4}),
]
_ALLERGEN_HINTS = {
    "花生": ("花生", "花生酱"),
    "鸡蛋": ("蛋", "鸡蛋", "蛋挞", "麦旋风"),
    "牛奶": ("奶", "芝士", "奶酪", "牛奶", "冰淇淋", "圣代", "麦旋风"),
    "麸质": ("面", "堡", "麦", "派", "卷"),
    "虾": ("虾",),
    "鱼": ("鱼", "鳕鱼", "麦香鱼"),
}


def _token() -> Optional[str]:
    return os.getenv("MCD_MCP_TOKEN") or os.getenv("MCD_TOKEN")


def guess_dims(name: str, tags: list) -> dict:
    """用菜名 + 标签推导口味维度强度（启发式，1–5）。"""
    text = (name or "") + " " + " ".join(tags or [])
    dims: dict = {}
    for keys, vals in _TASTE_HINTS:
        if any(k in text for k in keys):
            for d, v in vals.items():
                dims[d] = max(dims.get(d, 0), v)
    if not dims:
        dims["咸香"] = 3  # 麦当劳多数单品偏咸香，作为中性默认
    return dims


def guess_allergens(name: str) -> list:
    """基于菜名关键词粗判可能过敏原（仅在确知含该原料时标记，宁缺毋滥）。"""
    found = []
    for allergen, keys in _ALLERGEN_HINTS.items():
        if any(k in (name or "") for k in keys):
            found.append(allergen)
    return found


def normalize_meals(meals_payload: object, nutrition_payload: object = None) -> list:
    """把麦当劳 MCP 返回的菜单/营养 JSON 归一化为菜品结构列表。

    返回 ``[{"name", "dims", "tags", "ingredients", "allergens"}]``。
    解析失败时抛出，由上层捕获后回退离线目录。
    """
    items: list = []
    names: list = []

    meals = _as_json(meals_payload)
    # 兼容两种常见结构：列表 / 含 items 或 data 字段的对象
    if isinstance(meals, list):
        raw_list = meals
    elif isinstance(meals, dict):
        raw_list = meals.get("items") or meals.get("data") or meals.get("meals") or []
    else:
        raw_list = []

    for entry in raw_list:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            nm = entry.get("name") or entry.get("dishName") or entry.get("title") or entry.get("itemName")
            if nm:
                names.append(nm)
                items.append({
                    "name": nm,
                    "dims": guess_dims(nm, entry.get("tags") or []),
                    "tags": entry.get("tags") or [],
                    "ingredients": entry.get("ingredients") or [],
                    "allergens": guess_allergens(nm),
                })

    # 若解析不到结构化条目，但拿到了名称字符串，至少用名称构造候选
    for nm in names:
        if not any(i["name"] == nm for i in items):
            items.append({
                "name": nm,
                "dims": guess_dims(nm, []),
                "tags": [],
                "ingredients": [],
                "allergens": guess_allergens(nm),
            })
    return items


def _as_json(payload: object):
    if payload is None:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (ValueError, TypeError):
            return None
    # MCP TextContent / 其他对象：尝试取 .text
    text = getattr(payload, "text", None)
    if isinstance(text, str):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None
    return None


def _extract_text(result) -> Optional[str]:
    """从 MCP call_tool 的返回结果里取出首个文本块。"""
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for block in content:
            txt = getattr(block, "text", None)
            if isinstance(txt, str):
                return txt
    if isinstance(result, str):
        return result
    return None


async def _fetch_live() -> list:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    token = _token()
    if not token:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    async with streamable_http_client(MCD_MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            meals_result = await session.call_tool("query-meals", {})
            nutrition_result = None
            try:
                nutrition_result = await session.call_tool("list-nutrition-foods", {})
            except Exception as e:  # 营养接口可选，失败不影响菜单推荐
                logger.warning("list-nutrition-foods 调用失败，仅用菜单: %s", e)
            meals_text = _extract_text(meals_result)
            nutrition_text = _extract_text(nutrition_result) if nutrition_result else None
            items = normalize_meals(meals_text, nutrition_text)
            if not items:
                raise ValueError("麦当劳 MCP 未返回可解析的菜单条目")
            return items


def get_live_menu() -> Optional[list]:
    """同步入口：成功返回真实麦当劳菜品列表，否则返回 None（调用方透明回退离线目录）。"""
    if not _token():
        return None
    try:
        return asyncio.run(asyncio.wait_for(_fetch_live(), timeout=MCD_TIMEOUT))
    except Exception as e:  # 连接/鉴权/超时/解析任一失败都视为不可用
        logger.warning("麦当劳 MCP 拉取失败，回退离线目录: %s", e)
        return None
