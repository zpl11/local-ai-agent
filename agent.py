"""
AI 聊天客户端 - Agent 引擎层

包含：
- AgentEngine: 工业级 Agent 引擎
  - 模块 2: 标准 Schema 注入 (OpenAI-Compatible Tools)
  - 模块 4: 多轮次迭代闭环 (Agent Turn Loop)
  - 模块 5: 异常防御兜底
  - 链路追踪: 通过 ExecutionLogger 记录每一步 Span
"""

import uuid
import json
import threading
import requests
from datetime import datetime
from typing import Optional, Callable, Tuple

import config
from ai_logger import ExecutionLogger
from tools import ToolRegistry
from todo_manager import todo_manager


class AgentEngine:
    """
    工业级 Agent 引擎：
      - 模块 2: 标准 Schema 注入 (OpenAI-Compatible Tools)
      - 模块 4: 多轮次迭代闭环 (Agent Turn Loop)
      - 模块 5: 异常防御兜底
      - 链路追踪: 通过 ExecutionLogger 记录每一步 Span
    """

    def __init__(self, model_url: str, model_name: str, ctx_max: int,
                 timeout: int, registry: ToolRegistry,
                 logger: ExecutionLogger = None):
        self.model_url = model_url
        self.model_name = model_name
        self.ctx_max = ctx_max
        self.timeout = timeout
        self.registry = registry
        self.logger = logger
        self._callbacks = {
            "on_tool_call": None,       # (name, args) -> None
            "on_tool_result": None,     # (name, result) -> None
            "on_error": None,           # (error_msg) -> None
            "on_final": None,           # (content) -> None
        }

    def set_callback(self, event: str, fn):
        self._callbacks[event] = fn

    def run(self, messages: list, trace_id: str = None) -> Optional[str]:
        """
        模块 4: Agent Turn Loop 核心。
        循环调用大模型，直到模型不再请求工具调用，返回最终文本。
        每步动作通过 trace_logger 记录。
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        tools_spec = self.registry.get_tools_spec()
        if not tools_spec:
            return self._single_call(messages, trace_id)

        # 记录用户输入
        user_msgs = [m for m in messages if m["role"] == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else ""
        self.logger.log_step(trace_id, "user_input", {
            "message_preview": last_user[:200],
            "total_messages": len(messages),
        })

        current_msgs = list(messages)
        tool_call_count = 0
        consecutive_blocks = 0  # 连续被拦截次数
        max_blocks = 4  # 连续拦截 4 次后自动初始化 TODO List（四级递进）
        tool_error_counts = {}  # 跟踪每个工具的连续报错次数，触发自省机制

        while tool_call_count < config.MAX_TOOL_CALLS:
            try:
                # Plan-and-Act: 动态注入 TODO 状态到系统提示
                self._inject_todos(current_msgs)

                # 上下文瞬态修剪：折叠较早的历史代码输出，保护 16k 上下文
                prepared_msgs = self._prune_context_for_llm(current_msgs)

                # 动态自适应计算 safe_max_tokens，严格防止 prompt + max_tokens > ctx_max 导致的 400 错误
                approx_tokens = sum(len(str(m.get("content", ""))) for m in prepared_msgs) // 2 + len(tools_spec) * 80
                safe_max_tokens = min(4096, max(256, self.ctx_max - approx_tokens - 300))

                # 记录 LLM 请求
                self.logger.log_step(trace_id, "llm_request", {
                    "step": tool_call_count + 1,
                    "total_messages": len(prepared_msgs),
                    "tools_count": len(tools_spec),
                    "max_tokens": safe_max_tokens,
                })

                payload = {
                    "model": self.model_name,
                    "messages": prepared_msgs,
                    "temperature": 0.7,
                    "max_tokens": safe_max_tokens,
                    "tools": tools_spec,
                    "tool_choice": "auto",
                }
                start_time = datetime.now()
                resp = requests.post(
                    f"{self.model_url}/v1/chat/completions",
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

                data = resp.json()

                # 记录 LLM 响应
                usage = data.get("usage", {})
                self.logger.log_step(trace_id, "llm_response", {
                    "step": tool_call_count + 1,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "tokens": {
                        "prompt": usage.get("prompt_tokens", 0),
                        "completion": usage.get("completion_tokens", 0),
                        "total": usage.get("total_tokens", 0),
                    },
                })

                choice = data["choices"][0]["message"]
                current_msgs.append(choice)

                # 检测工具调用
                tool_calls = choice.get("tool_calls")
                if tool_calls:
                    # 🛡️ 前置拦截器：渐进式四级递进
                    blocked, block_msg, block_level = self._guardrail_check_todos(tool_calls, consecutive_blocks)
                    if blocked:
                        tool_call_count += 1
                        consecutive_blocks += 1

                        # 记录拦截日志（含等级）
                        self.logger.log_step(trace_id, "error", {
                            "type": "GuardrailBlocked",
                            "level": block_level,
                            "message": block_msg[:200],
                            "consecutive_blocks": consecutive_blocks,
                        })

                        # 回调：通知 UI
                        if self._callbacks["on_error"]:
                            self._callbacks["on_error"](block_msg)

                        # 第 4 次拦截 → 自动初始化 TODO List（强制兜底）
                        if consecutive_blocks >= max_blocks:
                            self.logger.log_step(trace_id, "system", {
                                "type": "AutoInitTodo",
                                "message": f"连续拦截 {max_blocks} 次，自动初始化任务清单",
                            })
                            # 自动创建默认任务清单
                            default_tasks = [
                                "列出项目文件结构",
                                "分析核心文件内容",
                                "总结代码架构和功能",
                                "生成文档并写入文件",
                            ]
                            todo_manager.set_todos(default_tasks)
                            # 注入系统指令：告知模型已自动创建 TODO
                            current_msgs.append({
                                "role": "system",
                                "content": (
                                    "【系统自动干预】由于你连续 4 次尝试调用受限工具（read_file 等）"
                                    "而未先初始化任务清单，系统已自动为你创建了默认任务清单。\n"
                                    "请立即查看下方的 TODO List，按顺序执行任务。\n"
                                    "如果你需要自定义任务，请调用 init_todo_list 重新规划。"
                                ),
                            })
                            # 重置拦截计数，继续正常流程
                            consecutive_blocks = 0
                            continue

                        # 将纠偏消息回填给模型，逼迫其下一轮补交 TODO List
                        # 🛡️ 遍历所有 tool_calls，为每一个被拦截的 ID 都补上一条 tool 响应消息，
                        # 防止因"孤儿 tool_call_id"导致大模型后端返回 400 Bad Request
                        for tc in tool_calls:
                            current_msgs.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": block_msg,
                            })
                        continue

                    # 未被拦截 → 重置连续拦截计数
                    consecutive_blocks = 0

                    tool_call_count += 1
                    for tc in tool_calls:
                        func_name = tc["function"]["name"]
                        func_args_str = tc["function"]["arguments"]

                        # 记录工具调用
                        self.logger.log_step(trace_id, "tool_call", {
                            "tool": func_name,
                            "arguments_preview": func_args_str[:200],
                        })

                        # 回调：通知 UI 显示工具调用
                        if self._callbacks["on_tool_call"]:
                            self._callbacks["on_tool_call"](func_name, func_args_str)

                        # 解析参数（使用 strict=False 容忍控制字符，并做容错提取）
                        func_args = None
                        try:
                            func_args = json.loads(func_args_str, strict=False)
                        except Exception:
                            # 容错修复：尝试提取最外层大括号中的 JSON
                            raw = func_args_str.strip()
                            first_b = raw.find('{')
                            last_b = raw.rfind('}')
                            if first_b != -1 and last_b != -1 and last_b > first_b:
                                try:
                                    func_args = json.loads(raw[first_b:last_b+1], strict=False)
                                except Exception:
                                    pass

                        if func_args is None or not isinstance(func_args, dict):
                            err_msg = (
                                f"Error: 工具 '{func_name}' 的参数不是合法的 JSON 格式: {func_args_str[:200]}... "
                                f"请重新以合法 JSON 格式传参。"
                            )
                            if self._callbacks["on_error"]:
                                self._callbacks["on_error"](f"参数解析失败: {func_name}")
                            result = err_msg
                            tool_elapsed = 0.0
                        else:
                            # 执行工具 (模块 3 + 5)
                            tool_start = datetime.now()
                            result = self.registry.execute(func_name, func_args)
                            tool_elapsed = (datetime.now() - tool_start).total_seconds() * 1000

                        # 自省机制：跟踪工具报错并在连续失败时强行注入反思指令
                        if result.startswith("Error:"):
                            tool_error_counts[func_name] = tool_error_counts.get(func_name, 0) + 1
                            fail_count = tool_error_counts[func_name]
                            if fail_count >= 2:
                                reflection_directive = (
                                    f"\n\n【🚨 系统反省指令 (Self-Reflection Trigger)】\n"
                                    f"注意：你对工具 '{func_name}' 的调用已连续失败 {fail_count} 次！\n"
                                    f"严禁盲目机械地重复上一轮的相同调用或随意试错。\n"
                                    f"在下一步行动前，你必须：\n"
                                    f"1. 仔细阅读上方报错给出的具体原因、参数契约与当前系统状态；\n"
                                    f"2. 反思为什么之前的参数会出错；\n"
                                    f"3. 调整思路，使用合规参数重新调用，或切换合适的工具推进任务。"
                                )
                                result += reflection_directive
                                self.logger.log_step(trace_id, "system", {
                                    "type": "SelfReflectionTriggered",
                                    "tool": func_name,
                                    "consecutive_failures": fail_count,
                                })
                        else:
                            tool_error_counts[func_name] = 0

                        # 记录工具结果
                        self.logger.log_step(trace_id, "tool_result", {
                            "tool": func_name,
                            "elapsed_ms": round(tool_elapsed, 1),
                            "result_preview": result[:300],
                        })

                        # 回调：通知 UI 显示工具结果
                        if self._callbacks["on_tool_result"]:
                            self._callbacks["on_tool_result"](func_name, result)

                        # 回填工具结果 (模块 4)
                        current_msgs.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })

                    continue  # 继续下一轮

                # 无工具调用，模型给出最终答案
                content = choice.get("content", "")
                if content and self._callbacks["on_final"]:
                    self._callbacks["on_final"](content)

                # 记录最终结果
                total_tokens = usage.get("total_tokens", 0)
                pct = total_tokens / self.ctx_max * 100
                self.logger.log_step(trace_id, "run_end", {
                    "total_tool_calls": tool_call_count,
                    "final_tokens": total_tokens,
                    "ctx_pct": round(pct, 1),
                    "content_preview": content[:200] if content else "",
                })

                return content

            except requests.exceptions.ConnectionError:
                self.logger.log_step(trace_id, "error", {
                    "type": "ConnectionError",
                    "message": "大模型服务无法连接",
                })
                if self._callbacks["on_error"]:
                    self._callbacks["on_error"]("[错误] 大模型服务无法连接")
                return None
            except requests.exceptions.Timeout:
                self.logger.log_step(trace_id, "error", {
                    "type": "Timeout",
                    "message": f"大模型请求超时（已等待 {self.timeout} 秒）",
                })
                if self._callbacks["on_error"]:
                    self._callbacks["on_error"](f"[错误] 大模型请求超时（已等待 {self.timeout} 秒）")
                return None
            except Exception as e:
                self.logger.log_step(trace_id, "error", {
                    "type": type(e).__name__,
                    "message": str(e),
                })
                if self._callbacks["on_error"]:
                    self._callbacks["on_error"](f"[错误] {type(e).__name__}: {e}")
                return None

        # 超过最大工具调用次数
        self.logger.log_step(trace_id, "error", {
            "type": "MaxToolCallsExceeded",
            "message": f"工具调用超过最大次数 ({config.MAX_TOOL_CALLS})，已终止循环。",
        })
        if self._callbacks["on_error"]:
            self._callbacks["on_error"](
                f"[警告] 工具调用超过最大次数 ({config.MAX_TOOL_CALLS})，已终止循环。"
            )
        return None

    def _single_call(self, messages: list, trace_id: str = None) -> Optional[str]:
        """没有注册工具时的普通聊天。"""
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        try:
            self.logger.log_step(trace_id, "llm_request", {
                "step": 1,
                "total_messages": len(messages),
                "tools_count": 0,
            })

            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2048,
            }
            start_time = datetime.now()
            resp = requests.post(
                f"{self.model_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

            data = resp.json()
            usage = data.get("usage", {})
            self.logger.log_step(trace_id, "llm_response", {
                "elapsed_ms": round(elapsed_ms, 1),
                "tokens": {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                },
            })

            content = data["choices"][0]["message"]["content"]
            if self._callbacks["on_final"]:
                self._callbacks["on_final"](content)

            self.logger.log_step(trace_id, "run_end", {
                "total_tool_calls": 0,
                "final_tokens": usage.get("total_tokens", 0),
                "content_preview": content[:200] if content else "",
            })

            return content
        except Exception as e:
            self.logger.log_step(trace_id, "error", {
                "type": type(e).__name__,
                "message": str(e),
            })
            if self._callbacks["on_error"]:
                self._callbacks["on_error"](f"[错误] {type(e).__name__}: {e}")
            return None

    def _inject_todos(self, messages: list) -> None:
        """将当前 TODO 状态动态注入到系统提示中。

        每次 LLM 调用前执行，确保模型始终看到最新的任务清单。
        如果系统消息已包含 TODO 分隔符，则替换；否则追加。
        """
        todo_str = todo_manager.get_status_str()
        if not todo_str:
            return

        todo_marker = "--- 📌 实时任务清单 (TODO List) ---"

        for msg in messages:
            if msg.get("role") == "system":
                current = msg.get("content", "")
                if todo_marker in current:
                    # 替换旧的 TODO 列表
                    idx = current.index(todo_marker)
                    msg["content"] = current[:idx] + todo_str
                else:
                    # 追加到系统提示末尾
                    msg["content"] = current.rstrip() + "\n" + todo_str
                break

    def _prune_context_for_llm(self, messages: list) -> list:
        """为保护 16k 上下文不被撑爆，对发往大模型的消息进行瞬态修剪（Ephemeral Pruning）。

        规则：
        1. 保持消息角色和结构完整（系统消息、用户消息、assistant 及其 tool_calls 完整保留）；
        2. 保留每一个 tool 响应的 tool_call_id，严格满足 OpenAI Function Calling 协议；
        3. 仅保留最近 2 个回合（最后 4 个 tool 消息）的完整输出；
        4. 对更早历史中内容较长（>300 字符）的 tool 输出（如旧的 read_file 或 get_code_outline），
           将其折叠为紧凑的摘要说明，彻底消除旧代码占用的上下文空间。
        """
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        # 最近 4 个 tool 消息保留完整输出
        recent_tool_set = set(tool_indices[-4:]) if tool_indices else set()

        pruned = []
        for idx, m in enumerate(messages):
            if m.get("role") == "tool" and idx not in recent_tool_set:
                content = str(m.get("content", ""))
                if len(content) > 300:
                    head_hint = content[:80].replace("\n", " ").strip()
                    pruned_content = (
                        f"[历史代码输出已折叠] {head_hint}... "
                        f"(该片段已在前面步骤中分析吸收，内容已折叠以保护 16k 上下文)"
                    )
                    pruned.append({
                        "role": "tool",
                        "tool_call_id": m.get("tool_call_id"),
                        "content": pruned_content,
                    })
                    continue
            pruned.append(m)

        return pruned

    # ------------------------------------------------------------------
    # 前置拦截器（Pre-execution Guardrail）— 渐进式四级递进
    # ------------------------------------------------------------------
    def _guardrail_check_todos(self, tool_calls: list, current_level: int = 0) -> tuple[bool, str, int]:
        """
        前置拦截器：渐进式四级递进机制。
        第 1 次：软提醒 → 第 2 次：警告 → 第 3 次：硬拦截 → 第 4 次：自动兜底（由调用方处理）

        @param tool_calls: 大模型返回的 tool_calls 列表。
        @param current_level: 当前已连续拦截次数（由调用方传入，用于生成对应等级消息）。
        @return: (blocked, error_message, level) — blocked=True 表示拦截，level 为当前等级（1-3）。
        """
        # 1. 定义需要受到 TODO List 强管控的"高权限工具"
        restricted_tools = {"read_file", "write_file", "write_markdown_file", "append_to_file", "execute_command"}

        # 2. 检查大模型当前调用的工具中是否包含受控工具
        is_trying_to_work = any(
            tc.get("function", {}).get("name") in restricted_tools
            for tc in tool_calls
        )

        # 3. 检查当前内存中的 TODO 状态是否为空
        has_todos = not todo_manager.is_empty()

        # 4. 未初始化 TODO List 就想调用受限工具 → 拦截
        if is_trying_to_work and not has_todos:
            blocked_tool_names = [
                tc.get("function", {}).get("name")
                for tc in tool_calls
                if tc.get("function", {}).get("name") in restricted_tools
            ]

            # 四级递进消息
            if current_level == 0:
                # 第 1 次：软提醒
                return True, (
                    f"\u26a0\ufe0f 【提醒：请先规划任务清单】\n"
                    f"你正在尝试调用受限工具（{', '.join(blocked_tool_names)}），\n"
                    f"但尚未初始化全局任务清单（TODO List）。\n\n"
                    f"\U0001f4cc **请调用 `init_todo_list` 规划步骤：**\n"
                    f"init_todo_list(tasks=[\"扫描目录\", \"读取核心文件\", \"分析代码\", \"写入报告\"])\n\n"
                    f"初始化完成后，下一轮再执行具体工具调用。"
                ), 1

            elif current_level == 1:
                # 第 2 次：警告
                return True, (
                    f"\U0001f6a8 【警告：你已被提醒过一次】\n"
                    f"你再次尝试调用受限工具（{', '.join(blocked_tool_names)}）"
                    "而未初始化任务清单。\n\n"
                    f"\U0001f4cc **你必须立即调用 `init_todo_list`：**\n"
                    f"init_todo_list(tasks=[\"第一步\", \"第二步\", \"第三步\"])\n\n"
                    f"\u26a0\ufe0f 如果继续不调用，你的工作将被反复拦截。"
                ), 2

            elif current_level >= 2:
                # 第 3 次：硬拦截
                return True, (
                    f"\U0001f6d1\ufe0f 【系统硬拦截：必须先规划任务清单】\n"
                    f"架构规范错误：你尚未初始化全局任务清单（TODO List）就尝试调用工具 "
                    f"（{', '.join(blocked_tool_names)}）！\n\n"
                    f"\U0001f4cc **你必须立即执行以下操作：**\n"
                    f"1. 调用 `init_todo_list` 工具，传入你要执行的完整步骤列表\n"
                    f"2. 步骤示例：[\"扫描目录\", \"读取核心文件\", \"分析代码\", \"写入报告\"]\n"
                    f"3. 初始化完成后，下一轮再执行具体工具调用\n\n"
                    f"\u26a0\ufe0f 注意：如果你继续不调用 init_todo_list 而直接调用其他工具，\n"
                    f"    你的工作将被反复拦截，无法推进。"
                ), 3

        return False, "", 0
