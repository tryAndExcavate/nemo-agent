from dataclasses import dataclass
from app.context.token_estimator import TokenEstimator


@dataclass
class ContextPolicy:
    token_threshold: int = 60000
    keep_recent_tools: int = 4
    max_tool_length: int = 2000
    protected_tools: list[str] = None

    def __post_init__(self):
        if self.protected_tools is None:
            self.protected_tools = []

    @staticmethod
    def defaults() -> "ContextPolicy":
        return ContextPolicy()


class ContextCompactor:
    """Two-layer context compaction:
    1. micro_compact: replaces old tool results with placeholders, keeps recent N
    2. auto_compact: LLM summarizes when over token threshold
    """

    def __init__(self, policy: ContextPolicy, llm_client=None):
        self.policy = policy
        self.llm_client = llm_client

    def compact(self, messages: list[dict], current_question: str | None = None):
        """In-place compaction of messages list."""
        self._micro_compact(messages)
        token_count = TokenEstimator.estimate_messages(messages)
        if token_count > self.policy.token_threshold:
            self._truncate_compact(messages)

    def _micro_compact(self, messages: list[dict]):
        """Replace old tool results with placeholders, keeping recent ones."""
        tool_result_indices = [
            i for i, m in enumerate(messages) if m.get("role") == "tool"
        ]
        if len(tool_result_indices) <= self.policy.keep_recent_tools:
            return

        # Keep last N tool results, truncate older ones
        keep_from = tool_result_indices[-(self.policy.keep_recent_tools)]
        for i in tool_result_indices[: -(self.policy.keep_recent_tools)]:
            content = messages[i].get("content", "")
            if len(content) > self.policy.max_tool_length:
                messages[i]["content"] = content[: self.policy.max_tool_length] + "\n...[truncated]"

    def _truncate_compact(self, messages: list[dict]):
        """Simple truncation-based compaction as fallback."""
        # Keep system message + first user message + last N messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        keep_count = max(10, len(non_system) // 3)
        truncated = non_system[-keep_count:]

        messages.clear()
        messages.extend(system_msgs)
        messages.extend(truncated)
