"""
AI 聊天客户端 - 任务清单管理器 (Plan-and-Act TODO List)

维护一个结构化的任务清单，支持增删改查。
让 AI 在每一步执行前先审视 TODO List，实现"先出清单 → 逐步勾选 → 状态闭环"。
"""

import threading


class TodoManager:
    """轻量级任务管理器，内存中维护当前任务的进展。"""

    def __init__(self):
        self.todos = []
        self._lock = threading.Lock()

    def set_todos(self, tasks: list[str]) -> str:
        """初始化或重置任务清单。

        @param tasks: 任务步骤的字符串列表（例如：['扫描目录', '读取核心文件', '写入总结报告']）。
        """
        with self._lock:
            self.todos = [
                {"id": i + 1, "task": t, "status": "pending"}
                for i, t in enumerate(tasks)
            ]
        return self.get_status_str()

    def update_todo(self, task_id: int, status: str) -> str:
        """更新指定任务的状态：pending（待办）, in_progress（进行中）, done（已完成）。

        @param task_id: 任务编号（ID）。
        @param status: 状态必须是以下之一: 'pending', 'in_progress', 'done'。
        """
        if status not in ("pending", "in_progress", "done"):
            return "Error: status 必须是 pending, in_progress 或 done 之一。"

        with self._lock:
            for item in self.todos:
                if item["id"] == task_id:
                    item["status"] = status
                    break
            else:
                available = [f"#{t['id']}: {t['task']} ({t['status']})" for t in self.todos]
                avail_str = "\n  - ".join(available) if available else "当前暂无任务"
                return (
                    f"Error: 未找到 ID 为 {task_id} 的任务。\n"
                    f"【当前活跃任务清单】：\n  - {avail_str}\n"
                    f"请从上述任务列表中选择合法的数字 ID 进行状态更新。"
                )

        return f"Success: 任务 #{task_id} 状态已更新为 {status}\n{self.get_status_str()}"

    def get_status_str(self) -> str:
        """生成格式化的任务清单字符串，用于注入 Prompt。"""
        if not self.todos:
            return "\n【当前暂无活跃的 TODO 任务清单】\n"

        lines = ["\n--- 📌 实时任务清单 (TODO List) ---"]
        for item in self.todos:
            icon = (
                "⏳" if item["status"] == "pending"
                else "🔄" if item["status"] == "in_progress"
                else "✅"
            )
            lines.append(f"[{item['id']}] {icon} {item['task']} ({item['status']})")
        lines.append("--------------------------------------\n")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        """检查任务清单是否为空。"""
        with self._lock:
            return len(self.todos) == 0

    def get_all(self) -> list[dict]:
        """返回当前任务清单的完整副本（供 UI 展示）。"""
        with self._lock:
            return [dict(item) for item in self.todos]

    def clear(self):
        """清空任务清单。"""
        with self._lock:
            self.todos = []


# ============================================================================
# 全局单例
# ============================================================================
todo_manager = TodoManager()
