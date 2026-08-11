"""Runner-Abstraktion ueber das Claude Agent SDK.

Baut `ClaudeAgentOptions` aus Request-Parametern + Defaults und stellt den
One-shot-Lauf (`query`) bereit. Die stateful Variante lebt in sessions.py und
nutzt denselben Options-Builder.

Auth laeuft ueber das Environment (`CLAUDE_CODE_OAUTH_TOKEN`), das der
Server-Prozess erbt und die vom SDK gestartete Claude-Code-Binary uebernimmt.
Es wird bewusst KEIN `ANTHROPIC_API_KEY` gesetzt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query

from .config import settings


def build_options(
    *,
    cwd: Path,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    permission_mode: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
    max_turns: int | None = None,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "permission_mode": permission_mode or settings.default_permission_mode,
    }
    model = model or settings.default_model
    if model:
        kwargs["model"] = model
    if allowed_tools:
        kwargs["allowed_tools"] = allowed_tools
    if disallowed_tools:
        kwargs["disallowed_tools"] = disallowed_tools
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if max_turns is not None:
        kwargs["max_turns"] = max_turns
    if resume:
        kwargs["resume"] = resume
    if settings.claude_cli_path:
        kwargs["cli_path"] = settings.claude_cli_path
    return ClaudeAgentOptions(**kwargs)


async def oneshot_stream(prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
    """Fuehrt einen One-shot-Prompt aus und liefert die SDK-Messages."""
    async for msg in query(prompt=prompt, options=options):
        yield msg
