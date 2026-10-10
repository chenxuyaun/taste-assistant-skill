"""工具层测试。依赖 fastmcp（由 importorskip 控制；缺失时整文件跳过）。

覆盖：AC4 未确认不写、两段式确认后写入、幂等重放不重复写、确认缺失报错、T7 超时返回 ERROR。
"""
import asyncio

import pytest

fastmcp = pytest.importorskip("fastmcp")

from core import config
from tools import writes, recommend_tools
from storage import db
from recommend import engine
from core.guard import ToolStatus


def test_ac4_record_requires_confirmation(isolated_db):
    # 首次调用（不带 confirmed）必须返回 NEEDS_CONFIRMATION 且不写入
    r = writes.record_meal("川菜", 5, "工作日午餐")
    assert r["status"] == ToolStatus.NEEDS_CONFIRMATION
    assert "pending_id" in r
    assert db.count_meals() == 0


def test_confirm_then_write_and_idempotent(isolated_db):
    r1 = writes.record_meal("川菜", 5, "工作日午餐")
    pid = r1["pending_id"]
    r2 = writes.record_meal("川菜", 5, "工作日午餐", confirmed=True, pending_id=pid)
    assert r2["status"] == ToolStatus.OK
    assert db.count_meals() == 1
    assert db.get_profile()["dimensions"]["辣"] == 3.3
    # 同一 pending_id 重放 -> 幂等 no-op，不重复写（T1）
    r3 = writes.record_meal("川菜", 5, "工作日午餐", confirmed=True, pending_id=pid)
    assert r3["status"] == ToolStatus.OK
    assert db.count_meals() == 1


def test_confirm_without_pending_id_errors(isolated_db):
    r = writes.record_meal("川菜", 5, "工作日午餐", confirmed=True, pending_id=None)
    assert r["status"] == ToolStatus.ERROR


def test_recommend_timeout_returns_error(isolated_db, monkeypatch):
    import time

    def slow(*a, **k):
        time.sleep(config.RECOMMEND_TIMEOUT + 2)  # 故意超过预算
        from core.guard import ToolResult
        return ToolResult("OK", data=[])

    monkeypatch.setattr(engine, "recommend_dish_sync", slow)
    result = asyncio.run(recommend_tools.recommend_dish("工作日午餐"))
    assert result["status"] == ToolStatus.ERROR
    assert result.get("retryable") is True
