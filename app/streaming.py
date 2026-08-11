"""Serialisierung der Claude-Agent-SDK-Messages -> JSON/SSE-Events.

Ein SDK-Message-Objekt wird zu genau einem SSE-Event (`event: <type>` + JSON-`data`).
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


def serialize_block(block: Any) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "thinking": block.thinking}
    if isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, (ToolResultBlock, ServerToolResultBlock)):
        return {
            "type": "tool_result",
            "tool_use_id": getattr(block, "tool_use_id", None),
            "content": getattr(block, "content", None),
            "is_error": getattr(block, "is_error", None),
        }
    # Fallback: unbekannter Blocktyp
    return {"type": "unknown", "repr": repr(block)}


def _content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [serialize_block(b) for b in content]
    return content


def serialize_message(msg: Any) -> dict[str, Any] | None:
    """SDK-Message -> serialisierbares dict mit `type`. None = ueberspringen."""
    if isinstance(msg, AssistantMessage):
        return {
            "type": "assistant",
            "content": _content(msg.content),
            "model": msg.model,
            "session_id": msg.session_id,
            "stop_reason": msg.stop_reason,
            "error": msg.error,
        }
    if isinstance(msg, UserMessage):
        return {"type": "user", "content": _content(msg.content)}
    if isinstance(msg, SystemMessage):
        return {"type": "system", "subtype": msg.subtype, "data": msg.data}
    if isinstance(msg, ResultMessage):
        return {
            "type": "result",
            "subtype": msg.subtype,
            "is_error": msg.is_error,
            "num_turns": msg.num_turns,
            "duration_ms": msg.duration_ms,
            "session_id": msg.session_id,
            "total_cost_usd": msg.total_cost_usd,
            "usage": msg.usage,
            "result": msg.result,
            "errors": msg.errors,
        }
    if isinstance(msg, StreamEvent):
        return {"type": "stream", "event": msg.event, "session_id": msg.session_id}
    # RateLimitEvent u.a.: generisch
    if type(msg).__name__ == "RateLimitEvent":
        info = getattr(msg, "rate_limit_info", None)
        return {"type": "rate_limit", "info": repr(info), "session_id": getattr(msg, "session_id", None)}
    return None


def error_event(detail: str) -> dict[str, Any]:
    return {"type": "error", "detail": detail}


def sse(event: dict[str, Any]) -> str:
    """dict -> SSE-Frame. `event["type"]` wird zum Eventnamen."""
    name = event.get("type", "message")
    return f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
