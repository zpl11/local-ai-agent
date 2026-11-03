# AI 聊天客户端

大小模型混用版 + 工业级工具调用 + Plan-and-Act 任务追踪。

**核心能力**：
- **大模型**：深度推理与代码分析（支持通过 `.env` 配置本地或远程 OpenAI 兼容服务）
- **小模型**：后台静默摘要与清洗（当上下文使用率超过 75% 时触发自动摘要，释放上下文空间）
- **工业级工具链**：文件读写、AST 语法分析、目录搜索、命令执行
- **Plan-and-Act 任务清单**：任务步骤自动化拆解与渐进式闭环

---

## 模块说明

### `todo_manager.py` — 任务清单管理器 (Plan-and-Act)

轻量级内存任务管理器，维护结构化任务清单，支持增删改查。
实现"先出清单 → 逐步勾选 → 状态闭环"的工业化流程。

**`TodoManager` 类**：

| 方法 | 说明 |
|------|------|
| `set_todos(tasks: list[str]) -> str` | 初始化或重置任务清单 |
| `update_todo(task_id: int, status: str) -> str` | 更新任务状态（pending / in_progress / done） |
| `get_status_str() -> str` | 生成格式化清单字符串，注入 Prompt |
| `get_all() -> list[dict]` | 返回完整副本（供 UI 展示） |
| `clear()` | 清空任务清单 |
| `is_empty() -> bool` | 检查是否为空 |

**全局单例**：`todo_manager` — 所有模块直接引用

**与 Agent 引擎的协作**：
1. `agent.py` 在每次 LLM 调用前通过 `_inject_todos()` 将 TODO 状态动态注入系统提示
2. `gui.py` 在 UI 顶部展示实时任务清单（含进度统计）
3. `init_todo_list` 和 `update_todo_status` 两个工具暴露给大模型，由模型自主管理进度

---

### `session_manager.py` — 会话管理器 (Session Management)

管理对话会话的生命周期，支持多轮对话的独立归档。

**`SessionManager` 类**：

| 方法 | 说明 |
|------|------|
| `create_session(name: str) -> str` | 创建新会话，返回 session_id (UUID) |
| `archive_current_session(log_file)` | 将当前会话的 trace 日志归档到 `sessions/` 目录 |
| `get_session_info() -> dict` | 返回当前会话的元信息（id, name, created_at） |
| `list_archived_sessions() -> list[dict]` | 列出所有已归档的会话 |
| `clear_current_session()` | 清除当前会话状态 |

**会话流程**：
1. 应用启动时自动创建第一个会话
2. 用户点击 `➕ 新对话` 时：归档旧 trace → 生成新 session_id → 重置上下文
3. 每次新对话的 trace 日志归档到 `sessions/trace_{session_id前8位}.jsonl`
4. 主日志文件 `agent_execution_trace.jsonl` 保留所有 trace（按时间追加）

---

### `config.py` — 配置层

支持读取根目录下 `.env` 环境变量，未配置时自动采用安全默认值：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `LARGE_MODEL_URL` | `http://127.0.0.1:8000` | 大模型 API 地址（支持 .env 覆盖） |
| `LARGE_MODEL_NAME` | `qwen3-next-80b-a3b` | 大模型名称 |
| `LARGE_CTX_MAX` | `16384` | 大模型上下文上限 (token) |
| `SMALL_MODEL_URL` | `http://127.0.0.1:8080` | 小模型 API 地址（支持 .env 覆盖） |
| `SMALL_MODEL_NAME` | `qwen3.8-27b` | 小模型名称 |
| `SUMMARIZE_THRESHOLD` | `0.75` | 上下文使用率超过此值触发自动摘要 |
| `TIMEOUT` | `360` | 大模型请求超时（秒） |
| `SUMMARIZE_TIMEOUT` | `60` | 小模型摘要超时（秒） |
| `MAX_TOOL_CALLS` | `50` | 单轮对话最大工具调用次数，防死循环 |
| `MAX_LINES_PER_PAGE` | `200` | 文件读取每页最大行数（硬限制） |

修改配置只需在根目录创建或编辑 `.env` 文件（可参考 `.env.example`）。

---

### `ai_logger.py` — 日志层（AI Observability / Execution Trace）

工业级执行时间线追踪器，记录 Agent 每一步动作的结构化日志。

- **`ExecutionLogger` 类**：线程安全的日志记录器
  - `log_step(trace_id, step_type, details)` — 记录一步动作
  - `read_all_logs()` — 读取全部日志内容
  - `clear_logs()` — 清空日志文件
- **`trace_logger`** — 全局日志器实例，所有模块直接引用

**落地格式**：JSONL 文件（`agent_execution_trace.jsonl`），每行一个合法 JSON 对象，方便后续分析/回放。

**step_type 类型**：`user_input`、`llm_request`、`llm_response`、`tool_call`、`tool_result`、`summary`、`error`、`run_end`

---

### `tools.py` — 工具层

包含工具注册中心和所有本地工具函数定义。

**核心类**：

| 类/函数 | 说明 |
|---------|------|
| `ParamValidator.validate(params, schema)` | 轻量级 JSON Schema 参数校验，不依赖 pydantic |
| `ToolRegistry` | 声明式工具注册中心，@tool 装饰器自动提取 JSON Schema |
| `ToolRegistry.register(func)` | 装饰器：注册工具函数 |
| `ToolRegistry.get_tools_spec()` | 返回 OpenAI 兼容的工具列表格式 |
| `ToolRegistry.execute(name, args)` | 参数校验 + 执行工具 + 异常隔离 |
| `ToolRegistry.list_tools()` | 返回已注册工具名列表 |
| `registry` | 全局工具注册实例 |

**已注册工具**：

| 工具名 | 说明 |
|--------|------|
| `read_file` | 分页读取文件（带指针导航，强制线性翻页，硬限制 200 行/页） |
| `get_file_info` | 获取文件基本信息（大小、行数、建议分页策略） |
| `search_code` | 在文件中搜索关键词，返回匹配行及上下文 |
| `list_dir` | 列出目录内容 |
| `search_files` | 递归搜索文件名匹配的文件 |
| `execute_command` | 执行本地 shell 命令（含安全白名单检查） |
| `get_env` | 读取环境变量（密码类自动脱敏） |
| `get_system_info` | 获取系统基本信息 |
| `write_file` | 工业级文件写入（路径安全检查 + 异常隔离） |
| `write_markdown_file` | 写入 Markdown 文件（调用 write_file） |
| `init_todo_list` | Plan-and-Act：创建全局任务清单 |
| `update_todo_status` | Plan-and-Act：更新任务状态 |

---

### `agent.py` — Agent 引擎层

工业级 Agent 引擎：标准 Schema 注入 + 多轮迭代闭环 + 异常防御兜底 + 链路追踪。

**`AgentEngine` 类**：

| 方法 | 说明 |
|------|------|
| `__init__(model_url, model_name, ctx_max, timeout, registry, logger)` | 构造函数，注入依赖 |
| `set_callback(event, fn)` | 注册回调：`on_tool_call`、`on_tool_result`、`on_error`、`on_final` |
| `run(messages, trace_id)` | **核心方法**：Agent Turn Loop，循环调用大模型直到不再请求工具调用 |
| `_single_call(messages, trace_id)` | 无工具时的普通聊天 |
| `_inject_todos(messages)` | Plan-and-Act：动态注入 TODO 状态到系统提示 |
| `_guardrail_check_todos(tool_calls, level)` | 渐进式四级 Guardrail：提醒→警告→硬拦截→自动兜底 |

**Agent Turn Loop 流程**：

```
while tool_call_count < MAX_TOOL_CALLS:
    1. 发送消息 + tools_spec 给大模型
    2. 记录 LLM 请求/响应（含 token 用量、耗时）
    3. 检测是否有 tool_calls
       - 有 → Guardrail 检查 → 执行工具 → 回填结果 → 继续
       - 无 → 返回最终答案
    4. 异常兜底：ConnectionError / Timeout / 其他异常
    5. 超过最大次数 → 终止循环，返回警告
```

**渐进式 Guardrail 机制**：

| 拦截次数 | 等级 | 行为 |
|---------|------|------|
| 第 1 次 | 软提醒 | "请先调用 init_todo_list 规划任务" |
| 第 2 次 | 警告 | "你已被提醒过一次，请立即调用 init_todo_list" |
| 第 3 次 | 硬拦截 | "架构规范错误，工作被阻断" |
| 第 4 次 | 自动兜底 | 系统自动创建默认任务清单 + 注入干预指令 |

---

### `gui.py` — GUI 层

tkinter 图形界面，线程安全 UI 更新。

**`ChatApp` 类**：

| 方法 | 说明 |
|------|------|
| `__init__(root)` | 初始化 UI，绑定 Agent 回调 |
| `on_send()` | 发送消息（回车或点击按钮） |
| `send_message(user_text)` | 发送消息，必要时先摘要 |
| `get_ctx_usage_pct()` | 估算当前上下文使用率 |
| `append_message(role, text, ...)` | 向聊天区域追加消息 |
| `update_message(msg_id, text, ...)` | 更新已有消息内容 |
| `show_trace_window()` | 打开执行时间线日志查看窗口（支持按 trace_id 过滤） |
| `show_archived_sessions()` | 打开已归档会话列表窗口 |
| `clear_chat()` | 清空对话 |
| `manual_summarize()` | 手动触发摘要 |
| `_on_tool_call(name, args_str)` | Agent 回调：模型请求调用工具 |
| `_on_tool_result(name, result)` | Agent 回调：工具执行结果 |
| `_on_tool_error(error_msg)` | Agent 回调：工具执行出错 |

**UI 布局**：
- 顶部栏：标题、工具数量、新对话/手动摘要/查看时间线/归档会话/清空对话按钮
- 状态栏：Session ID、大模型地址、小模型地址
- 聊天区域：Canvas + Scrollbar，支持鼠标滚轮
- 输入区域：文本框 + 发送按钮
- TODO 展示区：实时显示任务清单及进度

---

### `compress.py` — 压缩/摘要层

上下文压缩器。当上下文 token 使用率超过阈值时，用小模型对旧消息进行摘要压缩。

**`Compressor` 类**：

| 方法 | 说明 |
|------|------|
| `summarize(messages, trace_id)` | 对消息列表进行摘要压缩，返回 (新消息列表, 是否触发) |
| `get_context_usage(messages, ctx_max)` | 估算当前上下文使用率 |

**摘要策略**：
1. 过滤系统消息和已有摘要，保留用户消息和助手回复
2. 发送给小模型（qwen3.8-27b）进行压缩
3. 保留系统消息 + 历史摘要 + 最新一条用户消息 + 新摘要
4. 异常时原样返回原消息列表，不中断对话

---

### `gui.py` — GUI 层

tkinter 图形界面，线程安全 UI 更新。

**`ChatApp` 类**：

| 方法 | 说明 |
|------|------|
| `__init__(root)` | 初始化 UI，绑定 Agent 回调 |
| `on_send()` | 发送消息（回车或点击按钮） |
| `send_message(user_text)` | 发送消息，必要时先摘要 |
| `get_ctx_usage_pct()` | 估算当前上下文使用率 |
| `append_message(role, text, ...)` | 向聊天区域追加消息 |
| `update_message(msg_id, text, ...)` | 更新已有消息内容 |
| `show_trace_window()` | 打开执行时间线日志查看窗口 |
| `clear_chat()` | 清空对话 |
| `manual_summarize()` | 手动触发摘要 |
| `_on_tool_call(name, args_str)` | Agent 回调：模型请求调用工具 |
| `_on_tool_result(name, result)` | Agent 回调：工具执行结果 |
| `_on_tool_error(error_msg)` | Agent 回调：工具执行出错 |

**UI 布局**：
- 顶部栏：标题、工具数量、手动摘要/查看时间线/清空对话按钮
- 状态栏：就绪状态、上下文使用率、大模型地址
- 聊天区域：Canvas + Scrollbar，支持鼠标滚轮
- 输入区域：文本框 + 发送按钮

---

### `ai_chat_client.py` — 向后兼容入口

从各模块重新导出所有公共接口，保持原有 import 路径不变。旧代码无需修改。

---

## 文件结构

```
本地Ai工程化构建/
├── AGENTS.md              # Agent 工作空间规范（定义工作流程和工具开发规范）
├── config.py              # 配置层
├── ai_logger.py           # 日志层（执行时间线追踪）
├── session_manager.py     # 会话管理器（Session Management）
├── tools.py               # 工具层（注册中心 + 工具函数）
├── agent.py               # Agent 引擎层（Turn Loop + TODO 注入 + Guardrail）
├── compress.py            # 压缩/摘要层
├── todo_manager.py        # 任务清单管理器（Plan-and-Act）
├── gui.py                 # GUI 层（tkinter 界面）
├── ai_chat_client.py      # 向后兼容入口
├── sessions/              # 已归档的会话 trace 日志
├── dist/
│   └── AI聊天客户端_混用版.exe  # 打包后的可执行文件
└── agent_execution_trace.jsonl  # 执行时间线日志（运行时生成）
```

## 快速开始

```bash
# 直接运行（开发调试）
python gui.py

# 或通过兼容入口
python ai_chat_client.py

# 重新打包 EXE
python -m PyInstaller --clean "AI聊天客户端_混用版.spec"
```

## 关键设计决策

1. **分页读取文件**：`read_file` 强制线性翻页，每次最多 200 行，防止 400 Bad Request
2. **文件写入工具**：分析结果写入文件而非聊天窗口，避免上下文溢出
3. **大小模型混用**：大模型深度推理 + 小模型后台摘要
4. **异常隔离**：工具报错不崩溃，回填给模型继续处理
5. **链路追踪**：每一步动作记录 JSONL，支持事后分析
6. **Plan-and-Act 任务清单**：复杂任务自动拆分步骤，AI 每步执行前审视 TODO List，实现"先出清单 → 逐步勾选 → 状态闭环"
7. **渐进式 Guardrail**：提醒 → 警告 → 硬拦截 → 自动兜底，四级递进防止模型绕过规范
8. **会话管理**：每次新对话生成 UUID session_id，trace 日志自动归档到 `sessions/` 目录
9. **时间线过滤**：支持按 trace_id 查看单条 trace 事件，方便问题排查
