from storage import db


def test_profile_roundtrip(isolated_db):
    assert db.get_profile() is None
    p = db.default_profile_dict()
    p["allergens"] = ["花生"]
    db.upsert_profile(p)
    got = db.get_profile()
    assert got["allergens"] == ["花生"]
    assert got["dimensions"]["辣"] == 3.0


def test_meal_insert_and_query(isolated_db):
    db.insert_meal("川菜", 5, "工作日午餐", "2026-01-01T12:00:00")
    rows = db.get_meals()
    assert len(rows) == 1
    assert rows[0]["dish_name"] == "川菜"
    assert db.count_meals() == 1


def test_pending_and_completed(isolated_db):
    db.save_pending("pid1", "op", "{}", 9_999_999_999)
    assert db.get_pending("pid1")["op_key"] == "op"
    db.mark_completed("pid1", {"ok": True})
    assert db.get_completed("pid1") == {"ok": True}


def test_has_meaningful_profile_empty(isolated_db):
    assert db.has_meaningful_profile() is False


def test_has_meaningful_profile_with_allergen(isolated_db):
    p = db.default_profile_dict()
    p["allergens"] = ["花生"]
    db.upsert_profile(p)
    assert db.has_meaningful_profile() is True
