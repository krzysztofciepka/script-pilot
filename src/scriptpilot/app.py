from textual.app import App


class ScriptPilotApp(App):
    """ScriptPilot TUI application."""

    TITLE = "ScriptPilot"

    def compose(self):
        yield from []


def main():
    app = ScriptPilotApp()
    app.run()
