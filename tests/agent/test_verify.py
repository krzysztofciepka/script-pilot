import shutil
from pathlib import Path

import pytest

from scriptpilot.agent.verify import find_missing_references, verify_draft


def test_find_missing_references_flags_node_call_to_absent_file(tmp_path):
    content = "node /app/cloud-build-trigger.js\n"
    missing = find_missing_references("js", content, tmp_path)
    assert "/app/cloud-build-trigger.js" in missing


def test_find_missing_references_ignores_existing_sibling(tmp_path):
    (tmp_path / "helper.js").write_text("console.log(1)")
    content = "node helper.js\n"
    missing = find_missing_references("js", content, tmp_path)
    assert missing == []


def test_verify_draft_bash_syntax_error_fails(tmp_path):
    p = tmp_path / "script.sh"
    p.write_text("if then fi\n")  # invalid bash
    result = verify_draft("bash", p)
    assert not result.ok
    assert any(l.name == "syntax" and not l.passed for l in result.layers)


def test_verify_draft_valid_bash_passes(tmp_path):
    p = tmp_path / "script.sh"
    p.write_text("echo hello\n")
    result = verify_draft("bash", p)
    assert result.ok


def test_verify_draft_python_syntax_error_fails(tmp_path):
    p = tmp_path / "script.py"
    p.write_text("def (:\n")
    result = verify_draft("python", p)
    assert not result.ok


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_verify_draft_js_missing_reference_fails(tmp_path):
    p = tmp_path / "script.js"
    # Syntactically valid JS, but shells out to a file that does not exist.
    p.write_text("const x = 1;\n// node /app/cloud-build-trigger.js\n")
    result = verify_draft("js", p)
    assert not result.ok
    assert any(l.name == "resolve" and not l.passed for l in result.layers)


def test_verify_draft_safe_run_executes(tmp_path):
    p = tmp_path / "script.sh"
    p.write_text('echo "ran with $1"\n')
    result = verify_draft("bash", p, safe_run=["--help"])
    assert result.ok
    assert any(l.name == "run" for l in result.layers)
