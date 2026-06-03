import json

import httpx
import respx

from scriptpilot.agent.loop import AgentEvent, run_agent_loop
from scriptpilot.agent.session import ChatSession

BASE = "https://api.blackbox.ai/v1/chat/completions"


def _assistant(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={"choices": [{"message": msg}]})


def _collect():
    events: list[AgentEvent] = []
    return events, lambda e: events.append(e)


@respx.mock
async def test_loop_text_only_emits_done(tmp_path):
    respx.post(BASE).mock(return_value=_assistant(content="Hello, what should it do?"))
    s = ChatSession.new(tmp_path / "w")
    s.messages.append({"role": "user", "content": "hi"})
    events, emit = _collect()
    await run_agent_loop(s, "m", "key", max_tool_calls=25, bash_timeout=10, emit=emit)
    kinds = [e.kind for e in events]
    assert "assistant_text" in kinds
    assert kinds[-1] == "done"


@respx.mock
async def test_loop_dispatches_tool_then_finishes(tmp_path):
    tool_call = [{"id": "c1", "type": "function",
                  "function": {"name": "update_script",
                               "arguments": json.dumps({"code": "echo hi"})}}]
    respx.post(BASE).side_effect = [
        _assistant(content="", tool_calls=tool_call),
        _assistant(content="Done, the script is ready."),
    ]
    s = ChatSession.new(tmp_path / "w")
    s.messages.append({"role": "user", "content": "make it echo hi"})
    events, emit = _collect()
    await run_agent_loop(s, "m", "key", max_tool_calls=25, bash_timeout=10, emit=emit)
    assert s.draft.content == "echo hi"
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1"
               for m in s.messages)
    assert [e.kind for e in events][-1] == "done"
    assert any(e.kind == "tool_result" for e in events)


@respx.mock
async def test_loop_respects_tool_call_cap(tmp_path):
    tool_call = [{"id": "c", "type": "function",
                  "function": {"name": "bash", "arguments": json.dumps({"cmd": "echo x"})}}]
    respx.post(BASE).mock(return_value=_assistant(content="", tool_calls=tool_call))
    s = ChatSession.new(tmp_path / "w")
    s.messages.append({"role": "user", "content": "go"})
    events, emit = _collect()
    await run_agent_loop(s, "m", "key", max_tool_calls=3, bash_timeout=10, emit=emit)
    tool_results = [e for e in events if e.kind == "tool_result"]
    assert len(tool_results) <= 3
    assert events[-1].kind in ("done", "error")
