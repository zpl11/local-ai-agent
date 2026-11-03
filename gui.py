"""
AI 聊天客户端 - GUI 层

tkinter 图形界面：Canvas + Scrollbar 聊天区域，
线程安全 UI 更新，执行时间线查看窗口。
"""

import tkinter as tk
from tkinter import messagebox, ttk
import threading
import json
import requests
from datetime import datetime
import uuid

import config
from ai_logger import ExecutionLogger
from tools import ToolRegistry, registry
from agent import AgentEngine
from compress import Compressor
from todo_manager import todo_manager
from session_manager import session_manager


# 全局日志器实例
trace_logger = ExecutionLogger()


class ChatApp:
    """GUI 聊天应用主窗口。"""

    def __init__(self, root):
        self.root = root
        self.root.title("AI 聊天客户端 - 大小模型混用版 + 工具调用")
        self.root.geometry("1000x750")
        self.root.resizable(True, True)

        # 对话历史
        self.full_history = []
        self.large_ctx = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        self.msg_counter = 0
        self.is_summarizing = False

        # 使用全局工具注册
        self.registry = registry

        # 初始化 Agent 引擎
        self.agent = AgentEngine(
            model_url=config.LARGE_MODEL_URL,
            model_name=config.LARGE_MODEL_NAME,
            ctx_max=config.LARGE_CTX_MAX,
            timeout=config.TIMEOUT,
            registry=self.registry,
            logger=trace_logger,
        )
        self.agent.set_callback("on_tool_call", self._on_tool_call)
        self.agent.set_callback("on_tool_result", self._on_tool_result)
        self.agent.set_callback("on_error", self._on_tool_error)
        self.agent.set_callback("on_final", self._on_tool_final)

        # 初始化工具
        self.compressor = Compressor(logger=trace_logger)

        # 可用工具列表
        self.available_tools = self.registry.list_tools()

        # 创建初始会话
        self._create_new_session()

        self._build_ui()
        self.append_message("ai", self._get_welcome_message())
        self._update_session_label()

    def _create_new_session(self):
        """创建新会话：归档旧会话 → 生成新 session_id → 重置上下文。"""
        # 归档旧会话的 trace 日志
        session_manager.archive_current_session()
        # 创建新会话
        session_manager.create_session()
        # 重置对话上下文
        self.full_history = []
        self.large_ctx = [{"role": "system", "content": self._build_system_prompt()}]
        self.msg_counter = 0
        # 清空 TODO
        todo_manager.clear()

    # ------------------------------------------------------------------
    # 系统提示
    # ------------------------------------------------------------------
    def _build_system_prompt(self) -> str:
        return (
            "【🚨 强制第一步 — 违反将导致工作被反复拦截】\n"
            "你**必须**在处理任何复杂或多步骤任务时，**第一步且唯一第一步**调用 `init_todo_list` 工具，\n"
            "将所有要执行的步骤以**字符串列表**形式传入。正确格式示例：\n"
            "init_todo_list(tasks=[\"扫描目录结构\", \"读取核心文件\", \"分析代码逻辑\", \"写入总结报告\"])\n\n"
            "**注意：tasks 参数必须是 JSON 数组格式 `[\"...\", \"...\"]`，不能是纯文本字符串。**\n\n"

            "【渐进式拦截机制】\n"
            "如果你不调用 init_todo_list 就直接调用受限工具（read_file、write_file、execute_command）：\n"
            "- 第 1 次：系统会提醒你先规划任务\n"
            "- 第 2 次：系统会警告你已被提醒过一次\n"
            "- 第 3 次：系统会硬拦截你的工作\n"
            "- 第 4 次：系统将自动创建默认任务清单\n\n"
            "每次被拦截后，你必须立即调用 `init_todo_list` 重新规划。\n\n"

            "【Plan-and-Act 完整工作流】\n"
            "1. 第一步：调用 `init_todo_list` 规划所有步骤\n"
            "2. 对每个子任务：先调用 `update_todo_status(task_id=N, status='in_progress')`\n"
            "3. 执行子任务\n"
            "4. 完成后调用 `update_todo_status(task_id=N, status='done')`\n"
            "5. 重复 2-4 直到所有任务完成\n\n"

            "【高效代码探索与 Token 保护规则（至关重要）】\n"
            "1. 面对多个 Python 文件或理解代码全貌时，**第一优先级调用 `get_code_outline(file_path)`** 查看 AST 骨架（模块说明、类、方法签名与行号）。\n"
            "2. **极其重要**：代码讲解与分析的核心是整体架构、模块职责分工与调用链条。通过 AST 骨架已足够进行深入讲解，**严禁从头到尾逐行逐页通读所有文件源码**！\n"
            "3. 仅对 1~2 个最核心的实现细节，根据骨架行号用 `read_file(offset=..., max_lines=...)` 定向查看，禁止无脑连续翻页。\n"
            "4. 代码梳理完毕后，必须立即调用 `write_markdown_file` 将文档沉淀到本地，严禁在聊天窗口输出过长文本。\n\n"

            "【自省与动态纠错规则（极其重要）】\n"
            "1. 当工具调用返回 Error 时，绝对禁止机械盲目地重复上一轮相同的调用。\n"
            "2. 必须仔细研读报错中给出的参数契约与当前系统状态，反思错误原因并调整参数后再重新调用。\n"
            "3. TODO 状态更新仅在重要阶段完成时调用，不要微观频繁打卡。\n\n"

            "【写入文件的重要规则 — 解决 400 Bad Request】\n"
            "1. 当完成代码分析、文档整理等工作后，使用 write_file 或 write_markdown_file 将结果写入本地文件\n"
            "2. 不要将大段文本（超过 1000 字）直接输出到聊天窗口\n"
            "3. 写入文件后，工具返回简短的成功消息，不会污染对话历史\n"
            "4. 这是防止上下文溢出、避免 400 错误的核心策略\n"
        )

    def _get_welcome_message(self) -> str:
        tool_count = len(self.available_tools)
        return (
            "你好！我是 Qwen AI 助手。已启用以下能力：\n\n"
            "1. **大小模型混用**：大模型深度推理 + 小模型后台摘要\n"
            "2. **工具调用 (Function Call)**：可通过工具读取文件、浏览目录、执行命令\n"
            "3. **Plan-and-Act 任务清单**：复杂任务自动拆分步骤，逐步推进\n\n"
            f"已注册 {tool_count} 个工具: {', '.join(self.available_tools)}\n\n"
            "💡 **Plan-and-Act 工作流**：\n"
            "   复杂任务 → 先调用 `init_todo_list` 创建任务清单 →\n"
            "   每个子任务执行前设为 `in_progress` → 完成后设为 `done`\n\n"
            "💡 **正确格式**：\n"
            '   init_todo_list(tasks=["步骤1", "步骤2", "步骤3"])  ← 必须是 JSON 数组\n'
            "   ❌ 不要用纯文本字符串：init_todo_list(tasks=\"1. 步骤1\")\n\n"
            "💡 **高效读代码工作流（骨架优先 → 定向读取 → 写文件）**：\n"
            "   1. `get_code_outline` 查看 Python 代码 AST 骨架（类、函数、行号）\n"
            "   2. 针对核心逻辑用 `read_file` 定向读取关键行区间\n"
            "   3. `search_code keyword=xxx` 搜索定位关键代码\n"
            "   4. `write_markdown_file` 将分析结果写入 .md 文件\n\n"
            "💡 **为什么用 write_markdown_file？**\n"
            "   分析结果写入文件后，tool_result 只返回简短消息（几个 token），\n"
            "   避免聊天窗口被大段文本污染，彻底解决 400 Bad Request 问题。\n\n"
            "💡 **新对话**：点击顶部栏 `➕ 新对话` 按钮可开始全新对话，\n"
            "   当前对话的 trace 日志会自动归档到 `sessions/` 目录。\n\n"
            "💡 **拦截机制**：如果直接调用受限工具（read_file 等）而不先规划任务，\n"
            "   系统会分四级递进拦截：提醒 → 警告 → 硬拦截 → 自动兜底。\n\n"
            "试试对我说：'读取当前目录下的文件' 或 '查看系统信息'"
        )

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ---- 顶部栏 ----
        top_frame = tk.Frame(self.root, bg="#2c3e50", pady=8)
        top_frame.pack(fill="x")

        tk.Label(top_frame, text="AI 聊天", font=("Microsoft YaHei", 14, "bold"),
                 fg="white", bg="#2c3e50").pack(side="left", padx=10)

        tool_info = f"🔧 {len(self.available_tools)} 个工具就绪"
        self.lbl_tools = tk.Label(top_frame, text=tool_info, font=("Microsoft YaHei", 9),
                                  fg="#f39c12", bg="#2c3e50")
        self.lbl_tools.pack(side="left", padx=10)

        # 新对话按钮
        btn_new = tk.Button(top_frame, text="➕ 新对话", font=("Microsoft YaHei", 9, "bold"),
                            bg="#27ae60", fg="white", relief="flat",
                            command=self.new_conversation, padx=10)
        btn_new.pack(side="right", padx=5)

        self.btn_summary = tk.Button(top_frame, text="手动摘要", font=("Microsoft YaHei", 9),
                                     bg="#9b59b6", fg="white", relief="flat",
                                     command=self.manual_summarize, padx=10)
        self.btn_summary.pack(side="right", padx=5)

        btn_trace = tk.Button(top_frame, text="查看时间线", font=("Microsoft YaHei", 9),
                              bg="#3498db", fg="white", relief="flat",
                              command=self.show_trace_window, padx=10)
        btn_trace.pack(side="right", padx=5)

        btn_archive = tk.Button(top_frame, text="📁 归档会话", font=("Microsoft YaHei", 9),
                                bg="#16a085", fg="white", relief="flat",
                                command=self.show_archived_sessions, padx=10)
        btn_archive.pack(side="right", padx=5)

        btn_clear = tk.Button(top_frame, text="清空对话", font=("Microsoft YaHei", 9),
                              bg="#e74c3c", fg="white", relief="flat",
                              command=self.clear_chat, padx=10)
        btn_clear.pack(side="right", padx=5)

        # ---- TODO 列表展示区 ----
        self.todo_frame = tk.Frame(self.root, bg="#fff9e6", bd=1, relief="solid")
        self.todo_frame.pack(fill="x", padx=5, pady=(0, 0))

        self.lbl_todo_header = tk.Label(
            self.todo_frame, text="📌 TODO List", font=("Microsoft YaHei", 9, "bold"),
            fg="#e67e22", bg="#fff9e6", anchor="w")
        self.lbl_todo_header.pack(fill="x", padx=8, pady=4)

        self.txt_todo = tk.Text(
            self.todo_frame, font=("Microsoft YaHei", 9), bg="#fff9e6", fg="#555",
            height=3, wrap="word", state="disabled", bd=0, padx=8, pady=2)
        self.txt_todo.pack(fill="x", padx=8, pady=(0, 4))

        # ---- 状态栏 ----
        self.status_var = tk.StringVar(value=(
            f"就绪 | 大模型: {config.LARGE_MODEL_URL} | 小模型: {config.SMALL_MODEL_URL}"
        ))
        tk.Label(self.root, textvariable=self.status_var,
                 font=("Microsoft YaHei", 8), bg="#ecf0f1",
                 fg="#7f8c8d", anchor="w", pady=3).pack(fill="x")

        # ---- 聊天区域 ----
        chat_outer = tk.Frame(self.root)
        chat_outer.pack(fill="both", expand=True, padx=5, pady=5)

        self.chat_canvas = tk.Canvas(chat_outer, bg="#f5f5f5", highlightthickness=0)
        scrollbar = tk.Scrollbar(chat_outer, orient="vertical", command=self.chat_canvas.yview)
        self.chat_scroll_frame = tk.Frame(self.chat_canvas, bg="#f5f5f5")

        self.chat_scroll_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        )

        self.chat_canvas.create_window((0, 0), window=self.chat_scroll_frame, anchor="nw")
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)

        self.chat_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.chat_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.chat_scroll_frame.bind("<MouseWheel>", self._on_mousewheel)

        # ---- 输入区域 ----
        input_frame = tk.Frame(self.root, bg="white", pady=8, padx=10)
        input_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.entry = tk.Entry(input_frame, font=("Microsoft YaHei", 11),
                              bd=1, relief="solid")
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.on_send())

        btn_send = tk.Button(input_frame, text="发送",
                             font=("Microsoft YaHei", 10, "bold"),
                             bg="#27ae60", fg="white", relief="flat",
                             command=self.on_send, width=6)
        btn_send.pack(side="right")

    def _on_mousewheel(self, event):
        self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _scroll_to_bottom(self):
        self.chat_canvas.yview_moveto(1)

    # ------------------------------------------------------------------
    # TODO 列表展示
    # ------------------------------------------------------------------
    def _update_todo_display(self):
        """刷新 TODO 列表展示区域。"""
        todos = todo_manager.get_all()
        if not todos:
            self.txt_todo.config(state="normal")
            self.txt_todo.delete("1.0", tk.END)
            self.txt_todo.config(state="disabled")
            self.todo_frame.pack_forget()
            return

        self.todo_frame.pack(fill="x", padx=5, pady=(0, 0))
        done_count = sum(1 for t in todos if t["status"] == "done")
        self.lbl_todo_header.config(
            text=f"📌 TODO List ({done_count}/{len(todos)} 已完成)"
        )

        lines = []
        for t in todos:
            icon = {"pending": "⏳", "in_progress": "🔄", "done": "✅"}.get(t["status"], "⏳")
            lines.append(f"[{t['id']}] {icon} {t['task']} ({t['status']})")

        self.txt_todo.config(state="normal")
        self.txt_todo.delete("1.0", tk.END)
        self.txt_todo.insert("1.0", "\n".join(lines))
        self.txt_todo.config(state="disabled")

    def _on_tool_result(self, name: str, result: str):
        # Plan-and-Act: 如果执行了 TODO 工具，刷新展示
        if name in ("init_todo_list", "update_todo_status"):
            self.root.after(0, self._update_todo_display)

        display = result[:500] + (" ..." if len(result) > 500 else "")
        self.root.after(0, lambda: self._append_tool_result(name, display))

    # ------------------------------------------------------------------
    # 消息发送
    # ------------------------------------------------------------------
    def on_send(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, tk.END)
            self.send_message(text)

    def get_ctx_usage_pct(self):
        """估算当前上下文使用率"""
        if not self.large_ctx:
            return 0
        total_chars = sum(len(str(m.get("content", ""))) for m in self.large_ctx)
        estimated_tokens = int(total_chars * 0.5)
        return estimated_tokens / config.LARGE_CTX_MAX

    def send_message(self, user_text):
        """发送消息"""
        self.append_message("user", user_text)
        self.full_history.append({"role": "user", "content": user_text})

        threading.Thread(target=self._send_with_maybe_summarize,
                         args=(user_text,), daemon=True).start()

    def _send_with_maybe_summarize(self, user_text):
        """发送消息，必要时先摘要"""
        trace_id = str(uuid.uuid4())
        self.large_ctx.append({"role": "user", "content": user_text})

        pct = self.get_ctx_usage_pct()
        if pct > config.SUMMARIZE_THRESHOLD and len(self.large_ctx) > 6:
            self._summarize_context(trace_id)

        loading_id = self.append_message("ai", "思考中...", is_loading=True)

        def api_call():
            messages = list(self.large_ctx)
            result = self.agent.run(messages, trace_id=trace_id)

            if result is None:
                self.root.after(0, lambda: self.update_message(
                    loading_id, "[错误] 请求失败", is_error=True))
                return

            self.large_ctx.append({"role": "assistant", "content": result})
            self.full_history.append({"role": "assistant", "content": result})

            self.root.after(0, lambda: self.update_message(loading_id, result))

            new_pct = self.get_ctx_usage_pct()
            self.root.after(0, lambda: self.status_var.set(
                f"上下文使用率 {new_pct*100:.0f}% | 大模型: {config.LARGE_MODEL_URL}"))

        threading.Thread(target=api_call, daemon=True).start()

    # ------------------------------------------------------------------
    # Agent 回调 (UI 线程安全)
    # ------------------------------------------------------------------
    def _on_tool_call(self, name: str, args_str: str):
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {}
        self.root.after(0, lambda: self._append_tool_call(name, args))

    def _on_tool_error(self, error_msg: str):
        self.root.after(0, lambda: self._append_tool_error(error_msg))

    def _on_tool_final(self, content: str):
        pass  # 由 _send_with_maybe_summarize 统一处理

    def _append_tool_call(self, name: str, args: dict):
        args_text = json.dumps(args, ensure_ascii=False)
        self.append_message("tool", f"🔧 调用工具: `{name}`\n   参数: {args_text}",
                            is_loading=False, is_error=False)

    def _append_tool_result(self, name: str, result: str):
        self.append_message("tool_result", f"✅ 工具 `{name}` 返回:\n{result}",
                            is_loading=False, is_error=False)

    def _append_tool_error(self, error_msg: str):
        self.append_message("tool_error", f"❌ 工具调用错误:\n{error_msg}",
                            is_loading=False, is_error=True)

    # ------------------------------------------------------------------
    # UI 辅助
    # ------------------------------------------------------------------
    def append_message(self, role, text, is_loading=False, is_error=False):
        msg_id = self.msg_counter
        self.msg_counter += 1

        now = datetime.now().strftime("%H:%M:%S")

        if role == "user":
            label, color, bg = "你", "#1a73e8", "#e8f0fe"
        elif role == "tool":
            label, color, bg = "🔧 工具请求", "#e67e22", "#fef9e7"
        elif role == "tool_result":
            label, color, bg = "✅ 工具结果", "#27ae60", "#eafaf1"
        elif role == "tool_error":
            label, color, bg = "❌ 工具错误", "#e74c3c", "#fce8e6"
        elif role == "system":
            label, color, bg = "系统", "#8e44ad", "#f5eef8"
        else:
            label, color, bg = "AI", "#34a853", "#f1f8e9" if not is_error else "#fce8e6"

        frame = tk.Frame(self.chat_scroll_frame, bg=bg, bd=1, relief="ridge")
        frame.pack(fill="x", padx=5, pady=2)

        header = tk.Frame(frame, bg=bg)
        header.pack(fill="x")
        tk.Label(header, text=label, font=("Microsoft YaHei", 9, "bold"),
                 fg=color, bg=bg, width=10, anchor="w").pack(side="left")
        tk.Label(header, text=now, font=("Microsoft YaHei", 8),
                 fg="#999", bg=bg, anchor="e").pack(side="right")

        tk.Label(frame, text=text, font=("Microsoft YaHei", 10),
                 fg="#333" if not is_error else "#d32f2f",
                 bg=bg, justify="left", wraplength=850, anchor="w").pack(
            padx=8, pady=4)

        self._scroll_to_bottom()
        return msg_id

    def update_message(self, msg_id, text, is_error=False):
        frames = self.chat_scroll_frame.winfo_children()
        if 0 <= msg_id < len(frames):
            frame = frames[msg_id]
            labels = [w for w in frame.winfo_children()
                      if isinstance(w, tk.Label) and w.cget("wraplength") != ""]
            if labels:
                labels[-1].config(text=text,
                                  fg="#d32f2f" if is_error else "#333")
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # 时间线日志窗口（增强版：支持按 trace_id 过滤）
    # ------------------------------------------------------------------
    def show_trace_window(self):
        """打开时间线日志查看窗口（支持按 trace_id 过滤 + 归档会话列表）。"""
        win = tk.Toplevel(self.root)
        win.title("执行时间线日志 (Execution Trace)")
        win.geometry("900x650")
        win.resizable(True, True)

        # ---- 工具栏 ----
        toolbar = tk.Frame(win, bg="#2c3e50", pady=5)
        toolbar.pack(fill="x", padx=5, pady=5)

        # trace_id 下拉选择
        tk.Label(toolbar, text="Trace ID:", font=("Microsoft YaHei", 9),
                 fg="#ccc", bg="#2c3e50").pack(side="left", padx=(5, 3))

        trace_ids = trace_logger.get_unique_trace_ids()
        self.trace_var = tk.StringVar(value="全部")
        combo = ttk.Combobox(toolbar, textvariable=self.trace_var,
                             width=22, state="readonly", font=("Microsoft YaHei", 8))
        combo["values"] = ["全部"] + [f"{tid[:8]}..." for tid in trace_ids]
        combo.pack(side="left", padx=3)
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_trace_text(text_area))

        btn_refresh_list = tk.Button(toolbar, text="🔄 刷新列表", font=("Microsoft YaHei", 9),
                                     bg="#3498db", fg="white", relief="flat",
                                     command=lambda: self._refresh_trace_list(combo, text_area))
        btn_refresh_list.pack(side="left", padx=3)

        btn_copy = tk.Button(toolbar, text="📋 复制日志", font=("Microsoft YaHei", 9),
                             bg="#27ae60", fg="white", relief="flat",
                             command=lambda: self._copy_trace_to_clipboard(win))
        btn_copy.pack(side="left", padx=3)

        btn_clear = tk.Button(toolbar, text="🗑 清空日志", font=("Microsoft YaHei", 9),
                              bg="#e74c3c", fg="white", relief="flat",
                              command=lambda: self._confirm_clear_trace(text_area))
        btn_clear.pack(side="left", padx=3)

        # 统计信息
        self.lbl_trace_stats = tk.Label(toolbar, text=f"共 {len(trace_ids)} 条 trace",
                                        font=("Microsoft YaHei", 8), fg="#f39c12",
                                        bg="#2c3e50", anchor="e")
        self.lbl_trace_stats.pack(side="right", padx=5)

        # ---- 日志文本区 ----
        text_frame = tk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=5, pady=5)

        scrollbar = tk.Scrollbar(text_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        text_area = tk.Text(text_frame, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                            yscrollcommand=scrollbar.set, wrap="none", state="disabled")
        text_area.pack(fill="both", expand=True)
        scrollbar.config(command=text_area.yview)

        self._refresh_trace_text(text_area)
        text_area.bind("<Control-a>", lambda e: text_area.event_generate("<<SelectAll>>"))

    def _refresh_trace_list(self, combo, text_area):
        """刷新 trace_id 下拉列表。"""
        trace_ids = trace_logger.get_unique_trace_ids()
        combo["values"] = ["全部"] + [f"{tid[:8]}..." for tid in trace_ids]
        self.trace_var.set("全部")
        self.lbl_trace_stats.config(text=f"共 {len(trace_ids)} 条 trace")
        self._refresh_trace_text(text_area)

    def _refresh_trace_text(self, text_area):
        """根据当前 trace 选择刷新日志内容。"""
        selected = self.trace_var.get()

        if selected == "全部":
            content = trace_logger.read_all_logs()
        else:
            # 从显示文本还原 trace_id（去掉 "..."）
            short = selected.replace("...", "")
            all_ids = trace_logger.get_unique_trace_ids()
            target_id = None
            for tid in all_ids:
                if tid.startswith(short):
                    target_id = tid
                    break
            if target_id:
                events = trace_logger.get_trace_events(target_id)
                lines = []
                for event in events:
                    lines.append(json.dumps(event, ensure_ascii=False))
                content = "\n".join(lines) if lines else f"(trace {target_id[:8]}... 无事件)"
            else:
                content = f"(未找到 trace: {selected})"

        text_area.config(state="normal")
        text_area.delete("1.0", tk.END)
        text_area.insert("1.0", content if content else "(暂无日志记录)")
        text_area.config(state="disabled")

    def _copy_trace_to_clipboard(self, win):
        selected = self.trace_var.get()
        if selected == "全部":
            content = trace_logger.read_all_logs()
        else:
            short = selected.replace("...", "")
            all_ids = trace_logger.get_unique_trace_ids()
            target_id = None
            for tid in all_ids:
                if tid.startswith(short):
                    target_id = tid
                    break
            if target_id:
                events = trace_logger.get_trace_events(target_id)
                content = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
            else:
                content = ""

        if not content or content == "(暂无日志记录)":
            messagebox.showinfo("提示", "暂无日志记录。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update()
        messagebox.showinfo("成功", "日志已复制到剪贴板！")

    def _confirm_clear_trace(self, text_area):
        if messagebox.askyesno("确认", "确定清空所有时间线日志？此操作不可恢复。"):
            trace_logger.clear_logs()
            self._refresh_trace_text(text_area)
            messagebox.showinfo("提示", "日志已清空。")

    # ------------------------------------------------------------------
    # 归档会话窗口
    # ------------------------------------------------------------------
    def show_archived_sessions(self):
        """打开已归档会话列表窗口。"""
        win = tk.Toplevel(self.root)
        win.title("已归档会话 (Archived Sessions)")
        win.geometry("700x500")
        win.resizable(True, True)

        # 工具栏
        toolbar = tk.Frame(win, bg="#16a085", pady=5)
        toolbar.pack(fill="x", padx=5, pady=5)

        tk.Label(toolbar, text="📁 已归档会话", font=("Microsoft YaHei", 11, "bold"),
                 fg="white", bg="#16a085").pack(side="left", padx=10)

        btn_refresh = tk.Button(toolbar, text="🔄 刷新", font=("Microsoft YaHei", 9),
                                bg="white", fg="#16a085", relief="flat",
                                command=lambda: self._refresh_archive_list(tree))
        btn_refresh.pack(side="right", padx=5)

        btn_open = tk.Button(toolbar, text="📂 打开日志", font=("Microsoft YaHei", 9),
                             bg="#3498db", fg="white", relief="flat",
                             command=lambda: self._open_archive_log(tree))
        btn_open.pack(side="right", padx=5)

        btn_delete = tk.Button(toolbar, text="🗑 删除选中", font=("Microsoft YaHei", 9),
                               bg="#e74c3c", fg="white", relief="flat",
                               command=lambda: self._delete_archive(tree))
        btn_delete.pack(side="right", padx=5)

        # 表格
        tree_frame = tk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = tk.Scrollbar(tree_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        columns = ("id", "file", "lines")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                            yscrollcommand=scrollbar.set, selectmode="extended")
        tree.pack(fill="both", expand=True)
        scrollbar.config(command=tree.yview)

        tree.heading("id", text="Session ID (前8位)")
        tree.heading("file", text="文件名")
        tree.heading("lines", text="日志行数")
        tree.column("id", width=150, anchor="w")
        tree.column("file", width=300, anchor="w")
        tree.column("lines", width=100, anchor="center")

        self._refresh_archive_list(tree)

    def _refresh_archive_list(self, tree):
        """刷新归档会话列表。"""
        # 清空现有行
        for item in tree.get_children():
            tree.delete(item)

        sessions = session_manager.list_archived_sessions()
        for s in sessions:
            tree.insert("", "end", values=(s["id"], s["file"], s["lines"]))

        if sessions:
            tk.Label(tree, text=f"共 {len(sessions)} 个已归档会话",
                     font=("Microsoft YaHei", 8), fg="#666", bg="white").pack(
                side="bottom", pady=3)

    def _open_archive_log(self, tree):
        """打开选中归档会话的日志文件。"""
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个会话。")
            return
        item = tree.item(selection[0])
        file_path = item["values"][1]  # file 列
        if messagebox.askyesno("确认", f"是否在资源管理器中打开文件：\n{file_path}"):
            import subprocess
            subprocess.Popen(['explorer', '/select,', file_path])

    def _delete_archive(self, tree):
        """删除选中的归档会话。"""
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个会话。")
            return
        item = tree.item(selection[0])
        file_path = item["values"][1]
        if messagebox.askyesno("确认", f"确定删除归档会话：\n{file_path}？"):
            try:
                import os
                os.remove(file_path)
                self._refresh_archive_list(tree)
                messagebox.showinfo("提示", "已删除。")
            except Exception as e:
                messagebox.showerror("错误", f"删除失败：{e}")

    # ------------------------------------------------------------------
    # 对话管理
    # ------------------------------------------------------------------
    def new_conversation(self):
        """开始新对话：归档旧会话 → 创建新 session → 清空 UI。"""
        if self.full_history:
            if not messagebox.askyesno("确认", "当前对话将归档，是否开始新对话？"):
                return
        else:
            if not messagebox.askyesno("确认", "确定开始新对话？当前对话记录将被清空。"):
                return

        # 创建新会话（自动归档旧 trace）
        session_manager.archive_current_session()
        session_manager.create_session()

        # 重置上下文和 UI
        self.full_history = []
        self.large_ctx = [{"role": "system", "content": self._build_system_prompt()}]
        self.msg_counter = 0
        todo_manager.clear()
        for widget in self.chat_scroll_frame.winfo_children():
            widget.destroy()

        # 更新 UI 显示
        self._update_session_label()
        self._append_tool_result("system", f"✅ 新对话已创建 (Session: {session_manager.current_session_id[:8]})")
        self.append_message("ai", self._get_welcome_message())

    def clear_chat(self):
        """清空当前对话（不清理上下文，仅清空 UI 显示）。"""
        if messagebox.askyesno("确认", "确定清空所有对话记录？"):
            self.full_history.clear()
            self.large_ctx = [{"role": "system", "content": self._build_system_prompt()}]
            for widget in self.chat_scroll_frame.winfo_children():
                widget.destroy()
            self.append_message("ai", "对话已清空，请重新发送消息。")

    def _update_session_label(self):
        """更新状态栏中的会话信息。"""
        info = session_manager.get_session_info()
        session_text = f"Session: {info['id'][:8] if info['id'] else 'None'}"
        self.status_var.set(
            f"{session_text} | 大模型: {config.LARGE_MODEL_URL} | 小模型: {config.SMALL_MODEL_URL}"
        )

    # ------------------------------------------------------------------
    # 摘要
    # ------------------------------------------------------------------
    def manual_summarize(self):
        if self.is_summarizing:
            messagebox.showinfo("提示", "摘要进行中，请稍候...")
            return
        if len(self.large_ctx) < 4:
            messagebox.showinfo("提示", "对话轮次太少，无需摘要。")
            return
        self.append_message("system", "[手动摘要] 正在压缩对话历史...", is_loading=False)
        threading.Thread(target=self._summarize_context, daemon=True).start()

    def _summarize_context(self, parent_trace_id: str = None):
        """用小模型摘要上下文"""
        if self.is_summarizing:
            return
        self.is_summarizing = True

        msgs_to_summarize = [m for m in self.large_ctx[1:-1]
                             if m["role"] in ("user", "assistant")]

        if not msgs_to_summarize:
            self.is_summarizing = False
            return

        history_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
            for m in msgs_to_summarize[-10:]
        )

        if parent_trace_id:
            trace_logger.log_step(parent_trace_id, "summary", {
                "trigger": "auto",
                "msgs_to_summarize": len(msgs_to_summarize),
                "history_preview": history_text[:200],
            })

        prompt = (
            "请将以下对话历史压缩为精炼摘要，保留关键信息和上下文，"
            "控制在 500 字以内：\n\n"
            f"{history_text}"
        )

        def summarize_thread():
            try:
                resp = requests.post(f"{config.SMALL_MODEL_URL}/v1/completions", json={
                    "model": config.SMALL_MODEL_NAME,
                    "prompt": prompt,
                    "max_tokens": 512
                }, timeout=config.SUMMARIZE_TIMEOUT)
                resp.raise_for_status()
                summary = resp.json()["choices"][0]["text"]

                before_ctx = len(self.large_ctx)
                self.large_ctx = [
                    self.large_ctx[0],
                    {"role": "user", "content": f"[历史对话摘要]\n{summary}"},
                    self.large_ctx[-1]
                ]
                after_ctx = len(self.large_ctx)

                if parent_trace_id:
                    trace_logger.log_step(parent_trace_id, "summary", {
                        "status": "completed",
                        "before_count": before_ctx,
                        "after_count": after_ctx,
                        "summary_preview": summary[:200],
                    })

                self.root.after(0, lambda: self.append_message(
                    "system",
                    f"[摘要完成] 对话已压缩，当前上下文使用率: {self.get_ctx_usage_pct()*100:.0f}%",
                    is_loading=False, is_error=False))

            except Exception as e:
                if parent_trace_id:
                    trace_logger.log_step(parent_trace_id, "error", {
                        "type": "SummarizeError",
                        "message": str(e),
                    })
                self.root.after(0, lambda: self.append_message(
                    "system", f"[摘要失败] {type(e).__name__}: {e}",
                    is_loading=False, is_error=True))
            finally:
                self.is_summarizing = False

        threading.Thread(target=summarize_thread, daemon=True).start()


# ============================================================================
# 入口
# ============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = ChatApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (root.destroy()))
    root.mainloop()
