from storage import db, preference_learning
from recommend import engine
from core.guard import ToolStatus

PEANUT_DISHES = {"宫保鸡丁", "凉拌花生", "担担面"}
SPICY_DISHES = {"麻婆豆腐", "水煮鱼", "麻辣火锅", "辣子鸡", "酸菜鱼", "宫保鸡丁", "担担面", "酸辣土豆丝"}


def test_ac1_empty_recommend_terminal(isolated_db):
    r = engine.recommend_dish_sync("工作日午餐")
    assert r.status == ToolStatus.EMPTY_NEEDS_INPUT
    assert r.data == []
    assert r.hint  # 终态带提示，诱导 Agent 停下而非重试


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


def test_empty_weekly_menu_terminal(isolated_db):
    r = engine.generate_weekly_menu_sync()
    assert r.status == ToolStatus.EMPTY_NEEDS_INPUT


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
