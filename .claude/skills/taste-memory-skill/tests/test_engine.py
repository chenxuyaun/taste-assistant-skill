from storage import db, preference_learning
from recommend import engine
from recommend import mcd_client
from core.guard import ToolStatus

PEANUT_DISHES = {"宫保鸡丁", "凉拌花生", "担担面"}
SPICY_DISHES = {"麻婆豆腐", "水煮鱼", "麻辣火锅", "辣子鸡", "酸菜鱼", "宫保鸡丁", "担担面", "酸辣土豆丝"}


def test_ac1_cold_start_recommend_ok(isolated_db):
    # 全新用户（空库）仍属"终态"语义：返回规则化试探推荐（OK + cold_start），不再重试
    r = engine.recommend_dish_sync("工作日午餐")
    assert r.status == ToolStatus.OK
    assert r.cold_start is True
    assert len(r.data) == 3
    assert r.data_source in ("offline_demo", "mcd_mcp")
    assert r.hint  # 冷启动须带说明，引导用户确认/评分


def test_ac3_allergen_exclusion(isolated_db):
    p = db.default_profile_dict()
    p["allergens"] = ["花生"]
    db.upsert_profile(p)
    db.insert_meal("白灼菜心", 4, "工作日午餐", "2026-01-01T12:00:00")
    r = engine.recommend_dish_sync("工作日午餐")
    assert r.status == ToolStatus.OK
    names = {x["dish"] for x in r.data}
    assert not (names & PEANUT_DISHES), f"推荐结果含花生类菜品: {names & PEANUT_DISHES}"


def test_ac5_spicy_boost_reflected(isolated_db):
    for i, name in enumerate(["川菜", "辣子鸡", "水煮鱼"]):
        db.insert_meal(name, 5, "工作日午餐", f"2026-01-0{i+1}T12:00:00")
    preference_learning.apply_meal_learning("水煮鱼", 5)  # 归“辣”，触发 +0.3 与 streak +0.5
    assert db.get_profile()["dimensions"]["辣"] > 3.0
    r = engine.recommend_dish_sync("工作日午餐")
    assert r.status == ToolStatus.OK
    names = {x["dish"] for x in r.data}
    assert names & SPICY_DISHES, f"辣味提升后推荐应含辣菜，实际: {names}"


def test_cold_start_weekly_menu_ok(isolated_db):
    # 空库周菜单：冷启动生成（OK + cold_start），不踢回
    r = engine.generate_weekly_menu_sync()
    assert r.status == ToolStatus.OK
    assert r.cold_start is True
    assert len(r.data) > 0


def test_weekly_menu_no_consecutive_same_dominant(isolated_db):
    p = db.default_profile_dict()
    p["allergens"] = ["花生"]
    db.upsert_profile(p)
    db.insert_meal("白灼菜心", 4, "工作日午餐", "2026-01-01T12:00:00")
    r = engine.generate_weekly_menu_sync(days=5, diversityLevel=3)
    assert r.status == ToolStatus.OK
    dominants = [m["dominant"] for m in r.data]
    for a, b in zip(dominants, dominants[1:]):
        assert a != b, f"连续相同主导口味: {dominants}"


def test_suggest_known_filtered_by_allergen(isolated_db):
    p = db.default_profile_dict()
    p["allergens"] = ["芝麻"]
    db.upsert_profile(p)
    r = engine.suggest_substitute_sync("花生")
    assert r.status == ToolStatus.OK
    subs = r.data["substitutes"]
    assert subs
    assert all("芝麻" not in s for s in subs)


def test_suggest_unknown_not_error(isolated_db):
    r = engine.suggest_substitute_sync("海参")
    assert r.status == ToolStatus.OK
    assert r.data["substitutes"] == []
    assert r.hint


def test_compare_stores_mocked(isolated_db, monkeypatch):
    fake = [{
        "dish": "麦辣鸡腿堡",
        "prices": {"A": {"price": 21.5, "available": True}, "B": {"price": 20.0, "available": True}},
        "best_store": "B", "best_price": 20.0, "max_save": 1.5,
    }]
    monkeypatch.setattr(mcd_client, "compare_stores_sync", lambda sc: fake)
    r = engine.compare_stores_sync(["A", "B"])
    assert r.status == ToolStatus.OK
    assert r.data[0]["max_save"] == 1.5
    assert r.data_source == "mcd_mcp"


def test_compare_stores_no_token_terminal(isolated_db, monkeypatch):
    monkeypatch.delenv("MCD_MCP_TOKEN", raising=False)
    monkeypatch.delenv("MCD_TOKEN", raising=False)
    r = engine.compare_stores_sync(["A", "B"])
    assert r.status == ToolStatus.EMPTY_NEEDS_INPUT
    assert "MCD_MCP_TOKEN" in (r.hint or "")


def test_nutrition_empty_terminal(isolated_db, monkeypatch):
    # 有 Token 但 list-nutrition-foods 当前返回空（比赛 Token 权限限制）→ 如实转 EMPTY_NEEDS_INPUT，不造假
    monkeypatch.setenv("MCD_MCP_TOKEN", "x")
    monkeypatch.setattr(mcd_client, "get_nutrition_foods", lambda: [])
    r = engine.get_nutrition_sync()
    assert r.status == ToolStatus.EMPTY_NEEDS_INPUT
    assert "list-nutrition-foods" in (r.hint or "")
