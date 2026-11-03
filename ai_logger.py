"""
AI 聊天客户端 - 日志层 (AI Observability / Execution Trace)

工业级执行时间线追踪器。
- 落地 JSONL 文件（每行一个合法 JSON，方便后续分析/回放）
- 控制台打印格式化日志（方便盯着看）
- 支持 UI 窗口查看 + 一键复制
"""

import threading
import json
import os
from datetime import datetime


class ExecutionLogger:
    """
    工业级执行时间线追踪器。
    - 每个 trace_id 代表一次 Agent Turn Loop（一次用户请求的完整执行）
    - 所有 trace 追加写入同一个 JSONL 文件
    - 支持按 session 归档
    """

    def __init__(self, log_file: str = "agent_execution_trace.jsonl"):
        self.log_file = log_file
        dir_name = os.path.dirname(os.path.abspath(log_file))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        self._lock = threading.Lock()

    def log_step(self, trace_id: str, step_type: str, details: dict):
        """
        结构化记录每一步动作。
        step_type: 'user_input', 'llm_request', 'llm_response',
                   'tool_call', 'tool_result', 'summary', 'error', 'run_end'
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id,
            "type": step_type,
            "details": details,
        }

        with self._lock:
            # 1. 落地 JSONL（追加模式）
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

            # 2. 控制台打印
            ts = event["timestamp"][11:19]
            tid = trace_id[:8]
            detail_preview = json.dumps(details, ensure_ascii=False)[:150]
            print(f"[{ts}] [TRACE {tid}] [{step_type.upper():15s}] {detail_preview}...")

    def read_all_logs(self) -> str:
        """读取全部日志内容（用于 UI 展示和复制）。"""
        if not os.path.exists(self.log_file):
            return "(暂无日志记录)"
        with open(self.log_file, "r", encoding="utf-8") as f:
            return f.read()

    def get_unique_trace_ids(self) -> list[str]:
        """从日志中提取所有唯一的 trace_id（按出现顺序）。"""
        if not os.path.exists(self.log_file):
            return []
        trace_ids = []
        seen = set()
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    tid = event.get("trace_id", "")
                    if tid and tid not in seen:
                        trace_ids.append(tid)
                        seen.add(tid)
                except json.JSONDecodeError:
                    continue
        return trace_ids

    def get_trace_events(self, trace_id: str) -> list[dict]:
        """获取指定 trace_id 的所有事件。"""
        events = []
        if not os.path.exists(self.log_file):
            return events
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("trace_id") == trace_id:
                        events.append(event)
                except json.JSONDecodeError:
                    continue
        return events

    def clear_logs(self):
        """清空日志文件。"""
        if os.path.exists(self.log_file):
            os.remove(self.log_file)


# ============================================================================
# 全局日志器实例
# ============================================================================
trace_logger = ExecutionLogger()
