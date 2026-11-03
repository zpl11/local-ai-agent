"""
AI 聊天客户端 - 压缩/摘要层

策略：当上下文 token 使用率超过 SUMMARIZE_THRESHOLD (75%) 时，
用小模型自动摘要旧对话，释放上下文空间。
"""

import json
import threading
import requests
from datetime import datetime
from typing import Optional

import config
from ai_logger import ExecutionLogger


class Compressor:
    """
    上下文压缩器。
    当上下文使用率超过阈值时，用小模型对旧消息进行摘要压缩。
    """

    def __init__(self, logger: ExecutionLogger = None):
        self.logger = logger
        self._history_summaries = []  # 历史摘要列表

    def _build_system_prompt(self) -> str:
        """构建小模型的摘要系统提示。"""
        return (
            "你是一个对话摘要助手。请将以下对话内容压缩为简洁的摘要，"
            "保留关键信息、决策结论和待办事项。"
            "用中文回答，控制在 500 字以内。"
        )

    def _build_summary_messages(self, messages: list) -> list:
        """
        构建发送给小模型的摘要请求消息。
        过滤掉已有的摘要消息，只保留用户消息和助手回复。
        """
        # 提取需要摘要的消息 (排除系统消息和已有摘要)
        to_summarize = []
        for m in messages:
            if m["role"] == "system":
                continue
            if m["role"] == "assistant" and m.get("content", "").startswith("[摘要]"):
                continue
            to_summarize.append(m)

        # 构建摘要请求
        summary_prompt = self._build_system_prompt()
        conversation_text = json.dumps(to_summarize, ensure_ascii=False)

        return [
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": f"请摘要以下对话：\n\n{conversation_text}"},
        ]

    def summarize(self, messages: list, trace_id: str = None) -> tuple:
        """
        对消息列表进行摘要压缩。
        返回：(新的消息列表, 是否触发了摘要)
        """
        if trace_id is None:
            trace_id = str(datetime.now().strftime("%Y%m%d_%H%M%S"))

        # 记录摘要请求
        if self.logger:
            self.logger.log_step(trace_id, "summarize", {
                "input_messages": len(messages),
            })

        try:
            summary_messages = self._build_summary_messages(messages)
            payload = {
                "model": config.SMALL_MODEL_NAME,
                "messages": summary_messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            }

            resp = requests.post(
                f"{config.SMALL_MODEL_URL}/v1/chat/completions",
                json=payload,
                timeout=config.SUMMARIZE_TIMEOUT,
            )
            resp.raise_for_status()

            data = resp.json()
            summary = data["choices"][0]["message"]["content"]

            # 记录摘要结果
            if self.logger:
                self.logger.log_step(trace_id, "summary", {
                    "summary_preview": summary[:200],
                })

            # 保留系统消息 + 历史摘要 + 最新几条对话 + 新摘要
            system_msgs = [m for m in messages if m["role"] == "system"]
            last_user = messages[-1] if messages[-1]["role"] == "user" else None

            new_messages = system_msgs
            for s in self._history_summaries:
                new_messages.append({"role": "system", "content": f"[摘要] {s}"})

            if last_user:
                new_messages.append(last_user)

            new_messages.append({
                "role": "system",
                "content": f"[摘要] {summary}",
            })

            # 更新历史摘要
            self._history_summaries.append(summary)

            return new_messages, True

        except requests.exceptions.ConnectionError:
            if self.logger:
                self.logger.log_step(trace_id, "error", {
                    "type": "ConnectionError",
                    "message": "小模型摘要服务无法连接",
                })
            return messages, False
        except requests.exceptions.Timeout:
            if self.logger:
                self.logger.log_step(trace_id, "error", {
                    "type": "Timeout",
                    "message": "小模型摘要超时",
                })
            return messages, False
        except Exception as e:
            if self.logger:
                self.logger.log_step(trace_id, "error", {
                    "type": type(e).__name__,
                    "message": str(e),
                })
            return messages, False

    def get_context_usage(self, messages: list, ctx_max: int) -> float:
        """
        估算当前上下文的使用率。
        简单估算：每个中文字符约 0.5 token，每个英文单词约 1 token。
        """
        total_chars = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total_chars += len(block.get("text", ""))
            else:
                total_chars += len(content)

        # 简单估算 token 数
        estimated_tokens = total_chars * 0.7  # 中英混合估算
        return estimated_tokens / ctx_max if ctx_max > 0 else 0
