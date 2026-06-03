from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Callable

from scriptpilot.agent.session import ChatSession
from scriptpilot.agent.tools import TOOL_SCHEMAS, dispatch_tool
from scriptpilot.blackbox import chat_completion


@dataclass
class AgentEvent:
    kind: str  # "assistant_text" | "tool_started" | "tool_result" | "done" | "error"
    text: str = ""
    tool: str = ""


EmitFn = Callable[[AgentEvent], None]


async def run_agent_loop(
    session: ChatSession,
    model: str,
    api_key: str,
    *,
    max_tool_calls: int,
    bash_timeout: int,
    emit: EmitFn,
) -> None:
    """Drive the agent until it returns text with no tool calls (or hits the cap).

    Appends assistant + tool messages onto ``session.messages`` as it goes and
    reports progress through ``emit``. Exceptions are reported as an ``error``
    event rather than propagated.
    """
    calls = 0
    try:
        while True:
            assistant = await chat_completion(
                session.messages, model, api_key=api_key, tools=TOOL_SCHEMAS
            )
            session.messages.append(assistant)

            content = assistant.get("content") or ""
            if content.strip():
                emit(AgentEvent("assistant_text", text=content))

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                emit(AgentEvent("done"))
                return

            for i, tc in enumerate(tool_calls):
                if calls >= max_tool_calls:
                    # Append a tool response for EVERY remaining tool_call so the
                    # assistant's tool_calls message is never left dangling — an
                    # unmatched tool_call_id makes the persisted history invalid
                    # and the next API request would be rejected.
                    for rest in tool_calls[i:]:
                        session.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": rest["id"],
                                "content": "tool-call limit reached; stopping.",
                            }
                        )
                    emit(AgentEvent("done"))
                    return
                calls += 1
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                emit(AgentEvent("tool_started", tool=name))
                # dispatch_tool runs blocking subprocesses (bash/verify); off-thread
                # it so the Textual event loop stays responsive during tool calls.
                # A failing tool must not abort the loop or leave a dangling
                # tool_call: feed the error back so the model can self-correct.
                try:
                    result = await asyncio.to_thread(
                        dispatch_tool, name, args, session, bash_timeout=bash_timeout
                    )
                except Exception as e:
                    result = f"tool error: {e}"
                session.messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result}
                )
                emit(AgentEvent("tool_result", tool=name, text=result))
    except Exception as e:  # surfaced to the UI, never crashes the worker
        emit(AgentEvent("error", text=str(e)))
