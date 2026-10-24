from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from research_cockpit.config import Config
from research_cockpit.llm import (
    APIAdapter,
    ClaudeCLIAdapter,
    CodexCLIAdapter,
    FallbackAdapter,
    LLMError,
    LocalAdapter,
    extract_json_array,
    get_adapter,
)


def _config(tmp_path, **llm):
    cfg = Config.load(tmp_path / "config.toml")
    for key, val in llm.items():
        cfg.set(f"llm.{key}", val)
    return cfg


def test_get_adapter_selection(tmp_path):
    default = get_adapter(_config(tmp_path))
    assert isinstance(default, FallbackAdapter)
    assert isinstance(default.primary, ClaudeCLIAdapter)
    assert isinstance(default.fallback, LocalAdapter)
    codex = get_adapter(_config(tmp_path, backend="codex-cli"))
    assert isinstance(codex, FallbackAdapter)
    assert isinstance(codex.primary, CodexCLIAdapter)
    api = get_adapter(_config(tmp_path, backend="api", api_provider="openai"))
    assert isinstance(api, FallbackAdapter)
    assert isinstance(api.primary, APIAdapter) and api.primary.provider == "openai"
    with pytest.raises(LLMError):
        get_adapter(_config(tmp_path, backend="wat"))


def test_cli_adapter_composes_system_prompt():
    adapter = ClaudeCLIAdapter()
    with mock.patch("shutil.which", return_value="/usr/bin/claude"), \
         mock.patch("subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
        out = adapter.generate("question", system="be terse")
        assert out == "ok"
        argv = run.call_args[0][0]
        assert argv[:2] == ["claude", "-p"]
        assert "be terse" in argv[-1] and "question" in argv[-1]


def test_claude_cli_pins_opus_by_default_and_honors_config(tmp_path):
    default = ClaudeCLIAdapter()
    assert default._argv("q")[2:4] == ["--model", "claude-opus-4-8"]
    adapter = get_adapter(_config(tmp_path, model="claude-sonnet-5")).primary
    assert adapter._argv("q")[2:4] == ["--model", "claude-sonnet-5"]


def test_codex_cli_model_flag_only_when_set(tmp_path):
    assert CodexCLIAdapter()._argv("q") == ["codex", "exec", "q"]
    adapter = get_adapter(
        _config(tmp_path, backend="codex-cli", model="gpt-5.4-codex")
    ).primary
    assert adapter._argv("q") == ["codex", "exec", "-m", "gpt-5.4-codex", "q"]


def test_cli_adapter_detects_exit_zero_auth_errors():
    """`claude` with an expired token exits 0 but prints an error - that must
    raise (so the fallback engages) instead of being returned as an answer."""
    adapter = ClaudeCLIAdapter()
    for output in (
        "Please run /login",
        "API Error: 403 The security token included in the request is expired",
        "OAuth token has expired · Please run /login",
    ):
        with mock.patch("shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=output,
                                                           stderr="")
            with pytest.raises(LLMError, match="error instead of an answer"):
                adapter.generate("hi")
    # a long real answer that merely mentions such phrases is NOT an error
    answer = "The paper discusses API error handling. " * 20
    with mock.patch("shutil.which", return_value="/usr/bin/claude"), \
         mock.patch("subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout=answer, stderr="")
        assert adapter.generate("hi") == answer.strip()


def test_cli_adapter_missing_binary():
    adapter = ClaudeCLIAdapter()
    with mock.patch("shutil.which", return_value=None), pytest.raises(LLMError):
        adapter.generate("hi")


def test_cli_adapter_nonzero_exit():
    adapter = CodexCLIAdapter()
    with mock.patch("shutil.which", return_value="/usr/bin/codex"), \
         mock.patch("subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 2, stdout="", stderr="boom")
        with pytest.raises(LLMError, match="boom"):
            adapter.generate("hi")


def test_api_adapter_requires_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        APIAdapter().generate("hi")


def test_extract_json_array():
    assert extract_json_array('junk before [{"q": 1}] junk after') == [{"q": 1}]
    assert extract_json_array("no json here") == []
    assert extract_json_array('[1, [2, 3]] trailing') == [1, [2, 3]]
    fenced = '```json\n[{"question": "q", "answer": "a"}]\n```'
    assert extract_json_array(fenced)[0]["question"] == "q"
    assert extract_json_array('prefix [{"text": "a ] bracket [ in a quote"}] suffix') == [
        {"text": "a ] bracket [ in a quote"}
    ]


def test_fallback_adapter_uses_local_when_primary_fails(tmp_path):
    adapter = get_adapter(_config(tmp_path, backend="codex-cli"))
    with mock.patch("shutil.which", return_value="/usr/bin/codex"), \
         mock.patch("subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="nope")
        out = adapter.generate(
            "Context passages:\n\n[1] (Paper)\nWorld models predict actions."
            "\n\nQuestion: what is the claim?"
        )
    assert "Based on the retrieved passages" in out
    assert "[1]" in out


def test_degraded_notice_reports_fallback_use(tmp_path):
    from research_cockpit.llm import degraded_notice

    adapter = get_adapter(_config(tmp_path, backend="codex-cli"))
    assert degraded_notice(adapter) is None
    with mock.patch("shutil.which", return_value="/usr/bin/codex"), \
         mock.patch("subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="nope")
        adapter.generate("Context passages:\n\n[1] (P)\nSome text.\n\nQuestion: q?")
    notice = degraded_notice(adapter)
    assert notice and "local" in notice and "codex-cli" in notice and "nope" in notice
    # a healthy generation clears it
    with mock.patch("shutil.which", return_value="/usr/bin/codex"), \
         mock.patch("subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="fine", stderr="")
        adapter.generate("hi")
    assert degraded_notice(adapter) is None


def test_local_adapter_flashcards_return_json_array():
    raw = LocalAdapter().generate(
        "Paper: P\n\nUser's annotations:\n\n- Caching yields a 2x speedup.",
        system="You write concise flashcards. Respond with ONLY a JSON array"
               " of objects with keys question and answer.",
    )
    parsed = extract_json_array(raw)
    assert parsed and parsed[0]["question"] and parsed[0]["answer"]
