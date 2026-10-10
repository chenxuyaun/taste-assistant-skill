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
    assert big["price"] == "24.5" and big["original_price"] == "28"


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
    catalog, source = engine.get_menu_source()
    assert source == "offline_demo"
    assert len(catalog) > 0


def test_recommend_labels_offline_source(isolated_db):
    # 未配置 Token 时，推荐结果应标注 offline_demo 而非伪造 mcd_mcp
    from storage import db
    db.insert_meal("水煮鱼", 5, "工作日午餐", "2026-01-01T12:00:00")
    res = engine.recommend_dish_sync(scene="工作日午餐")
    assert res.status == "OK"
    assert res.data_source == "offline_demo"
