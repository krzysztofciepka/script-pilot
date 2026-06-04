import httpx
import respx

from scriptpilot.app import ScriptPilotApp
from scriptpilot.screens.chat import ChatScreen, PromptInput
from scriptpilot.storage import ScriptStore

BASE = "https://api.blackbox.ai/v1/chat/completions"


def _assistant(content):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


async def test_clear_command_resets_transcript(tmp_path):
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        screen._append_transcript("user", "something")
        screen._handle_input("/clear")
        await pilot.pause()
        # Only the system message remains in the session.
        assert len(screen.session.messages) == 1
        assert screen.session.messages[0]["role"] == "system"


@respx.mock
async def test_send_message_runs_agent_and_shows_reply(tmp_path):
    respx.post(BASE).mock(return_value=_assistant("Ready to save."))
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        screen._handle_input("make a hello script")
        # Wait for the agent worker to finish.
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Ready to save" in screen._log_text


async def test_prompt_input_is_focused_on_mount(tmp_path):
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        # The multi-line prompt must hold focus so the user can type immediately
        # (regression: the RichLog used to grab focus and swallow keystrokes).
        assert app.focused is screen.query_one("#prompt-input", PromptInput)


@respx.mock
async def test_typing_and_enter_sends_message(tmp_path):
    respx.post(BASE).mock(return_value=_assistant("Got it."))
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("h", "i")
        prompt = screen.query_one("#prompt-input", PromptInput)
        assert prompt.text == "hi"          # keystrokes landed in the input
        await pilot.press("enter")          # Enter submits
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert prompt.text == ""            # input cleared after send
        assert "you:" in screen._log_text or "hi" in screen._log_text
        assert "Got it." in screen._log_text


async def test_shift_enter_inserts_newline(tmp_path):
    store = ScriptStore(path=tmp_path)
    app = ScriptPilotApp()
    async with app.run_test() as pilot:
        screen = ChatScreen(store=store, script=None, model="m", api_key="k",
                            max_tool_calls=25, bash_timeout=10)
        await app.push_screen(screen)
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("shift+enter")
        await pilot.press("b")
        prompt = screen.query_one("#prompt-input", PromptInput)
        assert prompt.text == "a\nb"        # Shift+Enter is a newline, not a send
