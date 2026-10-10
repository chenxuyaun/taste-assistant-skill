"""麦当劳 MCP 客户端 —— 比赛资格的真实集成层。

通过原生 JSON-RPC over HTTP（Streamable HTTP 风格）连接 https://mcp.mcd.cn，
使用环境变量 ``MCD_MCP_TOKEN`` 鉴权，调用真实工具 ``query-meals`` 拉取**实时**菜单。

为什么不用 mcp SDK 的 streamable_http_client（实测结论）：
- mcp 2.3.0 的 streamable_http_client 进入 context 时会发起 GET 根路径建立 SSE 流，
  而麦当劳 MCP 服务端 `GET /` 返回 403，导致 anyio TaskGroup 抛 "unhandled errors"、连接失败。
- 其函数签名也无 headers 参数（需经自定义 httpx.AsyncClient 注入鉴权头）。
- 故直接用 httpx 发 JSON-RPC（initialize + tools/call），绕开 SDK 的流封装，稳定可用。

设计纪律（对应活动规则「不得静默降级到模拟数据」）：
- 仅在配置了有效 Token 且 query-meals 成功返回菜单时，返回真实麦当劳数据，source="mcd_mcp"。
- 任何连接 / 鉴权 / 参数缺失 / 超时 / 解析失败都返回 None，由推荐引擎**透明**回退离线目录，
  并在结果里标注 source="offline_demo"，绝不伪造实时数据。
- query-meals 需真实门店编码（storeCode）+ 取餐方式；本实现通过 MCD_STORE_CODE 注入，
  未配置时仍真实发起调用（服务端返回缺参数），由引擎离线兜底。
- 口味维度是用「菜名 / 标签」推导的**启发式**，代码与文档均如实标注，不声称是官方口味标签。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("taste-memory.mcd_client")

MCD_MCP_URL = "https://mcp.mcd.cn"   # 根路径 POST（诊断确认 200；非 /mcp）
MCD_TIMEOUT = 8.0
MCD_PROTOCOL = "2024-11-05"

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


def _store_code() -> Optional[str]:
    return os.getenv("MCD_STORE_CODE") or os.getenv("MCD_STORECODE")


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


def _parse_original_response(text: str) -> Optional[dict]:
    """从 'API Response Information' 包装文本里提取 `## Original Response` 后的真实 JSON。

    麦当劳 MCP 把后端 API 响应包成 LLM 可读文本 + 末尾 `## Original Response\\n{...}`，
    业务数据（菜单）就在这个 JSON 里。
    """
    if not isinstance(text, str):
        return None
    m = re.search(r"##\s*Original Response\s*\n(.*)", text, re.DOTALL)
    block = m.group(1).strip() if m else text.strip()
    try:
        return json.loads(block)
    except Exception:
        s, e = block.find("{"), block.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(block[s:e + 1])
            except Exception:
                return None
    return None


def normalize_meals(raw: object) -> list:
    """把 query-meals 的真实响应（已解析 dict 或包装文本）归一化为菜品结构列表。

    返回 ``[{"name", "dims", "tags", "ingredients", "allergens", "price", "original_price"}]``。
    真实结构（实测）：data.categories[].meals[].code/tags + data.meals[code].name/价格 + data.frequent。
    """
    data = raw
    if isinstance(raw, str):
        data = _parse_original_response(raw)
    if not isinstance(data, dict):
        return []
    payload = data.get("data") or {}
    if not isinstance(payload, dict):
        return []
    categories = payload.get("categories") or []
    meals_map = payload.get("meals") or {}
    frequent = payload.get("frequent") or {}

    items: list = []
    seen: set = set()

    for cat in categories:
        if not isinstance(cat, dict):
            continue
        for meal in cat.get("meals") or []:
            if not isinstance(meal, dict):
                continue
            code = meal.get("code")
            if not code:
                continue
            detail = meals_map.get(code) or {}
            name = detail.get("name") if isinstance(detail, dict) else None
            if not name or name in seen:
                continue
            seen.add(name)
            tags = list(meal.get("tags") or []) + list(detail.get("tags") or [])
            items.append({
                "name": name,
                "dims": guess_dims(name, tags),
                "tags": tags,
                "ingredients": [],
                "allergens": guess_allergens(name),
                "price": detail.get("currentPrice"),
                "original_price": detail.get("originalPrice"),
            })

    # 常点餐品（frequent）可能含 name
    if isinstance(frequent, dict):
        nm = frequent.get("name")
        if nm and nm not in seen:
            seen.add(nm)
            tags = list(frequent.get("tags") or [])
            items.append({
                "name": nm,
                "dims": guess_dims(nm, tags),
                "tags": tags,
                "ingredients": [],
                "allergens": guess_allergens(nm),
                "price": frequent.get("currentPrice"),
                "original_price": frequent.get("originalPrice"),
            })
    return items


async def _fetch_live(store_code: Optional[str]) -> list:
    import httpx

    token = _token()
    if not token:
        return []
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    args: dict = {}
    if store_code:
        args["storeCode"] = store_code
        args["orderType"] = 1   # 1-到店
        args["beType"] = 1      # 1-到店取餐（无需 beCode；外送场景才需 beCode）

    async with httpx.AsyncClient(headers=headers, timeout=MCD_TIMEOUT) as c:
        init = await c.post(MCD_MCP_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": MCD_PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "taste-memory", "version": "1.0.0"},
            },
        })
        if init.status_code != 200:
            raise RuntimeError(f"initialize 失败: HTTP {init.status_code}")
        resp = await c.post(MCD_MCP_URL, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "query-meals", "arguments": args},
        })
        result = resp.json().get("result", {})
        text = ""
        if result.get("content"):
            text = result["content"][0].get("text", "")

        # 业务失败判定：structuredContent 或 Original Response 里的 success=false
        sc = result.get("structuredContent")
        if isinstance(sc, dict) and sc.get("success") is False:
            raise ValueError(f"query-meals 业务失败: code={sc.get('code')} msg={sc.get('message')}")
        parsed = _parse_original_response(text)
        if isinstance(parsed, dict) and parsed.get("success") is False:
            raise ValueError(f"query-meals 业务失败: {parsed.get('message')}")

        items = normalize_meals(parsed if parsed else text)
        if not items:
            raise ValueError("麦当劳 MCP 未返回可解析的菜单条目")
        return items


def get_live_menu(store_code: Optional[str] = None) -> Optional[list]:
    """同步入口：成功返回真实麦当劳菜品列表，否则返回 None（调用方透明回退离线目录）。"""
    sc = store_code or _store_code()
    if not _token():
        return None
    try:
        return asyncio.run(asyncio.wait_for(_fetch_live(sc), timeout=MCD_TIMEOUT))
    except Exception as e:  # 连接/鉴权/参数缺失/超时/解析任一失败都视为不可用
        logger.warning("麦当劳 MCP 拉取失败，回退离线目录: %s", e)
        return None
