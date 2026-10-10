"""全局可调参数。墙钟超时是防死循环/挂起的硬边界（R6）。"""
from __future__ import annotations

READ_TIMEOUT = 0.2            # 只读工具预算（秒）
RECOMMEND_TIMEOUT = 2.0      # 单菜推荐预算（秒）
WEEKLY_TIMEOUT = 5.0         # 周菜单预算（秒）
MAX_TOOL_CALLS_PER_TURN = 8  # 单轮 Agent 调用上限（SKILL.md 软约束，配合服务端幂等/超时）
PENDING_TTL = 300            # 两段式确认 pending 有效期（秒）
COMPLETED_TTL = 600          # 已完成写操作幂等记录有效期（秒）
