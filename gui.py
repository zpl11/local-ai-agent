"""
AI 聊天客户端 - GUI 层 (现代化工业级重构版)

特性与升级：
1. 现代视觉设计：扁平化卡片布局、精选现代调色板、流线型层次与细致边框
2. 微交互体验：按钮 Hover 动态高亮反馈、手势光标、状态加载动态提示
3. 多行智能输入：多行自适应输入框，支持 Enter 极速发送与 Shift+Enter 自由换行
4. Plan-and-Act 可视化看板：任务进度条、状态徽章、支持优雅折叠/展开
5. 自适应响应式气泡：随窗口宽度动态调整排版折行，代码块等宽渲染
6. 统一设计语言：时间线追踪窗口与归档窗口均采用沉浸式现代终端与精致表格风格
"""

import tkinter as tk
from tkinter import messagebox, ttk
import threading
import json
import requests
from datetime import datetime
import uuid
import os
import subprocess

import config
from ai_logger import ExecutionLogger
from tools import ToolRegistry, registry
from agent import AgentEngine
from compress import Compressor
from todo_manager import todo_manager
from session_manager import session_manager


# 全局日志器实例
trace_logger = ExecutionLogger()

# ----------------------------------------------------------------------
# 现代设计语言与配色规范 (Design Tokens)
# ----------------------------------------------------------------------
THEME = {
    # 基础色
    "bg_main": "#f8fafc",         # 主背景 Slate-50
    "bg_card": "#ffffff",         # 卡片白
    "bg_header": "#0f172a",       # 顶部沉稳深空色 Slate-900
    "border_light": "#e2e8f0",    # 浅边框 Slate-200
    "border_subtle": "#cbd5e1",   # 次级边框 Slate-300
    "text_main": "#0f172a",       # 主文本 Slate-900
    "text_sub": "#64748b",        # 次要文本 Slate-500
    "text_muted": "#94a3b8",      # 弱化文本 Slate-400

    # 品牌与功能色
    "primary": "#2563eb",         # 科技蓝 Blue-600
    "primary_hover": "#1d4ed8",   # Blue-700
    "success": "#10b981",         # 翡翠绿 Emerald-500
    "success_hover": "#059669",   # Emerald-600
    "warning": "#f59e0b",         # 琥珀黄 Amber-500
    "warning_hover": "#d97706",   # Amber-600
    "danger": "#ef4444",          # 珊瑚红 Red-500
    "danger_hover": "#dc2626",    # Red-600
    "purple": "#8b5cf6",          # 紫水晶 Violet-500
    "purple_hover": "#7c3aed",    # Violet-600
    "teal": "#0d9488",            # 水鸭青 Teal-600
    "teal_hover": "#0f766e",      # Teal-700
    "cyan": "#0284c7",            # 蔚蓝 Sky-600
    "cyan_hover": "#0369a1",      # Sky-700

    # 气泡配色体系
    "bubble_user_bg": "#eff6ff",     # 用户气泡底色 (柔和淡蓝)
    "bubble_user_border": "#bfdbfe", # 用户气泡描边
    "bubble_user_text": "#1e3a8a",
    "bubble_user_tag": "#2563eb",

    "bubble_ai_bg": "#ffffff",       # AI 气泡底色 (纯白卡片)
    "bubble_ai_border": "#e2e8f0",   # AI 气泡描边
    "bubble_ai_text": "#1e293b",
    "bubble_ai_tag": "#059669",

    "bubble_tool_bg": "#0f172a",     # 工具请求 (极客暗黑终端风格)
    "bubble_tool_border": "#334155",
    "bubble_tool_text": "#e2e8f0",
    "bubble_tool_tag": "#f59e0b",

    "bubble_result_bg": "#f0fdf4",   # 工具结果 (清新薄荷绿)
    "bubble_result_border": "#bbf7d0",
    "bubble_result_text": "#14532d",
    "bubble_result_tag": "#16a34a",

    "bubble_error_bg": "#fef2f2",    # 错误提示 (浅红警示)
    "bubble_error_border": "#fecaca",
    "bubble_error_text": "#991b1b",
    "bubble_error_tag": "#dc2626",

    "bubble_system_bg": "#faf5ff",   # 系统/摘要通知 (柔紫)
    "bubble_system_border": "#e9d5ff",
    "bubble_system_text": "#581c87",
    "bubble_system_tag": "#7c3aed",

    # 字体设定
    "font_family": "Microsoft YaHei UI",
    "font_code": "Consolas",
}


def create_modern_button(parent, text, bg, fg="white", hover_bg=None,
                         command=None, font_size=9, bold=False, padx=12, pady=5):
    """创建扁平现代、带 Hover 微交互与手势反馈的高质感按钮。"""
    font_weight = "bold" if bold else "normal"
    btn = tk.Button(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        activebackground=hover_bg or bg,
        activeforeground=fg,
        font=(THEME["font_family"], font_size, font_weight),
        relief="flat",
        bd=0,
        padx=padx,
        pady=pady,
        cursor="hand2",
        command=command
    )
    if hover_bg:
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


class ChatApp:
    """现代工业级 GUI 聊天应用主窗口。"""

    def __init__(self, root):
        self.root = root
        self.root.title("Local AI Agent - 工业级本地智能体协同平台")
        self.root.geometry("1100x800")
        self.root.minsize(900, 650)
        self.root.configure(bg=THEME["bg_main"])

        # 对话历史
        self.full_history = []
        self.large_ctx = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        self.msg_counter = 0
        self.is_summarizing = False
        self.is_sending = False
        self.todo_expanded = True

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

        # 初始化工具与会话
        self.compressor = Compressor(logger=trace_logger)
        self.available_tools = self.registry.list_tools()
        self._create_new_session()

        # 构建现代化 UI 界面
        self._build_ui()
        self.append_message("ai", self._get_welcome_message())
        self._update_session_label()

    def _create_new_session(self):
        """创建新会话：归档旧会话 → 生成新 session_id → 重置上下文。"""
        session_manager.archive_current_session()
        session_manager.create_session()
        self.full_history = []
        self.large_ctx = [{"role": "system", "content": self._build_system_prompt()}]
        self.msg_counter = 0
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
            "👋 **你好！欢迎使用工业级 Local AI Agent 混合智能协同平台。**\n\n"
            "🌟 **核心架构与驱动能力**：\n"
            "• **大模型驱动引擎**：深层长上下文推理与工具编排决策\n"
            "• **小模型后台常驻**：对话上下文自动滑动摘要与实时修剪压缩\n"
            "• **工业级 Function Call**：已安全挂载 " + str(tool_count) + " 个本地系统级工具\n"
            "• **Plan-and-Act 规划闭环**：任务清单自动分解、实时进度看板与渐进式拦截\n\n"
            "🛠️ **挂载工具**：`" + "`, `".join(self.available_tools) + "`\n\n"
            "💡 **开始体验**：您可以直接告诉我您的目标，例如：\n"
            "   • “扫描项目目录结构并生成架构概览”\n"
            "   • “分析 agent.py 的核心函数调用链并输出分析报告”"
        )

    # ------------------------------------------------------------------
    # UI 构建 (现代化重构)
    # ------------------------------------------------------------------
    def _build_ui(self):
        # 1. 现代化顶部导航栏
        self._build_top_nav()

        # 2. Plan-and-Act 任务看板 (TODO)
        self._build_todo_dashboard()

        # 3. 聊天消息区 (Canvas + Scrollbar)
        self._build_chat_area()

        # 4. 底部现代化输入框与多行发送区
        self._build_input_area()

        # 5. 底部系统状态栏
        self._build_status_bar()

    def _build_top_nav(self):
        """现代化深色顶部导航栏，集成系统品牌标识与快捷操作。"""
        top_bar = tk.Frame(self.root, bg=THEME["bg_header"], height=56)
        top_bar.pack(fill="x")
        top_bar.pack_propagate(False)

        # 品牌与标志
        brand_frame = tk.Frame(top_bar, bg=THEME["bg_header"])
        brand_frame.pack(side="left", padx=16, pady=8)

        logo_lbl = tk.Label(
            brand_frame, text="⚡", font=(THEME["font_family"], 14),
            fg="#38bdf8", bg=THEME["bg_header"]
        )
        logo_lbl.pack(side="left", padx=(0, 6))

        title_lbl = tk.Label(
            brand_frame, text="Local AI Agent", font=(THEME["font_family"], 12, "bold"),
            fg="#f8fafc", bg=THEME["bg_header"]
        )
        title_lbl.pack(side="left")

        # 工具就绪徽章 (Pill Badge)
        tool_badge = tk.Frame(top_bar, bg="#1e293b", padx=8, pady=3)
        tool_badge.pack(side="left", padx=12, pady=14)
        self.lbl_tools = tk.Label(
            tool_badge, text=f"🔧 {len(self.available_tools)} 工具就绪",
            font=(THEME["font_family"], 8, "bold"), fg="#38bdf8", bg="#1e293b"
        )
        self.lbl_tools.pack()

        # 顶部操作按钮组 (从右往左依次布局)
        btn_frame = tk.Frame(top_bar, bg=THEME["bg_header"])
        btn_frame.pack(side="right", padx=14, pady=10)

        # 按钮样式统一配置
        b_clear = create_modern_button(
            btn_frame, "清空", bg="#334155", fg="#cbd5e1",
            hover_bg=THEME["danger"], command=self.clear_chat, font_size=8
        )
        b_clear.pack(side="right", padx=4)

        b_archive = create_modern_button(
            btn_frame, "📁 归档会话", bg="#1e293b", fg="#94a3b8",
            hover_bg=THEME["teal"], command=self.show_archived_sessions, font_size=8
        )
        b_archive.pack(side="right", padx=4)

        b_trace = create_modern_button(
            btn_frame, "⏱ 时间线", bg="#1e293b", fg="#94a3b8",
            hover_bg=THEME["cyan"], command=self.show_trace_window, font_size=8
        )
        b_trace.pack(side="right", padx=4)

        self.btn_summary = create_modern_button(
            btn_frame, "⚡ 手动摘要", bg="#1e293b", fg="#94a3b8",
            hover_bg=THEME["purple"], command=self.manual_summarize, font_size=8
        )
        self.btn_summary.pack(side="right", padx=4)

        b_new = create_modern_button(
            btn_frame, "➕ 新会话", bg=THEME["success"], fg="#ffffff",
            hover_bg=THEME["success_hover"], command=self.new_conversation, font_size=8, bold=True
        )
        b_new.pack(side="right", padx=4)

    def _build_todo_dashboard(self):
        """Plan-and-Act 任务看板：带进度条、徽章与优雅折叠。"""
        self.todo_frame = tk.Frame(self.root, bg="#ffffff", bd=0)
        # 默认有任务时自动展示，初始隐藏
        self.todo_frame.pack(fill="x", padx=16, pady=(10, 0))

        # 顶条容器
        header_bar = tk.Frame(self.todo_frame, bg="#f1f5f9", padx=12, pady=6)
        header_bar.pack(fill="x")

        self.lbl_todo_title = tk.Label(
            header_bar, text="📋 Plan-and-Act 任务编排看板",
            font=(THEME["font_family"], 9, "bold"), fg="#1e293b", bg="#f1f5f9"
        )
        self.lbl_todo_title.pack(side="left")

        self.lbl_todo_stats = tk.Label(
            header_bar, text="0/0 已完成 (0%)",
            font=(THEME["font_family"], 8, "bold"), fg=THEME["primary"], bg="#f1f5f9"
        )
        self.lbl_todo_stats.pack(side="left", padx=10)

        # 折叠/展开按钮
        self.btn_toggle_todo = tk.Button(
            header_bar, text="▲ 折叠看板", font=(THEME["font_family"], 8),
            fg="#64748b", bg="#f1f5f9", relief="flat", bd=0, cursor="hand2",
            command=self._toggle_todo_visibility
        )
        self.btn_toggle_todo.pack(side="right")

        # 进度条 (Canvas 绘制现代扁平胶囊条)
        self.todo_progress_canvas = tk.Canvas(self.todo_frame, height=4, bg="#e2e8f0", bd=0, highlightthickness=0)
        self.todo_progress_canvas.pack(fill="x")

        # 任务清单展示容器
        self.todo_body = tk.Frame(self.todo_frame, bg="#ffffff", padx=12, pady=8)
        self.todo_body.pack(fill="x")

        self.txt_todo = tk.Text(
            self.todo_body, font=(THEME["font_family"], 9), bg="#ffffff", fg="#334155",
            height=3, wrap="word", state="disabled", bd=0, relief="flat", padx=4, pady=2
        )
        self.txt_todo.pack(fill="x")

        # 初始无任务时先隐藏整个看板
        self.todo_frame.pack_forget()

    def _toggle_todo_visibility(self):
        """折叠/展开 TODO 列表内容。"""
        if self.todo_expanded:
            self.todo_body.pack_forget()
            self.btn_toggle_todo.config(text="▼ 展开看板")
            self.todo_expanded = False
        else:
            self.todo_body.pack(fill="x")
            self.btn_toggle_todo.config(text="▲ 折叠看板")
            self.todo_expanded = True

    def _build_chat_area(self):
        """构建自适应聊天滚动区域。"""
        chat_container = tk.Frame(self.root, bg=THEME["bg_main"])
        chat_container.pack(fill="both", expand=True, padx=16, pady=10)

        self.chat_canvas = tk.Canvas(
            chat_container, bg=THEME["bg_main"], bd=0, highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(
            chat_container, orient="vertical", command=self.chat_canvas.yview
        )
        self.chat_scroll_frame = tk.Frame(self.chat_canvas, bg=THEME["bg_main"])

        # 动态绑定滚动区域与窗口大小自适应
        self.chat_scroll_window = self.chat_canvas.create_window(
            (0, 0), window=self.chat_scroll_frame, anchor="nw"
        )

        def _on_canvas_configure(event):
            # 保持内部滚动容器与 Canvas 宽度一致
            self.chat_canvas.itemconfig(self.chat_scroll_window, width=event.width)
            self._adjust_wraplength_all()

        self.chat_canvas.bind("<Configure>", _on_canvas_configure)
        self.chat_scroll_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        )

        self.chat_canvas.configure(yscrollcommand=scrollbar.set)
        self.chat_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.chat_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.chat_scroll_frame.bind("<MouseWheel>", self._on_mousewheel)

    def _build_input_area(self):
        """现代卡片输入区域，支持多行文本、自适应滚动与快捷发送键。"""
        input_card = tk.Frame(
            self.root, bg=THEME["bg_card"],
            highlightbackground=THEME["border_light"],
            highlightthickness=1,
            padx=12, pady=8
        )
        input_card.pack(fill="x", padx=16, pady=(0, 6))

        # 文本输入框 (Text 替换原生单行 Entry)
        self.text_input = tk.Text(
            input_card,
            font=(THEME["font_family"], 10),
            bg=THEME["bg_card"],
            fg=THEME["text_main"],
            height=3,
            wrap="word",
            bd=0,
            relief="flat",
            padx=4,
            pady=4,
            insertbackground=THEME["primary"]
        )
        self.text_input.pack(side="left", fill="both", expand=True)

        # 键盘快捷键绑定: Enter 发送, Shift+Enter 换行
        self.text_input.bind("<Return>", self._on_enter_pressed)
        self.text_input.bind("<Shift-Return>", lambda e: None)  # 保持原生换行

        # 右侧操作栏 (快捷提示与发送按钮)
        right_panel = tk.Frame(input_card, bg=THEME["bg_card"])
        right_panel.pack(side="right", fill="y", padx=(8, 0))

        # 快捷键微型提示标签
        hint_lbl = tk.Label(
            right_panel, text="Enter 发送\nShift+Enter 换行",
            font=(THEME["font_family"], 7), fg=THEME["text_muted"], bg=THEME["bg_card"],
            justify="center"
        )
        hint_lbl.pack(pady=(2, 4))

        self.btn_send = create_modern_button(
            right_panel, "✈ 发送", bg=THEME["primary"], fg="white",
            hover_bg=THEME["primary_hover"], command=self.on_send,
            font_size=9, bold=True, padx=14, pady=6
        )
        self.btn_send.pack()

    def _build_status_bar(self):
        """底部状态栏，呈现会话 ID、服务连通性与上下文负载。"""
        self.status_bar = tk.Frame(self.root, bg="#f1f5f9", height=28, padx=16)
        self.status_bar.pack(fill="x", side="bottom")

        # 状态指示灯 (绿点)
        self.status_dot = tk.Label(
            self.status_bar, text="●", font=(THEME["font_family"], 9),
            fg=THEME["success"], bg="#f1f5f9"
        )
        self.status_dot.pack(side="left", padx=(0, 4))

        self.status_left_var = tk.StringVar(value="服务在线 | 初始化中...")
        self.lbl_status_left = tk.Label(
            self.status_bar, textvariable=self.status_left_var,
            font=(THEME["font_family"], 8), fg="#64748b", bg="#f1f5f9"
        )
        self.lbl_status_left.pack(side="left")

        # 右侧模型与上下文占用指标
        self.status_right_var = tk.StringVar(value="上下文负载: 0%")
        self.lbl_status_right = tk.Label(
            self.status_bar, textvariable=self.status_right_var,
            font=(THEME["font_family"], 8, "bold"), fg=THEME["primary"], bg="#f1f5f9"
        )
        self.lbl_status_right.pack(side="right")

    def _on_mousewheel(self, event):
        self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _scroll_to_bottom(self):
        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def _on_enter_pressed(self, event):
        """处理 Enter 键逻辑：若没有按下 Shift 键，则触发发送。"""
        if event.state & 0x0001:  # Shift 键按下
            return None
        self.on_send()
        return "break"  # 阻止 Text 控件产生默认多余回车

    def _adjust_wraplength_all(self):
        """当窗口宽度变化时，自适应调整全部消息气泡的折行宽度。"""
        canvas_width = self.chat_canvas.winfo_width()
        if canvas_width < 100:
            return
        # 预留内边距
        wrap_width = max(300, canvas_width - 80)
        for frame in self.chat_scroll_frame.winfo_children():
            # 找到包含 wraplength 属性的 Label
            for child in frame.winfo_children():
                if isinstance(child, tk.Label) and child.cget("wraplength") > 0:
                    child.config(wraplength=wrap_width)

    # ------------------------------------------------------------------
    # TODO 任务看板动态更新
    # ------------------------------------------------------------------
    def _update_todo_display(self):
        """刷新 TODO 列表展示区域与进度条。"""
        todos = todo_manager.get_all()
        if not todos:
            self.txt_todo.config(state="normal")
            self.txt_todo.delete("1.0", tk.END)
            self.txt_todo.config(state="disabled")
            self.todo_frame.pack_forget()
            return

        self.todo_frame.pack(fill="x", padx=16, pady=(10, 0))
        total = len(todos)
        done_count = sum(1 for t in todos if t["status"] == "done")
        pct = int((done_count / total) * 100) if total > 0 else 0

        self.lbl_todo_stats.config(
            text=f"{done_count}/{total} 已完成 ({pct}%)",
            fg=THEME["success"] if pct == 100 else THEME["primary"]
        )

        # 刷新进度条 Canvas
        self.todo_progress_canvas.delete("all")
        width = self.todo_progress_canvas.winfo_width()
        if width <= 1:
            width = 1000
        fill_width = int(width * (pct / 100.0))
        bar_color = THEME["success"] if pct == 100 else THEME["primary"]
        self.todo_progress_canvas.create_rectangle(0, 0, fill_width, 4, fill=bar_color, width=0)

        lines = []
        for t in todos:
            icon = {"pending": "⏳ 待执行", "in_progress": "🔄 执行中", "done": "✅ 已完成"}.get(t["status"], "⏳")
            lines.append(f"[{t['id']}]  {icon}  —  {t['task']}")

        self.txt_todo.config(state="normal")
        self.txt_todo.delete("1.0", tk.END)
        self.txt_todo.insert("1.0", "\n".join(lines))
        self.txt_todo.config(state="disabled")

    def _on_tool_result(self, name: str, result: str):
        # Plan-and-Act: 如果执行了 TODO 工具，刷新展示
        if name in ("init_todo_list", "update_todo_status"):
            self.root.after(0, self._update_todo_display)

        display = result[:500] + (" ... [已截断保留]" if len(result) > 500 else "")
        self.root.after(0, lambda: self._append_tool_result(name, display))

    # ------------------------------------------------------------------
    # 消息发送
    # ------------------------------------------------------------------
    def on_send(self):
        if self.is_sending:
            return

        text = self.text_input.get("1.0", tk.END).strip()
        if text:
            self.text_input.delete("1.0", tk.END)
            self.send_message(text)

    def get_ctx_usage_pct(self):
        """估算当前上下文使用率"""
        if not self.large_ctx:
            return 0
        total_chars = sum(len(str(m.get("content", ""))) for m in self.large_ctx)
        estimated_tokens = int(total_chars * 0.5)
        return estimated_tokens / config.LARGE_CTX_MAX

    def send_message(self, user_text):
        """发送消息并启动后台推理线程。"""
        self.is_sending = True
        self.btn_send.config(text="思考中...", bg=THEME["warning"], state="disabled")
        self.status_dot.config(fg=THEME["warning"])

        self.append_message("user", user_text)
        self.full_history.append({"role": "user", "content": user_text})

        threading.Thread(target=self._send_with_maybe_summarize,
                         args=(user_text,), daemon=True).start()

    def _send_with_maybe_summarize(self, user_text):
        """发送消息，必要时自动触发后台小模型摘要。"""
        trace_id = str(uuid.uuid4())
        self.large_ctx.append({"role": "user", "content": user_text})

        pct = self.get_ctx_usage_pct()
        if pct > config.SUMMARIZE_THRESHOLD and len(self.large_ctx) > 6:
            self._summarize_context(trace_id)

        loading_id = self.append_message("ai", "🧠 思考中，正在规划与执行...", is_loading=True)

        def api_call():
            try:
                messages = list(self.large_ctx)
                result = self.agent.run(messages, trace_id=trace_id)

                if result is None:
                    self.root.after(0, lambda: self.update_message(
                        loading_id, "❌ [错误] 模型请求失败或异常中断，请检查服务地址与日志。", is_error=True))
                    return

                self.large_ctx.append({"role": "assistant", "content": result})
                self.full_history.append({"role": "assistant", "content": result})

                self.root.after(0, lambda: self.update_message(loading_id, result))

            finally:
                new_pct = self.get_ctx_usage_pct()
                self.root.after(0, lambda: self._on_finish_turn(new_pct))

        threading.Thread(target=api_call, daemon=True).start()

    def _on_finish_turn(self, ctx_pct: float):
        """单轮对话结束后恢复发送状态与刷新指示灯。"""
        self.is_sending = False
        self.btn_send.config(text="✈ 发送", bg=THEME["primary"], state="normal")
        self.status_dot.config(fg=THEME["success"])
        self.status_right_var.set(f"上下文负载: {ctx_pct*100:.0f}%")
        self._update_session_label()

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
        pass

    def _append_tool_call(self, name: str, args: dict):
        args_text = json.dumps(args, ensure_ascii=False, indent=2)
        self.append_message("tool", f"🔧 调用工具: `{name}`\n{args_text}")

    def _append_tool_result(self, name: str, result: str):
        self.append_message("tool_result", f"✅ 工具 `{name}` 返回结果:\n{result}")

    def _append_tool_error(self, error_msg: str):
        self.append_message("tool_error", f"❌ 工具执行异常:\n{error_msg}", is_error=True)

    # ------------------------------------------------------------------
    # 现代化气泡渲染
    # ------------------------------------------------------------------
    def append_message(self, role, text, is_loading=False, is_error=False):
        """渲染高质感、现代卡片式消息气泡。"""
        msg_id = self.msg_counter
        self.msg_counter += 1
        now = datetime.now().strftime("%H:%M:%S")

        # 角色配置映射
        if role == "user":
            tag_text = "👤 您"
            tag_fg = THEME["bubble_user_tag"]
            bg_color = THEME["bubble_user_bg"]
            border_color = THEME["bubble_user_border"]
            text_color = THEME["bubble_user_text"]
            font_family = THEME["font_family"]
        elif role == "tool":
            tag_text = "⚡ 工具执行请求"
            tag_fg = THEME["bubble_tool_tag"]
            bg_color = THEME["bubble_tool_bg"]
            border_color = THEME["bubble_tool_border"]
            text_color = THEME["bubble_tool_text"]
            font_family = THEME["font_code"]
        elif role == "tool_result":
            tag_text = "📦 工具返回数据"
            tag_fg = THEME["bubble_result_tag"]
            bg_color = THEME["bubble_result_bg"]
            border_color = THEME["bubble_result_border"]
            text_color = THEME["bubble_result_text"]
            font_family = THEME["font_family"]
        elif role == "tool_error":
            tag_text = "⚠️ 拦截与执行告警"
            tag_fg = THEME["bubble_error_tag"]
            bg_color = THEME["bubble_error_bg"]
            border_color = THEME["bubble_error_border"]
            text_color = THEME["bubble_error_text"]
            font_family = THEME["font_family"]
        elif role == "system":
            tag_text = "⚙️ 系统管理通知"
            tag_fg = THEME["bubble_system_tag"]
            bg_color = THEME["bubble_system_bg"]
            border_color = THEME["bubble_system_border"]
            text_color = THEME["bubble_system_text"]
            font_family = THEME["font_family"]
        else:
            tag_text = "🤖 Qwen AI 助手"
            tag_fg = THEME["bubble_ai_tag"]
            bg_color = THEME["bubble_ai_bg"] if not is_error else THEME["bubble_error_bg"]
            border_color = THEME["bubble_ai_border"] if not is_error else THEME["bubble_error_border"]
            text_color = THEME["bubble_ai_text"] if not is_error else THEME["bubble_error_text"]
            font_family = THEME["font_family"]

        # 卡片外层包装框
        card = tk.Frame(
            self.chat_scroll_frame,
            bg=bg_color,
            highlightbackground=border_color,
            highlightthickness=1,
            padx=12, pady=10
        )
        card.pack(fill="x", padx=6, pady=4)

        # 气泡头部 (胶囊徽章 + 灰度时间戳)
        header = tk.Frame(card, bg=bg_color)
        header.pack(fill="x", pady=(0, 4))

        tk.Label(
            header, text=tag_text, font=(THEME["font_family"], 9, "bold"),
            fg=tag_fg, bg=bg_color
        ).pack(side="left")

        tk.Label(
            header, text=now, font=(THEME["font_family"], 8),
            fg=THEME["text_muted"], bg=bg_color
        ).pack(side="right")

        # 内容主体
        canvas_width = self.chat_canvas.winfo_width()
        wrap_width = max(300, canvas_width - 80) if canvas_width > 100 else 850

        content_lbl = tk.Label(
            card,
            text=text,
            font=(font_family, 10),
            fg=text_color,
            bg=bg_color,
            justify="left",
            wraplength=wrap_width,
            anchor="w"
        )
        content_lbl.pack(fill="x", pady=(2, 0))

        self._scroll_to_bottom()
        return msg_id

    def update_message(self, msg_id, text, is_error=False):
        """更新正在 loading 的气泡内容。"""
        frames = self.chat_scroll_frame.winfo_children()
        if 0 <= msg_id < len(frames):
            card = frames[msg_id]
            labels = [w for w in card.winfo_children()
                      if isinstance(w, tk.Label) and w.cget("wraplength") > 0]
            if labels:
                labels[-1].config(
                    text=text,
                    fg=THEME["bubble_error_text"] if is_error else THEME["bubble_ai_text"]
                )
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # 执行时间线窗口 (沉浸式暗黑终端风格)
    # ------------------------------------------------------------------
    def show_trace_window(self):
        """打开时间线日志查看窗口（现代化终端面板设计）。"""
        win = tk.Toplevel(self.root)
        win.title("执行时间线追踪 (Execution Trace Timeline)")
        win.geometry("960x680")
        win.configure(bg="#0f172a")

        # 现代化深色工具栏
        toolbar = tk.Frame(win, bg="#1e293b", padx=12, pady=10)
        toolbar.pack(fill="x")

        tk.Label(
            toolbar, text="Trace ID:", font=(THEME["font_family"], 9, "bold"),
            fg="#94a3b8", bg="#1e293b"
        ).pack(side="left", padx=(0, 6))

        trace_ids = trace_logger.get_unique_trace_ids()
        self.trace_var = tk.StringVar(value="全部")
        combo = ttk.Combobox(
            toolbar, textvariable=self.trace_var,
            width=24, state="readonly", font=(THEME["font_family"], 9)
        )
        combo["values"] = ["全部"] + [f"{tid[:8]}..." for tid in trace_ids]
        combo.pack(side="left", padx=(0, 10))
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_trace_text(text_area))

        create_modern_button(
            toolbar, "🔄 刷新", bg="#334155", hover_bg=THEME["cyan"],
            command=lambda: self._refresh_trace_list(combo, text_area), font_size=8
        ).pack(side="left", padx=3)

        create_modern_button(
            toolbar, "📋 复制日志", bg="#334155", hover_bg=THEME["success"],
            command=lambda: self._copy_trace_to_clipboard(win), font_size=8
        ).pack(side="left", padx=3)

        create_modern_button(
            toolbar, "🗑 清空日志", bg="#334155", hover_bg=THEME["danger"],
            command=lambda: self._confirm_clear_trace(text_area), font_size=8
        ).pack(side="left", padx=3)

        self.lbl_trace_stats = tk.Label(
            toolbar, text=f"共 {len(trace_ids)} 条追踪记录",
            font=(THEME["font_family"], 8, "bold"), fg="#38bdf8", bg="#1e293b"
        )
        self.lbl_trace_stats.pack(side="right")

        # 终端代码文本区
        text_frame = tk.Frame(win, bg="#0f172a", padx=10, pady=10)
        text_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        text_area = tk.Text(
            text_frame, font=(THEME["font_code"], 9), bg="#090d16", fg="#38bdf8",
            insertbackground="white", yscrollcommand=scrollbar.set,
            wrap="none", state="disabled", bd=0, padx=12, pady=12
        )
        text_area.pack(fill="both", expand=True)
        scrollbar.config(command=text_area.yview)

        self._refresh_trace_text(text_area)
        text_area.bind("<Control-a>", lambda e: text_area.event_generate("<<SelectAll>>"))

    def _refresh_trace_list(self, combo, text_area):
        trace_ids = trace_logger.get_unique_trace_ids()
        combo["values"] = ["全部"] + [f"{tid[:8]}..." for tid in trace_ids]
        self.trace_var.set("全部")
        self.lbl_trace_stats.config(text=f"共 {len(trace_ids)} 条追踪记录")
        self._refresh_trace_text(text_area)

    def _refresh_trace_text(self, text_area):
        selected = self.trace_var.get()
        if selected == "全部":
            content = trace_logger.read_all_logs()
        else:
            short = selected.replace("...", "")
            all_ids = trace_logger.get_unique_trace_ids()
            target_id = next((tid for tid in all_ids if tid.startswith(short)), None)
            if target_id:
                events = trace_logger.get_trace_events(target_id)
                lines = [json.dumps(event, ensure_ascii=False) for event in events]
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
            target_id = next((tid for tid in all_ids if tid.startswith(short)), None)
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
    # 归档会话窗口 (现代卡片与表格设计)
    # ------------------------------------------------------------------
    def show_archived_sessions(self):
        """打开已归档会话列表窗口。"""
        win = tk.Toplevel(self.root)
        win.title("已归档会话中心 (Archived Sessions)")
        win.geometry("780x520")
        win.configure(bg=THEME["bg_main"])

        # 工具栏
        toolbar = tk.Frame(win, bg=THEME["bg_header"], padx=14, pady=10)
        toolbar.pack(fill="x")

        tk.Label(
            toolbar, text="📁 历史会话归档库", font=(THEME["font_family"], 11, "bold"),
            fg="#f8fafc", bg=THEME["bg_header"]
        ).pack(side="left")

        create_modern_button(
            toolbar, "🗑 删除选中", bg="#334155", hover_bg=THEME["danger"],
            command=lambda: self._delete_archive(tree), font_size=8
        ).pack(side="right", padx=3)

        create_modern_button(
            toolbar, "📂 打开目录", bg="#334155", hover_bg=THEME["primary"],
            command=lambda: self._open_archive_log(tree), font_size=8
        ).pack(side="right", padx=3)

        create_modern_button(
            toolbar, "🔄 刷新", bg="#334155", hover_bg=THEME["teal"],
            command=lambda: self._refresh_archive_list(tree), font_size=8
        ).pack(side="right", padx=3)

        # 表格容器
        tree_frame = tk.Frame(win, bg=THEME["bg_main"], padx=14, pady=12)
        tree_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        columns = ("id", "file", "lines")
        tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            yscrollcommand=scrollbar.set, selectmode="extended"
        )
        tree.pack(fill="both", expand=True)
        scrollbar.config(command=tree.yview)

        tree.heading("id", text="会话标识 (Session ID)")
        tree.heading("file", text="归档物理文件")
        tree.heading("lines", text="追踪条数")
        tree.column("id", width=160, anchor="w")
        tree.column("file", width=420, anchor="w")
        tree.column("lines", width=100, anchor="center")

        self._refresh_archive_list(tree)

    def _refresh_archive_list(self, tree):
        for item in tree.get_children():
            tree.delete(item)

        sessions = session_manager.list_archived_sessions()
        for s in sessions:
            tree.insert("", "end", values=(s["id"], s["file"], s["lines"]))

    def _open_archive_log(self, tree):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个会话。")
            return
        item = tree.item(selection[0])
        file_path = item["values"][1]
        if messagebox.askyesno("确认", f"是否在资源管理器中定位文件：\n{file_path}"):
            subprocess.Popen(['explorer', '/select,', file_path])

    def _delete_archive(self, tree):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个会话。")
            return
        item = tree.item(selection[0])
        file_path = item["values"][1]
        if messagebox.askyesno("确认", f"确定删除归档会话：\n{file_path}？"):
            try:
                os.remove(file_path)
                self._refresh_archive_list(tree)
                messagebox.showinfo("提示", "会话归档已成功删除。")
            except Exception as e:
                messagebox.showerror("错误", f"删除失败：{e}")

    # ------------------------------------------------------------------
    # 对话会话管理
    # ------------------------------------------------------------------
    def new_conversation(self):
        """开始新对话：归档旧会话 → 创建新 session → 清空 UI。"""
        if self.full_history:
            if not messagebox.askyesno("确认", "当前会话数据将自动保存并归档，是否创建全新对话？"):
                return
        else:
            if not messagebox.askyesno("确认", "确定创建全新对话？当前记录将被重置。"):
                return

        session_manager.archive_current_session()
        session_manager.create_session()

        self.full_history = []
        self.large_ctx = [{"role": "system", "content": self._build_system_prompt()}]
        self.msg_counter = 0
        todo_manager.clear()
        self._update_todo_display()

        for widget in self.chat_scroll_frame.winfo_children():
            widget.destroy()

        self._update_session_label()
        self._append_tool_result("system", f"🚀 新会话已就绪 (Session ID: {session_manager.current_session_id[:8]})")
        self.append_message("ai", self._get_welcome_message())

    def clear_chat(self):
        """清空当前屏幕显示。"""
        if messagebox.askyesno("确认", "确定清空当前屏幕中的所有对话气泡？"):
            self.full_history.clear()
            self.large_ctx = [{"role": "system", "content": self._build_system_prompt()}]
            for widget in self.chat_scroll_frame.winfo_children():
                widget.destroy()
            self.append_message("ai", "对话历史已清空，您可以重新发送指令。")

    def _update_session_label(self):
        """更新状态栏中的会话与模型指标。"""
        info = session_manager.get_session_info()
        session_text = f"Session: {info['id'][:8] if info['id'] else 'None'}"
        self.status_left_var.set(
            f"{session_text} | 大模型: {config.LARGE_MODEL_NAME} | 小模型: {config.SMALL_MODEL_NAME}"
        )

    # ------------------------------------------------------------------
    # 摘要机制
    # ------------------------------------------------------------------
    def manual_summarize(self):
        if self.is_summarizing:
            messagebox.showinfo("提示", "正在执行后台压缩摘要，请稍候...")
            return
        if len(self.large_ctx) < 4:
            messagebox.showinfo("提示", "对话轮次较少，无需手动压缩。")
            return
        self.append_message("system", "⚡ [手动摘要触发] 正在唤醒后台小模型压缩长上下文...")
        threading.Thread(target=self._summarize_context, daemon=True).start()

    def _summarize_context(self, parent_trace_id: str = None):
        """后台调用小模型进行上下文滑动压缩。"""
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
                    f"✅ [摘要完成] 上下文已成功压缩！当前负载: {self.get_ctx_usage_pct()*100:.0f}%"))

            except Exception as e:
                if parent_trace_id:
                    trace_logger.log_step(parent_trace_id, "error", {
                        "type": "SummarizeError",
                        "message": str(e),
                    })
                self.root.after(0, lambda: self.append_message(
                    "system", f"⚠️ [摘要失败] {type(e).__name__}: {e}", is_error=True))
            finally:
                self.is_summarizing = False

        threading.Thread(target=summarize_thread, daemon=True).start()


# ============================================================================
# 入口
# ============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = ChatApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: root.destroy())
    root.mainloop()
