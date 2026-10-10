from storage import db, preference_learning


def test_ac2_spicy_increase(isolated_db):
    # 记录一餐川菜打 5 分 -> 辣维度 +0.3
    db.insert_meal("川菜", 5, "工作日午餐", "2026-01-01T12:00:00")
    out = preference_learning.apply_meal_learning("川菜", 5)
    assert out["dimension"] == "辣"
    assert out["deltas"]["辣"] == 0.3
    assert db.get_profile()["dimensions"]["辣"] == 3.3


def test_low_rating_decrease(isolated_db):
    db.insert_meal("清蒸鲈鱼", 1, "工作日午餐", "2026-01-01T12:00:00")
    preference_learning.apply_meal_learning("清蒸鲈鱼", 1)  # 清淡
    assert db.get_profile()["dimensions"]["清淡"] == 2.7


def test_dislike_sets_dim_to_min(isolated_db):
    out = preference_learning.apply_dislike("麻辣火锅")  # 辣
    assert out["dimension"] == "辣"
    assert db.get_profile()["dimensions"]["辣"] == 1.0
    assert "麻辣火锅" in db.get_profile()["disliked_dishes"]


def test_manual_set(isolated_db):
    preference_learning.apply_manual("甜", 4.5)
    assert db.get_profile()["dimensions"]["甜"] == 4.5


def test_streak_bonus(isolated_db):
    # 先插入连续 3 次辣味高评分用餐记录（均归“辣”维度），使 streak 判定成立
    db.insert_meal("川菜", 5, "工作日午餐", "2026-01-01T12:00:00")
    db.insert_meal("辣子鸡", 5, "周末聚餐", "2026-01-02T12:00:00")
    db.insert_meal("水煮鱼", 5, "工作日午餐", "2026-01-03T12:00:00")
    out = preference_learning.apply_meal_learning("水煮鱼", 5)
    # 单次 +0.3 叠加 streak 额外 +0.5 = 净 +0.8
    assert out["deltas"]["辣"] == 0.8
    assert db.get_profile()["dimensions"]["辣"] == 3.8
