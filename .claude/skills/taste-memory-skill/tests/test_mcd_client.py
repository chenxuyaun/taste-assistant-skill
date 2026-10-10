"""麦当劳 MCP 集成测试：客户端启发式 + 数据源回退（不依赖真实 Token / 网络）。"""
from __future__ import annotations

from recommend import mcd_client
from recommend import engine


def test_guess_dims_heuristic():
    dims = mcd_client.guess_dims("麦辣鸡腿堡", [])
    assert dims.get("辣", 0) >= 4
    light = mcd_client.guess_dims("田园沙拉", [])
    assert light.get("清淡", 0) >= 4


def test_guess_allergens_conservative():
    # 麦辣鸡腿堡 不含已知过敏原关键词 -> 不误报
    assert "花生" not in mcd_client.guess_allergens("麦辣鸡腿堡")
    # 含蛋挞 -> 标记鸡蛋
    assert "鸡蛋" in mcd_client.guess_allergens("蛋挞")


def test_normalize_meals_real_mcd_structure():
    # 麦当劳 query-meals 真实响应结构（data.categories + data.meals + data.frequent）
    raw = {
        "success": True, "code": 0,
        "data": {
            "categories": [{"name": "汉堡", "meals": [{"code": "C1", "tags": ["经典"]}]}],
            "meals": {"C1": {"name": "巨无霸", "currentPrice": "24.5", "originalPrice": "28"}},
            "frequent": {"name": "麦辣鸡腿堡", "tags": ["辣"]},
        },
    }
    items = mcd_client.normalize_meals(raw)
    names = {i["name"] for i in items}
    assert "巨无霸" in names and "麦辣鸡腿堡" in names
    required = {"name", "dims", "tags", "ingredients", "allergens", "price", "original_price"}
    for it in items:
        assert required <= set(it.keys())
    big = next(i for i in items if i["name"] == "巨无霸")
    assert big["price"] == 24.5 and big["original_price"] == 28.0


def test_normalize_meals_from_wrapped_text():
    # 麦当劳 MCP 把后端响应包成文本 + 末尾 ## Original Response JSON
    text = (
        "# API Response Information\n\n## Response Structure\n- **data**: ...\n\n"
        "## Original Response\n\n"
        '{"success": true, "code": 0, "data": {"categories": [{"name": "n",'
        '"meals": [{"code": "X", "tags": []}]}], "meals": {"X": {"name": "薯条"}}}}'
    )
    items = mcd_client.normalize_meals(text)
    assert any(i["name"] == "薯条" for i in items)


def test_normalize_meals_empty_returns_empty():
    # 无 item 字段且无名称 -> 返回空列表（由上层 _fetch_live 决定抛错/回退）
    assert mcd_client.normalize_meals("{}") == []


def test_get_menu_source_offline_when_no_token(monkeypatch):
    monkeypatch.delenv("MCD_MCP_TOKEN", raising=False)
    monkeypatch.delenv("MCD_TOKEN", raising=False)
    catalog, source, _ = engine.get_menu_source()
    assert source == "offline_demo"
    assert len(catalog) > 0


def test_recommend_labels_offline_source(isolated_db):
    # 未配置 Token 时，推荐结果应标注 offline_demo 而非伪造 mcd_mcp
    from storage import db
    db.insert_meal("水煮鱼", 5, "工作日午餐", "2026-01-01T12:00:00")
    res = engine.recommend_dish_sync(scene="工作日午餐")
    assert res.status == "OK"
    assert res.data_source == "offline_demo"


def test_normalize_filters_merchandise():
    raw = {
        "categories": [{"name": "n", "meals": [
            {"code": "A", "tags": []},
            {"code": "B", "tags": []},
        ]}],
        "meals": {
            "A": {"name": "麦辣鸡腿堡", "currentPrice": "20"},
            "B": {"name": "麦当劳联名复古棒球帽", "currentPrice": "34.9"},
        },
    }
    items = mcd_client.normalize_meals(raw)
    names = {i["name"] for i in items}
    assert "麦辣鸡腿堡" in names
    assert "麦当劳联名复古棒球帽" not in names  # 周边被过滤


def test_find_nearest_store_picks_min_distance(monkeypatch):
    stores = [
        {"storeCode": "A", "storeName": "远店", "distance": 500, "address": "x"},
        {"storeCode": "B", "storeName": "最近店", "distance": 173, "address": "y"},
        {"storeCode": "C", "storeName": "中店", "distance": 300, "address": "z"},
    ]

    async def fake(name, args):
        if name == "query-nearby-stores":
            return {"structuredContent": {"success": True, "code": 200, "data": stores}}
        return {}

    monkeypatch.setattr(mcd_client, "_call_tool", fake)
    monkeypatch.setenv("MCD_CITY", "成都市")
    monkeypatch.setenv("MCD_KEYWORD", "春熙路")
    monkeypatch.delenv("MCD_STORE_CODE", raising=False)
    monkeypatch.setenv("MCD_MCP_TOKEN", "x")
    res = mcd_client.find_nearest_store()
    assert res["store_code"] == "B"
    assert res["distance"] == 173


def test_get_live_menu_with_store_auto_locates(monkeypatch):
    stores = [{"storeCode": "B", "storeName": "最近店", "distance": 173, "address": "y"}]
    menu_raw = {
        "categories": [{"name": "套餐", "meals": [{"code": "c1", "tags": ["fast"]}]}],
        "meals": {"c1": {"name": "麦辣鸡腿堡", "currentPrice": "20.0", "originalPrice": "25"}},
    }

    async def fake(name, args):
        if name == "query-nearby-stores":
            return {"structuredContent": {"success": True, "code": 200, "data": stores}}
        if name == "query-meals":
            assert args.get("storeCode") == "B"  # 自动用了最近门店
            return {"structuredContent": {"success": True, "code": 200, "data": menu_raw}}
        return {}

    monkeypatch.setattr(mcd_client, "_call_tool", fake)
    monkeypatch.setenv("MCD_CITY", "成都市")
    monkeypatch.setenv("MCD_KEYWORD", "春熙路")
    monkeypatch.delenv("MCD_STORE_CODE", raising=False)
    monkeypatch.setenv("MCD_MCP_TOKEN", "x")
    items, store = mcd_client.get_live_menu_with_store()
    assert store["store_code"] == "B"
    assert len(items) == 1
    assert items[0]["name"] == "麦辣鸡腿堡"
    assert items[0]["price"] == 20.0
