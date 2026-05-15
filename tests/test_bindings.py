from scriptpilot.app import ScriptPilotApp
from scriptpilot.screens.main import MainScreen


def test_no_binding_conflicts_between_app_and_main_screen():
    """MainScreen bindings must not shadow App-level bindings."""
    app_keys = {b[0] for b in ScriptPilotApp.BINDINGS}
    main_keys = {b[0] for b in MainScreen.BINDINGS}
    overlap = app_keys & main_keys
    assert not overlap, f"Conflicting keys: {overlap}"
