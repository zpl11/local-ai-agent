# AGENTS.md — AI 聊天客户端工作空间规范

本项目是一个本地 AI 聊天客户端桌面应用，使用 tkinter GUI + Python，连接本地部署的大/小模型。

---

## 项目概述

**核心能力**：
- 大小模型混用：大模型深度推理 + 小模型后台摘要
- 工业级工具调用（Function Call）：文件读取/写入、目录浏览、命令执行
- Plan-and-Act 任务清单：复杂任务自动拆分步骤，逐步推进
- 执行时间线追踪：JSONL 格式记录每一步动作
- 会话管理：多轮对话独立归档

**模型配置**：
- 大模型：`qwen3-next-80b-a3b`（16384 token 上下文）
- 小模型：`qwen3.8-27b`（摘要/清洗）

---

## 文件结构

```
本地Ai工程化构建/
├── AGENTS.md              # ← 本文件：Agent 工作空间规范
├── config.py              # 配置层（模型地址、超时、阈值等）
├── ai_logger.py           # 日志层（执行时间线追踪）
├── session_manager.py     # 会话管理器（Session Management）
├── tools.py               # 工具层（注册中心 + 工具函数）
├── agent.py               # Agent 引擎层（Turn Loop + TODO 注入 + Guardrail）
├── compress.py            # 压缩/摘要层（上下文压缩）
├── todo_manager.py        # 任务清单管理器（Plan-and-Act）
├── gui.py                 # GUI 层（tkinter 界面）
├── ai_chat_client.py      # 向后兼容入口
├── sessions/              # 已归档的会话 trace 日志
├── dist/                  # 打包产物
└── agent_execution_trace.jsonl  # 执行时间线日志（运行时生成）
```

---

## Agent 工作流程

### 1. 系统提示（System Prompt）

系统提示定义在 `gui.py::ChatApp._build_system_prompt()` 中，包含：

1. **强制第一步**：必须先调用 `init_todo_list` 规划任务
2. **Plan-and-Act 工作流**：规划 → 执行 → 状态更新 → 闭环
3. **文件读取规则**：分页读取、指针导航、禁止乱跳
4. **文件写入规则**：分析结果写入文件而非聊天窗口

### 2. Agent Turn Loop

```
while tool_call_count < MAX_TOOL_CALLS (20):
    1. 动态注入 TODO 状态到系统提示 (_inject_todos)
    2. 发送消息 + tools_spec 给大模型
    3. 检测 tool_calls
       - 有 → Guardrail 检查 → 执行工具 → 回填结果 → 继续
       - 无 → 返回最终答案
    4. 异常兜底：ConnectionError / Timeout / 其他
    5. 超过最大次数 → 终止循环
```

### 3. Guardrail 渐进式拦截

| 拦截次数 | 行为 | 提示内容 |
|---------|------|---------|
| 第 1 次 | 提醒 | "请先调用 init_todo_list 规划任务" |
| 第 2 次 | 警告 | "你已被提醒过一次，请立即调用 init_todo_list" |
| 第 3 次 | 硬拦截 | "架构规范错误，工作被阻断" |
| 第 4 次 | 自动兜底 | 系统自动创建默认任务清单 + 注入干预指令 |

---

## 工具开发规范

### 添加新工具

1. 在 `tools.py` 中定义函数
2. 使用 `@registry.register` 装饰器
3. 通过类型注解声明参数类型（自动生成 JSON Schema）
4. 通过 docstring 的 `@param` 行声明参数描述
5. 函数返回 `str` 类型（工具结果将回填给模型）

### 受限工具集合

以下工具受 Guardrail 保护，必须先初始化 TODO List 才能调用：

```python
restricted_tools = {"read_file", "write_file", "write_markdown_file", "append_to_file", "execute_command"}
```

`list_dir` 和 `get_file_info` 不在受限工具中，模型可先调用它们探索环境。

---

## 日志规范

### JSONL 格式

每行一个 JSON 对象，包含：

```json
{
  "timestamp": "2025-01-01T12:00:00",
  "trace_id": "uuid",
  "type": "tool_call",
  "details": {"tool": "read_file", "arguments_preview": "..."}
}
```

### step_type 类型

`user_input` | `llm_request` | `llm_response` | `tool_call` | `tool_result` | `summary` | `error` | `run_end`

### 查询方法

- `trace_logger.get_unique_trace_ids()` — 获取所有唯一 trace_id
- `trace_logger.get_trace_events(trace_id)` — 获取指定 trace 的所有事件

---

## 会话管理

### 生命周期

1. 应用启动 → 自动创建第一个会话
2. 用户点击 `➕ 新对话` → 归档旧 trace → 生成新 session_id → 重置上下文
3. 归档文件命名：`sessions/trace_{session_id前8位}.jsonl`

### 关键方法

- `session_manager.create_session(name)` — 创建新会话
- `session_manager.archive_current_session()` — 归档当前 trace
- `session_manager.list_archived_sessions()` — 列出所有归档会话

---

## 关键设计决策

1. **分页读取文件**：`read_file` 强制线性翻页，每次最多 200 行
2. **文件写入工具**：分析结果写入文件而非聊天窗口，避免上下文溢出
3. **大小模型混用**：大模型深度推理 + 小模型后台摘要（阈值 75%）
4. **异常隔离**：工具报错不崩溃，回填给模型继续处理
5. **链路追踪**：每一步动作记录 JSONL，支持事后分析
6. **Plan-and-Act 任务清单**：`init_todo_list` + `update_todo_status` 实现"先出清单 → 逐步勾选 → 状态闭环"
7. **渐进式 Guardrail**：提醒 → 警告 → 拦截 → 自动兜底，四级递进

---

## 配置说明

所有配置支持通过根目录下的 `.env` 文件进行个性化配置（参考 `.env.example`）：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `LARGE_MODEL_URL` | `http://127.0.0.1:8000` | 大模型 API 地址（支持 .env 覆盖） |
| `LARGE_MODEL_NAME` | `qwen3-next-80b-a3b` | 大模型名称 |
| `LARGE_CTX_MAX` | `16384` | 大模型上下文上限 |
| `SMALL_MODEL_URL` | `http://127.0.0.1:8080` | 小模型 API 地址（支持 .env 覆盖） |
| `SMALL_MODEL_NAME` | `qwen3.8-27b` | 小模型名称 |
| `SUMMARIZE_THRESHOLD` | `0.75` | 上下文使用率超过此值触发自动摘要 |
| `TIMEOUT` | `360` | 大模型请求超时（秒） |
| `SUMMARIZE_TIMEOUT` | `60` | 小模型请求超时（秒） |
| `MAX_TOOL_CALLS` | `50` | 单轮对话最大工具调用次数 |

---

## 打包

```bash
python -m PyInstaller --clean "AI聊天客户端_混用版.spec"
```

打包产物位于 `dist/AI聊天客户端_混用版.exe`。
