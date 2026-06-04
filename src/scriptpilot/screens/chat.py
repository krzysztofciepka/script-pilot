from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RichLog, TextArea

from scriptpilot.agent.loop import AgentEvent, run_agent_loop
from scriptpilot.agent.session import ChatSession
from scriptpilot.models import Script
from scriptpilot.storage import ScriptStore

# How much of a tool result to echo into the chat transcript.
_TOOL_OUTPUT_LIMIT = 600


class PromptInput(TextArea):
    """Multi-line prompt box. Enter sends; Shift+Enter inserts a newline."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self.text))
        elif event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")


class ChatScreen(ModalScreen[Script | None]):
    """Conversational script builder for new and existing scripts."""

    DEFAULT_CSS = """
    ChatScreen { align: center middle; }
    ChatScreen #chat-container {
        width: 90%; height: 90%;
        background: $surface; border: solid $primary; padding: 1 2;
    }
    ChatScreen #chat-log {
        height: 1fr; width: 1fr;
        border: round $panel; padding: 0 1; margin-bottom: 1;
    }
    ChatScreen #prompt-input {
        height: 6; width: 1fr; border: round $primary;
    }
    ChatScreen #chat-buttons { height: 3; align: right middle; }
    ChatScreen #chat-buttons Button { margin-left: 1; }
    """

    def __init__(
        self,
        *,
        store: ScriptStore,
        script: Script | None,
        model: str,
        api_key: str,
        max_tool_calls: int,
        bash_timeout: int,
    ):
        super().__init__()
        self._store = store
        self._existing = script
        self._model = model
        self._api_key = api_key
        self._max_tool_calls = max_tool_calls
        self._bash_timeout = bash_timeout
        self._log_text = ""  # accumulating transcript text (testability)

        work_dir = self._store._dir.parent / "sessions" / Script(
            name="", description="", type="bash", content=""
        ).id
        if script is None:
            self.session = ChatSession.new(work_dir)
        else:
            self.session = ChatSession.from_script(script, work_dir)
            saved = self._store.load_transcript(script.id)
            if saved:
                self.session.messages = saved

    def compose(self) -> ComposeResult:
        title = "New script" if self._existing is None else f"Edit: {self._existing.name}"
        with Vertical(id="chat-container"):
            yield Label(
                f"[bold]{title}[/bold]  "
                "[dim]Enter to send · Shift+Enter for newline · /clear to reset[/dim]"
            )
            yield RichLog(id="chat-log", wrap=True, markup=True)
            yield PromptInput(
                id="prompt-input",
                tab_behavior="focus",
                soft_wrap=True,
            )
            with Horizontal(id="chat-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Send", id="send-btn", variant="primary")
                yield Button("Save", id="save-btn", variant="success")

    def on_mount(self):
        # Replay any restored conversation (skip the system message).
        for msg in self.session.messages[1:]:
            role = msg.get("role")
            if role == "user":
                self._append_transcript("user", msg.get("content", ""))
            elif role == "assistant" and (msg.get("content") or "").strip():
                self._append_transcript("agent", msg["content"])
        # Focus the input so the user can type immediately (the RichLog is
        # focusable and would otherwise grab focus, swallowing keystrokes).
        self.query_one("#prompt-input", PromptInput).focus()

    def on_unmount(self):
        # Safety net: remove the session working dir on any teardown (e.g. the
        # user quits mid-conversation), not just the Save/Cancel paths.
        self.session.cleanup()

    def on_prompt_input_submitted(self, message: PromptInput.Submitted):
        self._submit_current()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.session.cleanup()
            self.dismiss(None)
        elif event.button.id == "send-btn":
            self._submit_current()
        elif event.button.id == "save-btn":
            self._do_save()

    def _submit_current(self):
        prompt = self.query_one("#prompt-input", PromptInput)
        text = prompt.text.strip()
        if not text:
            return
        prompt.load_text("")
        self._handle_input(text)

    def _handle_input(self, text: str):
        if text == "/clear":
            self.session.clear()
            self.query_one("#chat-log", RichLog).clear()
            self._log_text = ""
            self._append_transcript("system", "(conversation cleared)")
            return
        self._append_transcript("user", text)
        self.session.messages.append({"role": "user", "content": text})
        self._set_busy(True)
        self.run_worker(self._run_agent(), name="agent", exclusive=True)

    async def _run_agent(self):
        # The agent loop runs as an async worker in the event loop (not a
        # thread), so emit can update widgets directly.
        await run_agent_loop(
            self.session,
            self._model,
            self._api_key,
            max_tool_calls=self._max_tool_calls,
            bash_timeout=self._bash_timeout,
            emit=self._apply_event,
        )

    def _apply_event(self, ev: AgentEvent):
        if ev.kind == "assistant_text":
            self._append_transcript("agent", ev.text)
        elif ev.kind == "tool_started":
            self._append_transcript("tool", f"▸ {ev.tool}")
        elif ev.kind == "tool_result":
            self._append_transcript("tool", self._trim(ev.text))
        elif ev.kind == "error":
            self._append_transcript("error", ev.text)
            self._set_busy(False)
        elif ev.kind == "done":
            self._set_busy(False)

    def _trim(self, text: str) -> str:
        text = text.strip()
        if len(text) > _TOOL_OUTPUT_LIMIT:
            return text[:_TOOL_OUTPUT_LIMIT] + " …"
        return text

    def _set_busy(self, busy: bool):
        self.query_one("#prompt-input", PromptInput).disabled = busy
        self.query_one("#send-btn", Button).disabled = busy
        if not busy:
            self.query_one("#prompt-input", PromptInput).focus()

    def _append_transcript(self, who: str, text: str):
        colors = {"user": "cyan", "agent": "green", "tool": "yellow",
                  "error": "red", "system": "dim"}
        label = {"user": "you", "agent": "agent", "tool": "", "error": "error",
                 "system": ""}[who]
        prefix = f"[{colors[who]}]{label}:[/] " if label else f"[{colors[who]}]"
        suffix = "" if label else "[/]"
        self._log_text += text + "\n"
        self.query_one("#chat-log", RichLog).write(f"{prefix}{text}{suffix}")

    def _do_save(self):
        if not self.session.draft.name.strip():
            self.notify("Ask the agent to set a name, or it can't be saved.",
                        severity="error")
            return
        if not self.session.draft.content.strip():
            self.notify("Nothing to save yet.", severity="error")
            return
        script = self.session.to_script()
        # Preserve the id when editing an existing script.
        if self._existing is not None:
            script.id = self._existing.id
        self._store.save_transcript(script.id, self.session.messages)
        self.session.cleanup()
        self.dismiss(script)
