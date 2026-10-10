# 麦味记忆 MCP Server 镜像
# 基于 Python 3.11（项目要求 >=3.11）
FROM python:3.11-slim

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制仓库（.env / *.db 已被 .dockerignore 排除，绝不进镜像）
COPY . .

# 入口：拉起 MCP Server（main.py 内部自动 load_dotenv + sys.path 注入）
# Token 通过 -e 或 --env-file 在运行时注入，例如：
#   docker run --rm -e MCD_MCP_TOKEN=xxx -e MCD_CITY=成都市 -e MCD_KEYWORD=春熙路 taste-memory
CMD ["python", ".claude/skills/taste-memory-skill/main.py"]
