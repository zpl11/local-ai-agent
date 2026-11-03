"""
AI 聊天客户端 - 大小模型混用版 + 工业级工具调用 + Plan-and-Act TODO List

大模型: 支持本地或远程部署的大模型（如 qwen3-next-80b-a3b，通过 .env 配置）
小模型: 支持本地或远程部署的小模型（如 qwen3.8-27b，用于后台摘要）

架构（已模块化重构）：
  config.py            - 配置层
  ai_logger.py         - 日志层 (AI Observability / Execution Trace)
  session_manager.py   - 会话管理器 (Session Management)
  tools.py             - 工具层 (ParamValidator + ToolRegistry + 工具函数)
  agent.py             - Agent 引擎层 (Agent Turn Loop + Schema 注入)
  compress.py          - 压缩/摘要层 (上下文压缩)
  todo_manager.py      - 任务清单管理器 (Plan-and-Act)
  gui.py               - GUI 层 (tkinter 界面)

策略：当上下文使用率超过 75% 时，用小模型自动摘要旧对话。
"""

# 从模块化组件重新导出，保持向后兼容
from config import (
    LARGE_MODEL_URL, LARGE_MODEL_NAME, LARGE_CTX_MAX,
    SMALL_MODEL_URL, SMALL_MODEL_NAME,
    SUMMARIZE_THRESHOLD, TIMEOUT, SUMMARIZE_TIMEOUT,
    MAX_TOOL_CALLS, MAX_LINES_PER_PAGE,
)
from ai_logger import ExecutionLogger, trace_logger
from session_manager import SessionManager, session_manager
from tools import ParamValidator, ToolRegistry, registry
from agent import AgentEngine
from compress import Compressor
from todo_manager import TodoManager, todo_manager
from gui import ChatApp

# 兼容旧代码中直接引用 trace_logger
trace_logger = ExecutionLogger()

if __name__ == "__main__":
    import tkinter as tk
    root = tk.Tk()
    app = ChatApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (root.destroy()))
    root.mainloop()
