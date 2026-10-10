"""SQLite 存储层。本地优先，不联网、不存储任何凭据。

表结构（字段含义见注释）：
- taste_profile  : 单行(id=1) 口味维度评分 + 饮食限制（JSON 列）
- meal_records   : 每餐一行
- preference_log : 每次权重变化的追加日志（可审计）
- pending_ops    : 两段式确认的暂存（带过期）
- completed_ops  : 已完成写操作的幂等记录（短时间 TTL）

路径：默认 ~/.taste_memory/taste.db，可用环境变量 TASTE_DB_PATH 覆盖（测试用）。
"""
from __future__ import annotations

import os
import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from models.schemas import TASTE_DIMENSIONS

DEFAULT_DB_PATH = os.path.expanduser("~/.taste_memory/taste.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS taste_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    dimensions_json TEXT NOT NULL,   -- 六个维度 1-5 分
    allergens_json TEXT NOT NULL,    -- 过敏原列表
    avoid_json TEXT NOT NULL,        -- 忌口食材列表
    religious_json TEXT NOT NULL,    -- 宗教饮食规则列表
    disliked_json TEXT NOT NULL,     -- 不想再吃的菜列表
    updated_at TEXT NOT NULL         -- 更新时间戳 ISO8601
);
CREATE TABLE IF NOT EXISTS meal_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dish_name TEXT NOT NULL,         -- 菜品名
    rating INTEGER NOT NULL,         -- 评分 1-5
    scene TEXT NOT NULL,             -- 场景
    timestamp TEXT NOT NULL          -- ISO8601
);
CREATE TABLE IF NOT EXISTS preference_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,         -- 变化时间
    rule TEXT NOT NULL,              -- meal_rating / streak_bonus / manual / dislike
    dimension TEXT,                  -- 受影响维度
    delta REAL,                      -- 变化量
    reason TEXT                      -- 原因
);
CREATE TABLE IF NOT EXISTS pending_ops (
    pid TEXT PRIMARY KEY,
    op_key TEXT NOT NULL,            -- 操作类型（如 record_meal）
    payload_json TEXT NOT NULL,      -- 待确认的操作参数
    expires INTEGER NOT NULL         -- 过期时间（unix 秒）
);
CREATE TABLE IF NOT EXISTS completed_ops (
    pid TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,       -- 该确认写操作的返回结果（用于幂等重放）
    created_at INTEGER NOT NULL      -- 完成时间
);
"""


def db_path() -> str:
    return os.environ.get("TASTE_DB_PATH", DEFAULT_DB_PATH)


@contextmanager
def get_conn():
    p = db_path()
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(p, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def default_profile_dict() -> dict:
    return {
        "dimensions": {d: 3.0 for d in TASTE_DIMENSIONS},
        "allergens": [],
        "avoid_foods": [],
        "religious_rules": [],
        "disliked_dishes": [],
        "updated_at": _now(),
    }


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


# ---------- 口味档案 ----------
def get_profile() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM taste_profile WHERE id=1").fetchone()
    return _row_to_profile(row) if row else None


def upsert_profile(p: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO taste_profile (id, dimensions_json, allergens_json, avoid_json,
               religious_json, disliked_json, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 dimensions_json=excluded.dimensions_json,
                 allergens_json=excluded.allergens_json,
                 avoid_json=excluded.avoid_json,
                 religious_json=excluded.religious_json,
                 disliked_json=excluded.disliked_json,
                 updated_at=excluded.updated_at""",
            (
                json.dumps(p["dimensions"], ensure_ascii=False),
                json.dumps(p["allergens"], ensure_ascii=False),
                json.dumps(p["avoid_foods"], ensure_ascii=False),
                json.dumps(p["religious_rules"], ensure_ascii=False),
                json.dumps(p["disliked_dishes"], ensure_ascii=False),
                p["updated_at"],
            ),
        )


def _row_to_profile(row) -> dict:
    return {
        "dimensions": json.loads(row["dimensions_json"]),
        "allergens": json.loads(row["allergens_json"]),
        "avoid_foods": json.loads(row["avoid_json"]),
        "religious_rules": json.loads(row["religious_json"]),
        "disliked_dishes": json.loads(row["disliked_json"]),
        "updated_at": row["updated_at"],
    }


def count_meals() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM meal_records").fetchone()["c"]


def has_meaningful_profile() -> bool:
    """是否已有足够信息可直接推荐（无需先让用户记录）。

    有任一用餐记录，或设置了饮食限制，或手动改过维度 -> True。
    完全空白（全新库、无任何设置）-> False，此时推荐应返回 EMPTY_NEEDS_INPUT。
    """
    if count_meals() > 0:
        return True
    p = get_profile()
    if p is None:
        return False
    if p["allergens"] or p["avoid_foods"] or p["religious_rules"] or p["disliked_dishes"]:
        return True
    if any(v != 3.0 for v in p["dimensions"].values()):
        return True
    return False


# ---------- 用餐记录 ----------
def insert_meal(dish_name: str, rating: int, scene: str, timestamp: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO meal_records (dish_name, rating, scene, timestamp) VALUES (?, ?, ?, ?)",
            (dish_name, rating, scene, timestamp),
        )
        return cur.lastrowid


def get_meals(dateRange: Optional[str] = None, limit: int = 20) -> list:
    """按时间倒序返回用餐记录。dateRange 形如 '2026-01-01..2026-01-31'。"""
    sql = "SELECT dish_name, rating, scene, timestamp FROM meal_records"
    args: list = []
    if dateRange:
        start, _, end = dateRange.partition("..")
        if start:
            sql += " WHERE timestamp >= ?"
            args.append(start)
        if end:
            sql += (" AND" if start else " WHERE") + " timestamp <= ?"
            args.append(end)
    sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def get_recent_meals(limit: int) -> list:
    """最近 limit 餐（倒序），供 streak 判定使用。"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT dish_name, rating FROM meal_records ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def get_recent_dish_names(days: int) -> list:
    """最近 days 天内吃过的菜名，供推荐去重。"""
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dish_name FROM meal_records WHERE timestamp >= ?", (cutoff,)
        ).fetchall()
    return [r["dish_name"] for r in rows]


# ---------- 偏好变化日志 ----------
def log_pref(timestamp: str, rule: str, dimension: Optional[str], delta: Optional[float], reason: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO preference_log (timestamp, rule, dimension, delta, reason) VALUES (?, ?, ?, ?, ?)",
            (timestamp, rule, dimension, delta, reason),
        )


def get_pref_log(limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT timestamp, rule, dimension, delta, reason FROM preference_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- 两段式确认 / 幂等 ----------
def save_pending(pid: str, op_key: str, payload_json: str, expires: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_ops (pid, op_key, payload_json, expires) VALUES (?, ?, ?, ?)",
            (pid, op_key, payload_json, expires),
        )


def get_pending(pid: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM pending_ops WHERE pid=?", (pid,)).fetchone()
    return dict(row) if row else None


def clear_pending(pid: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_ops WHERE pid=?", (pid,))


def mark_completed(pid: str, result: dict) -> None:
    from core import config
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO completed_ops (pid, result_json, created_at) VALUES (?, ?, ?)",
            (pid, json.dumps(result, ensure_ascii=False), int(time.time())),
        )


def get_completed(pid: str) -> Optional[dict]:
    from core import config
    with get_conn() as conn:
        row = conn.execute("SELECT result_json, created_at FROM completed_ops WHERE pid=?", (pid,)).fetchone()
    if row is None:
        return None
    # 超过 TTL 视为忘记，强制重新确认（防止极旧的 pending_id 永久幂等）
    if int(time.time()) - row["created_at"] > config.COMPLETED_TTL:
        conn.execute("DELETE FROM completed_ops WHERE pid=?", (pid,))
        return None
    return json.loads(row["result_json"])
