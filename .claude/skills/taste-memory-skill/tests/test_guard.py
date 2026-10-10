import asyncio

import pytest

from core.guard import ToolResult, ToolStatus, with_timeout


def test_ok_omits_error_fields():
    d = ToolResult(ToolStatus.OK, data={"a": 1}).to_dict()
    assert d["status"] == "OK"
    assert "retryable" not in d
    assert "fallback" not in d


def test_error_includes_error_fields():
    d = ToolResult(ToolStatus.ERROR, hint="x", retryable=True, retry_after=2, fallback="safe").to_dict()
    assert d["status"] == "ERROR"
    assert d["retryable"] is True
    assert d["retry_after"] == 2
    assert d["fallback"] == "safe"


def test_needs_confirmation_shape():
    d = ToolResult(ToolStatus.NEEDS_CONFIRMATION, pending_id="p1", hint="确认?").to_dict()
    assert d["status"] == "NEEDS_CONFIRMATION"
    assert d["pending_id"] == "p1"


def test_with_timeout_ok():
    assert asyncio.run(with_timeout(asyncio.sleep(0.001, result=7), 1.0, "t")) == 7


def test_with_timeout_expires():
    with pytest.raises(TimeoutError):
        asyncio.run(with_timeout(asyncio.sleep(5), 0.05, "t"))
