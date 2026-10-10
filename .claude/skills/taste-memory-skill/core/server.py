"""fastmcp 服务实例。各 tools.* 模块通过 @mcp.tool() 注册工具，main.py 启动时 import 它们。"""
from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("taste-memory-skill")
