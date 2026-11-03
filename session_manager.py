"""
AI 聊天客户端 - 会话管理器 (Session Manager)

管理对话会话的生命周期：
- 创建新会话（生成唯一 session_id）
- 归档旧会话的 trace 日志
- 切换会话上下文
"""

import os
import uuid
import shutil
from datetime import datetime


class SessionManager:
    """会话管理器：跟踪当前会话，管理 trace 日志的归档。"""

    def __init__(self, archive_dir: str = "sessions"):
        self.archive_dir = archive_dir
        os.makedirs(self.archive_dir, exist_ok=True)
        self._current_session_id: str | None = None
        self._current_session_name: str = ""
        self._created_at: str = ""

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    @property
    def current_session_name(self) -> str:
        return self._current_session_name

    @property
    def created_at(self) -> str:
        return self._created_at

    def create_session(self, name: str = "") -> str:
        """创建新会话，返回 session_id。"""
        self._current_session_id = str(uuid.uuid4())
        self._current_session_name = name or datetime.now().strftime("%m-%d %H:%M")
        self._created_at = datetime.now().isoformat()
        return self._current_session_id

    def archive_current_session(self, log_file: str = "agent_execution_trace.jsonl"):
        """将当前会话的 trace 日志归档到 sessions/ 目录。"""
        if not self._current_session_id:
            return

        if not os.path.exists(log_file):
            return

        archive_name = f"trace_{self._current_session_id[:8]}.jsonl"
        archive_path = os.path.join(self.archive_dir, archive_name)
        shutil.copy2(log_file, archive_path)

    def get_session_info(self) -> dict:
        """返回当前会话的元信息。"""
        if not self._current_session_id:
            return {"id": None, "name": None, "created_at": None}
        return {
            "id": self._current_session_id,
            "name": self._current_session_name,
            "created_at": self._created_at,
        }

    def list_archived_sessions(self) -> list[dict]:
        """列出所有已归档的会话。"""
        sessions = []
        if not os.path.exists(self.archive_dir):
            return sessions
        for fname in sorted(os.listdir(self.archive_dir)):
            if fname.startswith("trace_") and fname.endswith(".jsonl"):
                short_id = fname[6:-6]  # 去掉 "trace_" 和 ".jsonl"
                fpath = os.path.join(self.archive_dir, fname)
                lines = 0
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        lines = sum(1 for _ in f)
                except Exception:
                    pass
                sessions.append({
                    "id": short_id,
                    "file": fname,
                    "path": fpath,
                    "lines": lines,
                })
        return sessions

    def clear_current_session(self):
        """清除当前会话状态（不归档，仅重置）。"""
        self._current_session_id = None
        self._current_session_name = ""
        self._created_at = ""


# ============================================================================
# 全局单例
# ============================================================================
session_manager = SessionManager()
