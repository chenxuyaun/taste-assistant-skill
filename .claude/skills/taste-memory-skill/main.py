"""MCP Server 入口。从该目录运行：python main.py

把本目录加入 sys.path，确保 `core / models / storage / recommend / tools` 可直接导入；
导入各 tools.* 模块以注册 @mcp.tool()；初始化本地 SQLite；启动服务。
"""
from __future__ import annotations

import os
import sys

# 自动加载 .env（若已安装 python-dotenv），让 MCD_MCP_TOKEN 等配置在 `python main.py` 时生效；
# 未安装则退化为仅读取已 export 的环境变量，不影响其它功能。
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.server import mcp  # FastMCP 实例

# 导入工具模块，触发 @mcp.tool() 注册
import tools.profile        # noqa: F401
import tools.history        # noqa: F401
import tools.writes         # noqa: F401
import tools.recommend_tools  # noqa: F401

from storage import db

db.init()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
