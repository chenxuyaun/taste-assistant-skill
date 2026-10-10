"""麦当劳 MCP 客户端 —— 比赛资格的真实集成层。

通过原生 JSON-RPC over HTTP（Streamable HTTP 风格）连接 https://mcp.mcd.cn，
使用环境变量 ``MCD_MCP_TOKEN`` 鉴权，真实调用以下工具：

- ``query-meals``：拉取**实时**门店菜单（需门店编码 storeCode + 取餐方式）。
- ``query-nearby-stores``：**基于位置锚点（城市 + 关键词）定位附近门店**，按到店距离选最近。
- ``list-nutrition-foods``：拉取营养数据（可选，推荐未深度消费，仅作能力暴露）。

为什么不用 mcp SDK 的 streamable_http_client（实测结论）：
- mcp 2.3.0 的 streamable_http_client 进入 context 时会发起 GET 根路径建立 SSE 流，
  而麦当劳 MCP 服务端 `GET /` 返回 403，导致 anyio TaskGroup 抛 "unhandled errors"、连接失败。
- 其函数签名也无 headers 参数（需经自定义 httpx.AsyncClient 注入鉴权头）。
- 故直接用 httpx 发 JSON-RPC（initialize + tools/call），绕开 SDK 的流封装，稳定可用。

关于"定位"（重要，如实说明）：
- 麦当劳 MCP **没有"获取 GPS 经纬度"的工具**，桌面 Agent 也没有 GPS。
  这里的"定位"是**语义定位**：用户提供位置锚点（``MCD_CITY`` + ``MCD_KEYWORD``，如「成都市」+「春熙路」），
  调 ``query-nearby-stores``(searchType=2) 拿到附近门店列表（含到店 distance 米数），取最近一家。
- 若用户显式配置了 ``MCD_STORE_CODE``，则优先用该门店，不再自动定位。

设计纪律（对应活动规则「不得静默降级到模拟数据」）：
- 仅在配置了有效 Token 且工具成功返回时，返回真实麦当劳数据，source="mcd_mcp"。
- 任何连接 / 鉴权 / 参数缺失 / 超时 / 解析失败都返回 None，由推荐引擎**透明**回退离线目录，
  并在结果里标注 source="offline_demo"，绝不伪造实时数据。
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

# 实时菜单含部分周边商品（帽/公仔/玩具等），非食品，推荐时过滤
_MERCH_HINTS = ("帽", "公仔", "玩具", "T恤", "tee", "Tee", "钥匙扣", "水杯",
                "抱枕", "盲盒", "联名牌", "帆布包", "玩偶", "手办", "周边",
                "徽章", "贴纸", "餐具", "卡包", "毛绒")


def _token() -> Optional[str]:
    return os.getenv("MCD_MCP_TOKEN") or os.getenv("MCD_TOKEN")


def _store_code() -> Optional[str]:
    return os.getenv("MCD_STORE_CODE") or os.getenv("MCD_STORECODE")


def _city() -> Optional[str]:
    return os.getenv("MCD_CITY")


def _keyword() -> Optional[str]:
    return os.getenv("MCD_KEYWORD")


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


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_merch(name: str) -> bool:
    """判断是否为周边非食品（帽/公仔/玩具等），实时菜单里混入此类商品需过滤。"""
    return any(k in (name or "") for k in _MERCH_HINTS)


def _parse_original_response(text: str) -> Optional[dict]:
    """从 'API Response Information' 包装文本里提取 `## Original Response` 后的真实 JSON。

    麦当劳 MCP 把后端 API 响应包成 LLM 可读文本 + 末尾 `## Original Response\\n{...}`，
    业务数据（菜单 / 门店）就在这个 JSON 里。优先用 structuredContent，此处仅作回退。
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

    返回 ``[{"name","dims","tags","ingredients","allergens","price","original_price","image"}]``。
    真实结构（实测 store 3450410）：``data = {categories:[{name,meals:[{code,tags}]}],
    meals:{code:{name,image,currentPrice:"33.5",originalPrice:"47",canWithOrder}}}``。
    """
    data = raw
    if isinstance(raw, str):
        data = _parse_original_response(raw)
    if not isinstance(data, dict):
        return []
    # 兼容 {success, code, data:{...}} 包装与直接 {categories, meals}
    if "categories" in data or "meals" in data:
        payload = data
    else:
        payload = data.get("data") or {}
    if not isinstance(payload, dict):
        return []
    categories = payload.get("categories") or []
    meals_map = payload.get("meals") or {}

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
            if _is_merch(name):  # 过滤周边非食品（如"棒球帽"），避免被当作菜推荐
                continue
            seen.add(name)
            tags = list(meal.get("tags") or []) + list(detail.get("tags") or [])
            items.append({
                "name": name,
                "dims": guess_dims(name, tags),
                "tags": tags,
                "ingredients": [],
                "allergens": guess_allergens(name),
                "price": _to_float(detail.get("currentPrice")),
                "original_price": _to_float(detail.get("originalPrice")),
                "image": detail.get("image"),
            })

    # 常点餐品（frequent）可能含 name（真实结构里部分门店有，部分门店为 None）
    frequent = payload.get("frequent")
    if isinstance(frequent, dict):
        nm = frequent.get("name")
        if nm and nm not in seen:
            seen.add(nm)
            tags = list(frequent.get("tags") or [])
            items.append({
                "name": nm, "dims": guess_dims(nm, tags), "tags": tags,
                "ingredients": [], "allergens": guess_allergens(nm),
                "price": _to_float(frequent.get("currentPrice")),
                "original_price": _to_float(frequent.get("originalPrice")),
                "image": frequent.get("image"),
            })
    return items


async def _call_tool(name: str, args: dict) -> dict:
    """统一 JSON-RPC 调用：initialize + tools/call，返回 result 字典（无 result 时返回 {}）。"""
    import httpx

    token = _token()
    if not token:
        return {}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(headers=headers, timeout=MCD_TIMEOUT) as c:
        await c.post(MCD_MCP_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": MCD_PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "taste-memory", "version": "1.0.0"},
            },
        })
        resp = await c.post(MCD_MCP_URL, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        })
        return resp.json().get("result", {}) or {}


def _extract_success_data(result: dict) -> Optional[object]:
    """从 tools/call 的 result 里取出 data 业务体；业务失败抛 ValueError（不静默）。"""
    if not isinstance(result, dict):
        return None
    sc = result.get("structuredContent")
    if isinstance(sc, dict):
        if sc.get("success") is False:
            raise ValueError(f"{sc.get('message')} (code={sc.get('code')})")
        if "data" in sc:
            return sc.get("data")
    text = ""
    if result.get("content"):
        text = result["content"][0].get("text", "")
    parsed = _parse_original_response(text)
    if isinstance(parsed, dict):
        if parsed.get("success") is False:
            raise ValueError(f"{parsed.get('message')}")
        if "data" in parsed:
            return parsed.get("data")
    return None


async def _fetch_live(store_code: str) -> list:
    if not store_code:
        raise ValueError("缺少门店编码（storeCode）")
    result = await _call_tool("query-meals", {
        "storeCode": store_code, "orderType": 1, "beType": 1,
    })
    data = _extract_success_data(result)
    if data is None:
        raise ValueError("query-meals 未返回 data")
    items = normalize_meals(data)
    if not items:
        raise ValueError("麦当劳 MCP 未返回可解析的菜单条目")
    return items


async def _fetch_nearby(city: str, keyword: str, be_type: int = 1) -> Optional[dict]:
    """调 query-nearby-stores，按到店 distance（米）升序返回最近门店信息。"""
    if not (city and keyword):
        return None
    result = await _call_tool("query-nearby-stores", {
        "beType": be_type, "searchType": 2, "city": city, "keyword": keyword,
    })
    try:
        data = _extract_success_data(result)
    except ValueError as e:
        logger.warning("query-nearby-stores 业务失败，回退离线: %s", e)
        return None
    if not isinstance(data, list) or not data:
        return None

    def _dkey(s: dict):
        d = s.get("distance")
        return d if isinstance(d, (int, float)) else float("inf")

    best = min(data, key=_dkey)
    return {
        "store_code": best.get("storeCode"),
        "store_name": best.get("storeName"),
        "address": best.get("address"),
        "distance": best.get("distance"),
    }


def find_nearest_store(city: Optional[str] = None, keyword: Optional[str] = None,
                       be_type: int = 1) -> Optional[dict]:
    """同步入口：基于位置锚点自动定位最近门店；未配置 city/keyword 或调用失败返回 None。"""
    city = city or _city()
    keyword = keyword or _keyword()
    if not (city and keyword):
        return None
    try:
        return asyncio.run(asyncio.wait_for(_fetch_nearby(city, keyword, be_type), timeout=MCD_TIMEOUT))
    except Exception as e:  # 连接/超时/解析任一失败 -> 透明回退
        logger.warning("自动定位最近门店失败，回退离线目录: %s", e)
        return None


async def _fetch_nutrition() -> list:
    """list-nutrition-foods 真实存在（tools/list 实测），返回营养数据列表（尽力解析）。"""
    result = await _call_tool("list-nutrition-foods", {})
    data = _extract_success_data(result)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("foods", "list", "items", "nutritions"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def get_nutrition_foods() -> Optional[list]:
    """同步入口：成功返回营养数据列表，否则 None。"""
    if not _token():
        return None
    try:
        return asyncio.run(asyncio.wait_for(_fetch_nutrition(), timeout=MCD_TIMEOUT))
    except Exception as e:
        logger.warning("营养数据获取失败: %s", e)
        return None


def get_live_menu_with_store(store_code: Optional[str] = None) -> tuple[Optional[list], Optional[dict]]:
    """同步入口：返回 (真实菜品列表 | None, 定位门店信息 | None)。

    决策：
    1. store_code 参数 或 MCD_STORE_CODE 环境变量优先；
    2. 否则若有 Token 且配置了 MCD_CITY+MCD_KEYWORD，自动定位最近门店并取其 storeCode；
    3. 仍无门店则真实发起调用（服务端返回缺参数），由调用方透明回退离线目录。
    """
    sc = store_code or _store_code()
    store_info: Optional[dict] = None
    if not sc and _token():
        store_info = find_nearest_store()
        if store_info:
            sc = store_info.get("store_code")
    if not _token():
        return None, None
    if not sc:
        return None, store_info  # 连上但缺门店 -> 离线兜底
    try:
        items = asyncio.run(asyncio.wait_for(_fetch_live(sc), timeout=MCD_TIMEOUT))
        return items, store_info
    except Exception as e:
        logger.warning("麦当劳 MCP 拉取失败，回退离线目录: %s", e)
        return None, store_info


def get_live_menu(store_code: Optional[str] = None) -> Optional[list]:
    """兼容入口：只返回菜品列表（忽略 store_info）。"""
    items, _ = get_live_menu_with_store(store_code)
    return items
