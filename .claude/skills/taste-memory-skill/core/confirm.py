"""两段式写入确认 + 幂等（R1）。

写入类工具**绝不在首次调用时执行**。首次调用（confirmed=False）创建一条 pending
操作并返回 NEEDS_CONFIRMATION + 稳定 pending_id；Agent 必须把确认话术交给用户并停下。
第二次调用（confirmed=True + 同一 pending_id）校验有效性后执行。重复同一 pending_id
是**幂等 no-op**——即使 Agent 因重试重复调用，也不会写两次（T1）。

为什么这样能防死循环：MCP 工具是一次请求/响应，无法阻塞等用户输入。把“等确认”
显式建模成终态 + pending 句柄，Agent 的唯一合法后续动作就是“带 pending_id 再调一次”，
任何其他重调/自作主张写入都会被拒绝或判定为已完成。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional, Tuple

from core.guard import ToolResult, ToolStatus
from core import config


def _db():
    # 延迟导入，避免与 storage 包的导入顺序问题
    from storage import db
    return db


def stage_write(
    op_key: str,
    payload: dict,
    confirmed: bool,
    pending_id: Optional[str],
    confirm_prompt: str,
) -> Tuple[ToolResult, bool, Optional[dict]]:
    """返回 (result, should_write, payload)。

    - confirmed=False  -> (NEEDS_CONFIRMATION, False, None)  不写
    - confirmed=True 且 pending 有效 -> (OK, True, payload)  调用方执行写入
    - 同一 pending 已完成重放 -> (OK, False, <已完成结果>)  幂等 no-op
    - 缺 pending_id / 已失效 -> (ERROR, False, None)         拒绝
    """
    store = _db()
    if not confirmed:
        pid = uuid.uuid4().hex
        expires = int(time.time()) + config.PENDING_TTL
        store.save_pending(pid, op_key, json.dumps(payload, ensure_ascii=False), expires)
        return ToolResult(ToolStatus.NEEDS_CONFIRMATION, pending_id=pid, hint=confirm_prompt), False, None

    if not pending_id:
        return ToolResult(ToolStatus.ERROR, hint="缺少 pending_id，无法确认写入", retryable=False), False, None

    done = store.get_completed(pending_id)
    if done is not None:
        # 幂等重放：该确认写操作已经执行过
        return ToolResult(ToolStatus.OK, data=done), False, None

    row = store.get_pending(pending_id)
    if row is None or row["op_key"] != op_key or row["expires"] < int(time.time()):
        store.clear_pending(pending_id)
        return ToolResult(ToolStatus.ERROR, hint="确认已失效或无效，请重新发起写入", retryable=False), False, None

    return ToolResult(ToolStatus.OK), True, payload


def mark_completed(pending_id: str, result: dict) -> None:
    _db().mark_completed(pending_id, result)
