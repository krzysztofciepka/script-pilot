from scriptpilot.agent.prompts import system_prompt


def test_system_prompt_mentions_tools_and_behaviors():
    p = system_prompt().lower()
    for token in ("bash", "update_script", "verify", "clarify", "script.sh"):
        assert token in p
