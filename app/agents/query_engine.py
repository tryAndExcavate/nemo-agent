"""QueryEngine 核心实现。

负责对话全生命周期：维护消息历史、调用 API、执行工具调用、管理 token 预算、
处理错误和重试、触发上下文压缩。

借鉴 Claude Code QueryEngine 设计。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("query_engine")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

from app.models.query_engine import (
    AssistantMessage,
    ContentBlock,
    Message,
    ProcessedInput,
    StreamEvent,
    StreamEventType,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    UserMessage,
    SystemMessage,
    messages_to_list,
    list_to_messages,
)
from app.tools.base import Tool, ToolResult, ToolUseContext
from app.context.context import Context


# =========================================================
# QueryEngineConfig
# =========================================================

@dataclass
class QueryEngineConfig:
    tools: list[Tool]
    llm_client: Any = None              # AsyncOpenAI 实例（由上层工厂提供）
    model: str = ""                     # 模型名称（由上层工厂提供）
    can_use_tool: Any = lambda name, inp: True  # 默认允许所有工具
    get_app_state: Any = None
    set_app_state: Any = None
    initial_messages: list[Message] = field(default_factory=list)
    conversation_id: str = ""
    cwd: str = "."                      # 工作区路径，用于查找 GlobalState 和工具执行

    max_turns: int = 25
    custom_system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None
    max_budget_usd: Optional[float] = None
    task_budget: Optional[dict] = None
    commands: list[Any] = field(default_factory=list)
    mcp_clients: list[Any] = field(default_factory=list)
    agents: list[Any] = field(default_factory=list)
    use_memory_agent: bool = False  # True = 用 memory-retriever 子智能体替代原生记忆加载


# =========================================================
# QueryEngineState —— 会话级状态
# =========================================================

@dataclass
class QueryEngineState:
    conversation_id: str
    messages: list[Message] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    turn_count: int = 0
    context_compressed: bool = False  # 标记是否刚被手动压缩（避免 finally 覆盖 meta）
    started_at: float = 0.0
    finished_at: float = 0.0


# =========================================================
# QueryEngine
# =========================================================

class QueryEngine:
    def __init__(self, config: QueryEngineConfig, initial_state: Optional[QueryEngineState] = None, store=None):
        self.config = config

        # 会话存储（JSONL 持久化）— 始终创建 store 以加载历史
        if store is not None:
            self.store = store
        else:
            from app.storage.jsonl_store import JSONLSessionStore
            self.store = JSONLSessionStore()

        # 启动时从磁盘恢复历史（如果有的话）
        existing = self.store.load_all(config.conversation_id)
        self.state = initial_state or QueryEngineState(
            conversation_id=config.conversation_id,
            messages=existing or list(config.initial_messages),
        )
        self.abort_event: asyncio.Event = asyncio.Event()
        self.permission_denials: list[dict] = []
        self.discovered_skill_names: set[str] = set()
        self.loaded_nested_memory_paths: set[str] = set()
        self.live_memory_store = None  # 主 Agent 可选绑定，子 Agent 为 None

        # 上下文维护窗口
        system_prompt = self._build_system_prompt()
        self.context = Context(
            system_prompt=system_prompt,
            tools=config.tools,
            messages=self.state.messages,
        )
        logger.info(f"[QE][init] conv={config.conversation_id} cwd={config.cwd} model={config.model} "
                     f"history={len(self.state.messages)} msgs tools={len(config.tools)} max_turns={config.max_turns}")

    def append_message(self, msg: Message) -> None:
        self.state.messages.append(msg)
        self.context.add_message(msg)
        # _persist=False 时不写 JSONL（子 Agent 用），但 store 始终存在用于加载历史
        if getattr(self.config, "_persist", True):
            self.store.append_message(self.config.conversation_id, msg)
        # 同步写入 live memory（主 Agent 有 live_memory_store 时）
        if self.live_memory_store is not None:
            import time as _time
            role = "user" if isinstance(msg, UserMessage) else (
                "assistant" if isinstance(msg, AssistantMessage) else "system"
            )
            content = msg.content if isinstance(msg, (UserMessage, SystemMessage)) else ""
            if isinstance(msg, AssistantMessage):
                from app.models.query_engine import TextBlock
                content = "\n".join(b.text for b in msg.content if isinstance(b, TextBlock))
            self.live_memory_store.add_message(role=role, content=content, timestamp=_time.time())

    def snapshot(self) -> dict:
        """
        导出可持久化的纯 dict。
        注意：不能直接 asdict(self.state)，因为 messages 里含 Union 类型，
        必须走专门的 messages_to_list 转换，否则 Block 的具体子类型信息会丢失。
        """
        return {
            "conversation_id": self.state.conversation_id,
            "messages": messages_to_list(self.state.messages),
            "total_input_tokens": self.state.total_input_tokens,
            "total_output_tokens": self.state.total_output_tokens,
            "total_cost_usd": self.state.total_cost_usd,
            "turn_count": self.state.turn_count,
            "started_at": self.state.started_at,
            "finished_at": self.state.finished_at,
        }

    @classmethod
    def restore(cls, config: QueryEngineConfig, snapshot: dict) -> "QueryEngine":
        state = QueryEngineState(
            conversation_id=snapshot["conversation_id"],
            messages=list_to_messages(snapshot["messages"]),
            total_input_tokens=snapshot.get("total_input_tokens", 0),
            total_output_tokens=snapshot.get("total_output_tokens", 0),
            total_cost_usd=snapshot.get("total_cost_usd", 0.0),
            turn_count=snapshot.get("turn_count", 0),
            started_at=snapshot.get("started_at", 0.0),
            finished_at=snapshot.get("finished_at", 0.0),
        )
        return cls(config, initial_state=state)

    # =====================================================
    # submitMessage —— 处理一次用户输入
    # =====================================================
    async def submit_message(self, user_input: str) -> AsyncIterator[StreamEvent]:
        conv = self.config.conversation_id
        self.state.started_at = time.time()
        logger.info(f"[QE][submit] conv={conv} input={user_input[:100]}")
        try:
            # ① 预处理用户输入
            processed = await self._preprocess_input(user_input)
            logger.debug(f"[QE][submit] conv={conv} preprocess done: slash={processed.slash_command} attachments={len(processed.attachments)}")

            if processed.is_command_only:
                logger.info(f"[QE][submit] conv={conv} command-only: {processed.slash_command}")
                async for event in self._handle_command_only(processed):
                    yield event
                self.state.finished_at = time.time()
                yield StreamEvent(StreamEventType.DONE)
                return

            # ② 构建消息列表并更新上下文
            messages = await self._build_message_list(processed)
            self.context.reset(messages)
            ctx = self.context.estimate_usage()
            logger.info(f"[QE][submit] conv={conv} context ready: {len(messages)} msgs, ~{ctx.total_tokens} tokens")

            # ③ 调用 query() 核心循环
            async for raw_event in self.query():
                # ④ 后处理
                await self._postprocess(raw_event)

                # ⑤ 流式 yield 给调用方
                yield raw_event

                if raw_event.type in (
                    StreamEventType.TURN_LIMIT_EXCEEDED,
                    StreamEventType.BUDGET_EXCEEDED,
                ):
                    break

                if self.abort_event.is_set():
                    logger.info(f"[QE][submit] conv={conv} aborted by user")
                    yield StreamEvent(StreamEventType.SYSTEM_INFO, {"msg": "已中断"})
                    break

            await self._finalize_turn()
            self.state.finished_at = time.time()
            logger.info(f"[QE][submit] conv={conv} done: total_msgs={len(self.state.messages)} "
                         f"in_tokens={self.state.total_input_tokens} out_tokens={self.state.total_output_tokens}")
            yield StreamEvent(StreamEventType.DONE)

        except Exception as e:
            self.state.finished_at = time.time()
            logger.error(f"[QE][submit] conv={conv} exception: {type(e).__name__}: {e}", exc_info=True)
            yield StreamEvent(StreamEventType.ERROR, {"error": str(e)})
            yield StreamEvent(StreamEventType.DONE)

    # =====================================================
    # ③ query() —— 核心执行循环
    # =====================================================
    async def query(self) -> AsyncIterator[StreamEvent]:
        conv = self.config.conversation_id
        current_messages = self.context.clone_messages()
        turn_count = 0
        logger.info(f"[QE][query] conv={conv} start: {len(current_messages)} initial msgs")

        while True:
            turn_count += 1

            # --- 检查轮次限制 ---
            if turn_count > (self.config.max_turns or 25):
                logger.warning(f"[QE][query] conv={conv} turn_limit_exceeded: {turn_count}")
                self.state.turn_count = turn_count
                yield StreamEvent(StreamEventType.TURN_LIMIT_EXCEEDED, {"turn": turn_count})
                return

            # --- 发送 LLM 输入监控 ---
            ctx_usage = self.context.estimate_usage()
            logger.info(f"[QE][query] conv={conv} turn={turn_count} msgs={len(current_messages)} "
                         f"ctx={ctx_usage.total_tokens}t (sys={ctx_usage.system_prompt_tokens} "
                         f"hist={ctx_usage.history_tokens} tools_def={ctx_usage.tool_definitions_tokens} "
                         f"tools_res={ctx_usage.tool_results_tokens} input={ctx_usage.current_input_tokens})")
            yield StreamEvent(StreamEventType.LLM_INPUT, {
                "turn": turn_count,
                "message_count": len(current_messages),
                "messages": self._summarize_messages_for_monitor(current_messages),
                "context_usage": ctx_usage.to_dict(),
            })

            # --- 调用 LLM API（流式，OpenAI 兼容格式） ---
            accumulated_text = ""
            content_blocks: list[ContentBlock] = []
            tool_calls_raw: list[dict] = []  # OpenAI 格式的 tool_calls
            usage: Optional[dict] = None
            thinking_text = ""

            async for chunk in self._call_llm_api_stream(current_messages):
                if chunk["type"] == "text":
                    accumulated_text += chunk["text"]
                    yield StreamEvent(StreamEventType.TEXT_DELTA, chunk["text"])

                elif chunk["type"] == "thinking":
                    # 思考块：存入 content_blocks 但不输出给用户
                    thinking_text += chunk["text"]
                    content_blocks.append(ThinkingBlock(thinking=chunk["text"]))

                elif chunk["type"] == "tool_use":
                    content_blocks.append(
                        ToolUseBlock(id=chunk["id"], name=chunk["name"], input=chunk["input"])
                    )
                    tool_calls_raw.append({
                        "id": chunk["id"],
                        "type": "function",
                        "function": {
                            "name": chunk["name"],
                            "arguments": json.dumps(chunk["input"], ensure_ascii=False),
                        },
                    })
                    yield StreamEvent(
                        StreamEventType.TOOL_USE_START,
                        {"id": chunk["id"], "name": chunk["name"], "input": chunk["input"]},
                    )

                elif chunk["type"] == "usage":
                    usage = chunk["usage"]

            logger.info(f"[QE][query] conv={conv} turn={turn_count} LLM done: "
                         f"text={len(accumulated_text)}chars thinking={len(thinking_text)}chars "
                         f"tool_calls={len(tool_calls_raw)} usage={usage}")

            # --- 组装本轮 assistant 消息并立即落盘 ---
            if accumulated_text:
                content_blocks.insert(0, TextBlock(text=accumulated_text))

            # --- 发送 LLM 输出监控 ---
            yield StreamEvent(StreamEventType.LLM_OUTPUT, {
                "turn": turn_count,
                "text": accumulated_text,
                "thinking": thinking_text,
                "tool_calls": [{"name": tc["function"]["name"], "input": json.loads(tc["function"]["arguments"] or "{}")} for tc in tool_calls_raw],
                "usage": usage,
            })

            assistant_msg = AssistantMessage(content=content_blocks)
            current_messages = current_messages + [assistant_msg]
            self.append_message(assistant_msg)

            yield StreamEvent(
                StreamEventType.MESSAGE_COMPLETE,
                {"turn": turn_count, "usage": usage},
            )

            # --- 判断是否结束 ---
            # 有工具调用 → 继续执行
            # 无工具调用 → 检查文本是否包含"结束"信号
            if tool_calls_raw:
                pass  # 继续执行工具
            else:
                # 提取纯文本（去掉 thinking blocks）
                text_parts = [b.text for b in content_blocks if isinstance(b, TextBlock)]
                full_text = "\n".join(text_parts).strip()

                # 仅当文本以"结束"结尾时才终止循环
                if full_text.endswith("结束"):
                    logger.info(f"[QE][query] conv={conv} turn={turn_count} terminated: '结束' signal")
                    # 去掉末尾的"结束"标记再存储
                    cleaned = full_text[:-2].rstrip()
                    if cleaned:
                        # 替换最后一条 assistant 消息的文本
                        self.state.messages[-1] = AssistantMessage(
                            content=[TextBlock(text=cleaned)] + [b for b in content_blocks if not isinstance(b, TextBlock)]
                        )
                    self.state.turn_count = turn_count
                    return
                else:
                    # 没有工具调用也没有"结束"信号 → 注入提示推动决策，继续循环
                    logger.info(f"[QE][query] conv={conv} turn={turn_count} no tools + no '结束', injecting nudge")
                    self.state.turn_count = turn_count
                    # 在消息列表中追加一条 user 提示，迫使 LLM 做出下一步决策
                    nudge = UserMessage(content="[系统提示] 请根据上面的分析结果，调用工具继续执行任务，或者如果任务已全部完成则输出\"结束\"。")
                    current_messages = current_messages + [nudge]
                    self.append_message(nudge)
                    continue

            # --- 是 → 并行执行工具调用 ---
            tool_use_blocks = [b for b in content_blocks if isinstance(b, ToolUseBlock)]
            tool_results = await self._run_tools_parallel(tool_use_blocks)

            for tr in tool_results:
                yield StreamEvent(
                    StreamEventType.TOOL_RESULT,
                    {
                        "tool_use_id": tool_use_blocks[tool_results.index(tr)].id,
                        "content": tr.output,
                        "is_error": tr.is_error,
                    },
                )

            # --- 工具结果追加到消息列表并立即落盘 ---
            # OpenAI 要求每个工具结果单独一条 SystemMessage(role="tool")
            for i, tr in enumerate(tool_results):
                tool_msg = SystemMessage(
                    subtype="tool_result",
                    content=self._stringify_tool_content(tr.output, tr.is_error),
                    tool_use_id=tool_use_blocks[i].id,
                    is_error=tr.is_error,
                )
                current_messages = current_messages + [tool_msg]
                self.append_message(tool_msg)

            # --- 检查 token 预算 ---
            if self._check_token_budget(current_messages):
                self.state.turn_count = turn_count
                yield StreamEvent(StreamEventType.BUDGET_EXCEEDED, {"turn": turn_count})
                return

            # 循环继续

    # =====================================================
    # query() 的辅助方法（OpenAI 兼容核心逻辑）
    # =====================================================
    async def _call_llm_api_stream(
        self, messages: list[Message]
    ) -> AsyncIterator[dict]:
        """
        封装 OpenAI 兼容的 Chat Completions 流式调用，
        统一转换成内部 chunk 格式：{"type": "text"|"thinking"|"tool_use"|"usage", ...}
        """
        client = self.config.llm_client
        model = self.config.model

        # 通过 Context 组装 API 消息
        api_messages = self.context.to_api_messages()
        tool_schemas = self.context.get_tool_schemas()

        stream = await client.chat.completions.create(
            model=model,
            messages=api_messages,
            tools=tool_schemas if tool_schemas else None,
            stream=True,
            stream_options={"include_usage": True},  # 让最后一个 chunk 带上 usage
        )

        # OpenAI 流式返回的 tool_calls 是按 index 分片传输的，
        # 参数（arguments）是逐段拼接的 JSON 字符串，需要手动累积
        tool_call_accumulator: dict[int, dict] = {}

        async for chunk in stream:
            # 最后一个 usage-only chunk 通常 choices 为空
            if not chunk.choices:
                if getattr(chunk, "usage", None):
                    yield {
                        "type": "usage",
                        "usage": {
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                        },
                    }
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            # --- 部分推理模型（如 DeepSeek-R1）通过 reasoning_content 承载思考过程 ---
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "thinking", "text": reasoning}

            # --- 正文文本增量 ---
            if delta.content:
                yield {"type": "text", "text": delta.content}

            # --- 工具调用增量，按 index 累积 ---
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_accumulator:
                        tool_call_accumulator[idx] = {"id": "", "name": "", "arguments": ""}

                    if tc_delta.id:
                        tool_call_accumulator[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_call_accumulator[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_call_accumulator[idx]["arguments"] += tc_delta.function.arguments

                    tool_call_accumulator[idx] = tool_call_accumulator[idx]  # 显式回写，清晰起见

            # --- finish_reason 出现时，说明本轮流结束，把累积的 tool_calls 全部产出 ---
            if choice.finish_reason:
                for idx in sorted(tool_call_accumulator.keys()):
                    tc = tool_call_accumulator[idx]
                    try:
                        parsed_input = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        parsed_input = {}
                    yield {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": parsed_input,
                    }
                tool_call_accumulator.clear()

    def _to_api_messages(self, messages: list[Message], system_prompt: str) -> list[dict]:
        """把内部 Message 转换成 OpenAI API 需要的 dict 格式，并在最前面插入 system 消息"""
        api_messages: list[dict] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        for m in messages:
            if isinstance(m, UserMessage):
                api_messages.append({"role": "user", "content": m.content})

            elif isinstance(m, AssistantMessage):
                # 提取文本内容
                text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
                text_content = "\n".join(text_parts) if text_parts else None

                # 提取 tool_calls（OpenAI 格式）
                tool_calls = []
                for b in m.content:
                    if isinstance(b, ToolUseBlock):
                        tool_calls.append({
                            "id": b.id,
                            "type": "function",
                            "function": {
                                "name": b.name,
                                "arguments": json.dumps(b.input, ensure_ascii=False),
                            },
                        })

                d: dict = {"role": "assistant", "content": text_content}
                if tool_calls:
                    d["tool_calls"] = tool_calls
                api_messages.append(d)

            elif isinstance(m, SystemMessage):
                # 工具结果 → OpenAI 的 role="tool" 消息
                if m.subtype == "tool_result" and m.tool_use_id:
                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": m.tool_use_id,
                        "content": m.content,
                    })
                else:
                    # error / info 作为 system 消息
                    api_messages.append({"role": "system", "content": m.content})

        return api_messages

    def _stringify_tool_content(self, content: Any, is_error: bool) -> str:
        """OpenAI 的 tool 消息 content 要求是字符串"""
        if isinstance(content, str):
            text = content
        else:
            try:
                text = json.dumps(content, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(content)
        return f"[ERROR] {text}" if is_error else text

    def _build_tool_use_context(self) -> ToolUseContext:
        from app.models.state import get_global_state
        # 合并外部注入的 _extra_tool_context（子 Agent 用）
        extras = dict(self._extra_tool_context) if hasattr(self, "_extra_tool_context") else {}
        return ToolUseContext(
            cwd=get_global_state(self.config.cwd).cwd,
            abort_event=self.abort_event,
            messages=tuple(self.state.messages),
            extras=extras,
        )

    async def _run_tools_parallel(
        self, tool_calls: list[ToolUseBlock]
    ) -> list[ToolResult]:
        """并行执行多个工具调用"""
        conv = self.config.conversation_id
        tool_names = [tc.name for tc in tool_calls]
        logger.info(f"[QE][tools] conv={conv} executing: {tool_names}")
        context = self._build_tool_use_context()

        async def run_one(tu: ToolUseBlock) -> ToolResult:
            tool = next((t for t in self.config.tools if t.name == tu.name), None)
            if tool is None:
                logger.warning(f"[QE][tools] conv={conv} unknown tool: {tu.name}")
                return ToolResult(output=f"未知工具: {tu.name}", is_error=True)

            # --- 权限检查 ---
            if tool.needs_permission(tu.input):
                if self.config.can_use_tool and not self.config.can_use_tool(tool.name, tu.input):
                    logger.info(f"[QE][tools] conv={conv} permission denied: {tool.name}")
                    self.permission_denials.append({"tool": tool.name, "input": tu.input})
                    return ToolResult(output="用户拒绝了该操作", is_error=True)

            # --- 中断检查 ---
            if context.is_aborted():
                return ToolResult(output="已中断", is_error=True)

            try:
                logger.debug(f"[QE][tools] conv={conv} running {tu.name}({json.dumps(tu.input, ensure_ascii=False)[:200]})")
                result = await tool.execute(tu.input, context)
                out_preview = str(result.output)[:100] if result.output else ""
                logger.info(f"[QE][tools] conv={conv} {tu.name} -> {'ERROR' if result.is_error else 'OK'} ({len(str(result.output))} chars) {out_preview}")
                return result
            except Exception as e:
                logger.error(f"[QE][tools] conv={conv} {tu.name} exception: {type(e).__name__}: {e}")
                return ToolResult(output=str(e), is_error=True)

        results = await asyncio.gather(*(run_one(tu) for tu in tool_calls))
        logger.info(f"[QE][tools] conv={conv} batch done: {len(results)} results")
        return results

    # =====================================================
    # ⑥ 手动上下文压缩
    # =====================================================

    def _format_messages_for_summary(self, messages: list[Message]) -> str:
        """把消息列表格式化为可读文本，供 LLM 摘要使用"""
        lines = []
        for m in messages:
            if isinstance(m, UserMessage):
                text = m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False)
                lines.append(f"[用户]: {text[:500]}")
            elif isinstance(m, AssistantMessage):
                parts = []
                for b in m.content:
                    if isinstance(b, TextBlock):
                        parts.append(b.text[:300])
                    elif isinstance(b, ToolUseBlock):
                        parts.append(f"[调用工具 {b.name}]")
                if parts:
                    lines.append(f"[助手]: {' '.join(parts)[:500]}")
            elif isinstance(m, SystemMessage):
                if m.subtype == "tool_result":
                    text = str(m.content)[:200]
                    lines.append(f"[工具结果]: {text}")
        return "\n".join(lines)

    async def _call_llm_summary(self, history_text: str) -> str:
        """调用 LLM 对历史对话生成压缩摘要"""
        client = self.config.llm_client
        model = self.config.model
        summary_prompt = """请总结以下对话历史，保留：
1. 已完成的任务和结果
2. 重要的决策和原因
3. 当前正在进行的任务状态
4. 关键的代码变更（文件名和变更摘要）
5. 用户的重要偏好和约束

不需要保留：
- 工具调用的详细输出（只保留结果）
- 中间步骤的详细过程
- 已解决的错误的详细信息

请用简洁的中文输出摘要，控制在 500 字以内。"""
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": summary_prompt},
                    {"role": "user", "content": f"以下是需要总结的对话历史：\n\n{history_text}"},
                ],
                max_tokens=1000,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"[QE][compress] LLM summary failed: {e}")
            return f"[摘要生成失败: {e}]"

    async def compress_context(self) -> dict:
        """手动压缩上下文：生成摘要保存到文件，重置 context 为摘要+最近3条"""
        if not getattr(self.config, "_persist", True):
            return {"error": "子 Agent 不支持上下文压缩"}
        conv = self.config.conversation_id
        usage_before = self.context.estimate_usage()
        logger.info(f"[QE][compress] conv={conv} before: {usage_before.total_tokens}t "
                     f"msgs={len(self.state.messages)}")

        # 1. 格式化全部历史为文本
        history_text = self._format_messages_for_summary(self.state.messages)
        if not history_text.strip():
            return {"error": "无历史消息可压缩", "before_tokens": 0, "after_tokens": 0}

        # 2. 调 LLM 生成摘要
        summary = await self._call_llm_summary(history_text)

        # 3. 保存摘要（不动 JSONL）
        self.store.save_compressed_summary(conv, {
            "summary_text": summary,
            "original_msg_count": len(self.state.messages),
            "original_tokens": usage_before.total_tokens,
            "compressed_tokens": 0,  # 下面估算后填入
        })

        # 4. 用摘要 + 最近3条重建 context（不改 state.messages，JSONL 保留完整历史）
        recent = self.state.messages[-3:] if len(self.state.messages) > 3 else self.state.messages
        compressed_messages = [
            SystemMessage(content=f"[Earlier conversation summary]\n{summary}")
        ] + list(recent)
        self.context.reset(compressed_messages)
        self.state.context_compressed = True

        usage_after = self.context.estimate_usage()
        logger.info(f"[QE][compress] conv={conv} after: {usage_after.total_tokens}t "
                     f"(saved {usage_before.total_tokens - usage_after.total_tokens}t)")

        # 5. 更新摘要文件 + meta（让 /load 返回压缩后的值）
        self.store.save_compressed_summary(conv, {
            "summary_text": summary,
            "original_msg_count": len(self.state.messages),
            "original_tokens": usage_before.total_tokens,
            "compressed_tokens": usage_after.total_tokens,
        })
        self.store.save_meta(conv, {
            "ctx_system_tokens": usage_after.system_prompt_tokens,
            "ctx_history_tokens": usage_after.history_tokens,
            "ctx_tool_def_tokens": usage_after.tool_definitions_tokens,
            "ctx_tool_result_tokens": usage_after.tool_results_tokens,
            "ctx_input_tokens": usage_after.current_input_tokens,
            "total_input_tokens": usage_after.total_tokens,
        })

        return {
            "before_tokens": usage_before.total_tokens,
            "after_tokens": usage_after.total_tokens,
            "summary_preview": summary[:200],
            "ctx_usage": usage_after.to_dict(),
        }

    def _check_token_budget(self, messages: list[Message]) -> bool:
        if self.config.task_budget is None:
            return False
        usage = self.context.estimate_usage()
        budget = self.config.task_budget.get("total", float("inf"))
        exceeded = usage.total_tokens > budget
        if exceeded:
            logger.warning(f"[QE][budget] exceeded: {usage.total_tokens} > {budget}")
        return exceeded

    def _build_system_prompt(self) -> str:
        prompt = self.config.custom_system_prompt or "You are a helpful assistant."
        if self.config.append_system_prompt:
            prompt += "\n" + self.config.append_system_prompt
        return prompt

    def _build_tool_schemas(self) -> list[dict]:
        """通过 Tool.to_openai_schema() 统一转换"""
        return [t.to_openai_schema() for t in self.config.tools]

    def _summarize_messages_for_monitor(self, messages: list[Message]) -> list[dict]:
        """将消息列表压缩为前端可展示的摘要格式（不含完整内容，避免数据过大）"""
        summary = []
        for m in messages:
            if isinstance(m, UserMessage):
                text = m.content if isinstance(m.content, str) else str(m.content)
                summary.append({"role": "user", "preview": text[:300]})
            elif isinstance(m, AssistantMessage):
                text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
                tool_uses = [{"name": b.name} for b in m.content if isinstance(b, ToolUseBlock)]
                summary.append({
                    "role": "assistant",
                    "preview": "\n".join(text_parts)[:300] if text_parts else "",
                    "tool_calls": tool_uses,
                })
            elif isinstance(m, SystemMessage):
                if m.subtype == "tool_result":
                    preview = str(m.content)[:200] if m.content else ""
                    summary.append({"role": "tool", "tool_use_id": m.tool_use_id, "preview": preview, "is_error": m.is_error})
                else:
                    summary.append({"role": "system", "preview": str(m.content)[:200]})
        return summary

    # =====================================================
    # ① 预处理用户输入
    # =====================================================
    async def _preprocess_input(self, user_input: str) -> ProcessedInput:
        text = user_input.strip()
        slash_command, slash_args, is_command_only = self._parse_slash_command(text)
        if slash_command:
            text = slash_args or ""
        attachments = self._extract_attachments(user_input)
        injected_memory = await self._load_relevant_memory(text)
        return ProcessedInput(
            text=text,
            slash_command=slash_command,
            slash_command_args=slash_args,
            attachments=attachments,
            injected_memory=injected_memory,
            is_command_only=is_command_only,
        )

    def _parse_slash_command(self, text: str) -> tuple[Optional[str], Optional[str], bool]:
        if not text.startswith("/"):
            return None, None, False
        parts = text[1:].split(maxsplit=1)
        command_name = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        matched = next((c for c in self.config.commands if c.name == command_name), None)
        if matched is None:
            return None, None, False
        is_local_only = getattr(matched, "is_local_only", False)
        return command_name, args, is_local_only

    def _extract_attachments(self, user_input: str) -> list[dict]:
        # TODO: 解析 @file.py 引用等，读取内容打包成附件
        return []

    async def _load_relevant_memory(self, text: str) -> Optional[str]:
        # TODO: 结合 self.loaded_nested_memory_paths 做去重加载
        return None

    # =====================================================
    # AOP：记忆模式切面（不修改 _load_relevant_memory 本体）
    # =====================================================
    def apply_memory_agent_patch(self) -> None:
        """切面注入：将 _load_relevant_memory 替换为支持子 Agent 的版本。

        原始方法保留在 _original_load_relevant_memory 中，
        通过 self.config.use_memory_agent 标志切换行为。
        """
        if hasattr(self, "_original_load_relevant_memory"):
            return  # 已打过补丁，幂等

        self._original_load_relevant_memory = self._load_relevant_memory
        engine = self  # 闭包捕获

        async def _patched_load_relevant_memory(text: str) -> Optional[str]:
            if not getattr(engine.config, "use_memory_agent", False):
                return await engine._original_load_relevant_memory(text)
            # 记忆 Agent 模式：异步调用 memory-retriever 子智能体
            return await _dispatch_memory_retriever(engine, text)

        # 绑定到实例（直接赋值属性，不走 types.MethodType 避免重复传 self）
        self._load_relevant_memory = _patched_load_relevant_memory

    async def _handle_command_only(self, processed: ProcessedInput) -> AsyncIterator[StreamEvent]:
        yield StreamEvent(
            StreamEventType.SYSTEM_INFO,
            {"msg": f"执行本地命令: {processed.slash_command}"},
        )

    # =====================================================
    # ② 构建消息列表
    # =====================================================
    async def _build_message_list(self, processed: ProcessedInput) -> list[Message]:
        content: Any = processed.text
        if processed.attachments:
            content = self._merge_attachments_into_content(processed.text, processed.attachments)

        # 直接使用完整历史消息，由 to_api_messages 保证 system 消息在最前面
        # （压缩摘要路径已移除——过滤 SystemMessage 会破坏 user/assistant 交替顺序）
        messages = list(self.state.messages)

        if processed.injected_memory:
            # 记忆 Agent 输出注入为 SystemMessage，不落盘、不显示在 UI
            mem_msg = SystemMessage(content=f"[Memory]\n{processed.injected_memory}")
            messages.insert(0, mem_msg)

        new_user_message = UserMessage(content=content)
        messages.append(new_user_message)
        self.append_message(new_user_message)

        return messages

    def _merge_attachments_into_content(self, text: str, attachments: list[dict]) -> Any:
        """
        OpenAI 视觉模型的多模态格式：
        [{"type": "text", "text": ...}, {"type": "image_url", "image_url": {"url": ...}}]
        """
        blocks = [{"type": "text", "text": text}]
        blocks.extend(attachments)
        return blocks

    # =====================================================
    # ④ 后处理
    # =====================================================
    async def _postprocess(self, event: StreamEvent) -> None:
        if event.type == StreamEventType.MESSAGE_COMPLETE:
            usage = event.data.get("usage") if event.data else None
            if usage:
                self._record_usage(usage)

        elif event.type == StreamEventType.BUDGET_EXCEEDED:
            self.abort_event.set()

        await self._trigger_hooks(event)

    def _record_usage(self, usage: dict) -> None:
        self.state.total_input_tokens += usage.get("input_tokens", 0)
        self.state.total_output_tokens += usage.get("output_tokens", 0)
        # TODO: 按 model 单价换算 cost_usd
        if self.config.max_budget_usd and self.state.total_cost_usd >= self.config.max_budget_usd:
            self.abort_event.set()

    async def _trigger_hooks(self, event: StreamEvent) -> None:
        pass

    async def _finalize_turn(self) -> None:
        await self._save_session()
        await self._check_compaction()

    async def _save_session(self) -> None:
        pass

    async def _check_compaction(self) -> None:
        pass

    def abort(self) -> None:
        self.abort_event.set()


# =========================================================
# QueryEngineRegistry —— 按 session_id 管理引擎实例
# =========================================================

class QueryEngineRegistry:
    """全局注册表：每个 session_id 对应一个 QueryEngine 实例。"""
    _engines: dict[str, QueryEngine] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_or_create(cls, session_id: str, config: QueryEngineConfig) -> QueryEngine:
        async with cls._lock:
            if session_id not in cls._engines:
                cls._engines[session_id] = QueryEngine(config)
            return cls._engines[session_id]

    @classmethod
    def get(cls, session_id: str) -> Optional[QueryEngine]:
        return cls._engines.get(session_id)

    @classmethod
    def destroy(cls, session_id: str):
        """结束会话时释放资源"""
        engine = cls._engines.pop(session_id, None)
        if engine:
            engine.abort()


# =========================================================
# AOP 切面函数：memory-retriever 子智能体调度
# =========================================================

async def _dispatch_memory_retriever(engine: "QueryEngine", text: str) -> Optional[str]:
    """调用 memory-retriever 子智能体检索相关记忆，返回简报文本。

    独立于 QueryEngine 主逻辑，通过 apply_memory_agent_patch 注入。
    """
    try:
        from app.subagent.registry import get as get_definition
        from app.subagent.policy import AgentExecutionContext
        from app.memory.live_view import LiveMemoryReadOnlyView
        from app.memory.history_reader import ConversationHistoryReader
        from app.memory.retrieval_context import MemoryRetrievalContext
        from app.subagent.runner import SubAgentRunner
        from pathlib import Path

        definition = get_definition("memory-retriever")
        if definition is None:
            return None

        # live memory 只读视图
        live_view = None
        if engine.live_memory_store is not None:
            live_view = LiveMemoryReadOnlyView(engine.live_memory_store)

        # history reader 绑定当前会话
        history_reader = None
        sessions_root = Path(".sessions")
        if engine.store is not None:
            history_reader = ConversationHistoryReader(sessions_root, engine.config.conversation_id)

        retrieval = MemoryRetrievalContext(live_memory=live_view, history=history_reader)

        # 执行上下文（复用 engine 的 extras 中已有的，或新建）
        extras = getattr(engine, "_extra_tool_context", {})
        exec_ctx = extras.get("execution_context")
        if exec_ctx is None:
            exec_ctx = AgentExecutionContext.root(engine.config.conversation_id, max_depth=1)

        runner = SubAgentRunner(
            llm_client=engine.config.llm_client,
            parent_model=engine.config.model,
            cwd=engine.config.cwd,
        )

        result = await runner.run(
            definition=definition,
            task=f"检索与以下用户输入相关的记忆信息，返回简报：\n\n{text}",
            execution_context=exec_ctx,
            memory_retrieval=retrieval,
            parent_config=engine.config,
        )

        if result.is_error or not result.text:
            return None

        logger.info(f"[QE][memory-agent] conv={engine.config.conversation_id} "
                     f"retrieved {len(result.text)} chars")
        return result.text

    except Exception as e:
        logger.error(f"[QE][memory-agent] dispatch failed: {e}")
        return None
