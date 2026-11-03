"""
AI 聊天客户端 - 配置层
支持通过本地 .env 文件或系统环境变量动态加载模型地址与运行参数。
未配置时回退到默认本地地址 (127.0.0.1)。
"""

import os
from pathlib import Path

# ----------------------------------------------------------------------------
# 1. 尝试加载当前目录的 .env 文件
# ----------------------------------------------------------------------------
_env_loaded = False
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=True)
        _env_loaded = True
except ImportError:
    pass

# 内置轻量级 .env 解析器（兜底防呆，不强依赖 python-dotenv）
if not _env_loaded:
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        try:
            with open(_env_path, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith("#") or "=" not in _line:
                        continue
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"\'')
                    if _k:
                        os.environ[_k] = _v
        except Exception:
            pass


# ============================================================================
# 大模型配置（深度推理与复杂工具调用）
# ============================================================================
LARGE_MODEL_URL = os.getenv("LARGE_MODEL_URL", "http://127.0.0.1:8000")
LARGE_MODEL_NAME = os.getenv("LARGE_MODEL_NAME", "qwen3-next-80b-a3b")
LARGE_CTX_MAX = int(os.getenv("LARGE_CTX_MAX", "16384"))

# ============================================================================
# 小模型配置（后台静默摘要与清洗）
# ============================================================================
SMALL_MODEL_URL = os.getenv("SMALL_MODEL_URL", "http://127.0.0.1:8080")
SMALL_MODEL_NAME = os.getenv("SMALL_MODEL_NAME", "qwen3.8-27b")

# ============================================================================
# 运行时配置
# ============================================================================
SUMMARIZE_THRESHOLD = float(os.getenv("SUMMARIZE_THRESHOLD", "0.75"))
TIMEOUT = int(os.getenv("TIMEOUT", "360"))
SUMMARIZE_TIMEOUT = int(os.getenv("SUMMARIZE_TIMEOUT", "60"))
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "50"))
MAX_LINES_PER_PAGE = int(os.getenv("MAX_LINES_PER_PAGE", "200"))
