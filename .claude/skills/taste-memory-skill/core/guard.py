"""Loop-safe 工具结果契约 + 超时包装。

每个 MCP 工具都返回 ToolResult。status 字段是给“驱动 Agent”的**停止信号**：
- NEEDS_CONFIRMATION / EMPTY_NEEDS_INPUT / ERROR 都是**终态**——Agent 不得重试或再调，
  必须交还用户并等待。
- 只有 OK 表示可继续读取/使用 data。

这是把“死循环/乱调工具”从设计上掐死的第一道边界（R1/R2/R4/R6）。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional, Awaitable


class ToolStatus:
    OK = "OK"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"   # 终态：停下，向用户确认
    EMPTY_NEEDS_INPUT = "EMPTY_NEEDS_INPUT"     # 终态：停下，请用户先补充数据
    ERROR = "ERROR"                             # 终态：停下，如实上报错误


@dataclass
class ToolResult:
    status: str
    data: Any = None
    pending_id: Optional[str] = None
    hint: Optional[str] = None
    retryable: bool = False
    retry_after: Optional[int] = None
    fallback: Optional[str] = None
    data_source: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"status": self.status}
        if self.data is not None:
            d["data"] = self.data
        if self.pending_id is not None:
            d["pending_id"] = self.pending_id
        if self.hint is not None:
            d["hint"] = self.hint
        if self.data_source is not None:
            d["data_source"] = self.data_source
        if self.status == ToolStatus.ERROR:
            d["retryable"] = self.retryable
            if self.retry_after is not None:
                d["retry_after"] = self.retry_after
            if self.fallback is not None:
                d["fallback"] = self.fallback
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


async def with_timeout(coro: Awaitable, seconds: float, tool_name: str) -> Any:
    """硬墙钟超时。超时必须抛 TimeoutError，由调用方转成 ERROR 结果——
    绝不把超时静默吞成模拟/兜底数据（R6 / 任务书六）。
    """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{tool_name} 超过 {seconds}s 预算，已中止")
