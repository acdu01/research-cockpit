from __future__ import annotations

import pytest

from research_cockpit.config import Config


def test_defaults_when_no_file(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert cfg.get("llm.backend") == "claude-cli"
    assert cfg.get("llm.fallback_backend") == "local"
    assert cfg.get("embeddings.model") == "BAAI/bge-small-en-v1.5"
    assert cfg.get("ui.host") == "127.0.0.1"


def test_set_save_reload(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config.load(path)
    cfg.set("llm.backend", "api")
    cfg.set("ui.port", "9000")
    cfg.save()
    reloaded = Config.load(path)
    assert reloaded.get("llm.backend") == "api"
    assert reloaded.get("ui.port") == 9000  # int coerced
    # user file merges over defaults without losing other sections
    assert reloaded.get("embeddings.model") == "BAAI/bge-small-en-v1.5"


def test_ui_host_is_forced_to_loopback(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config.load(path)
    cfg.set("ui.host", "0.0.0.0")
    cfg.save()
    assert Config.load(path).ui_host == "127.0.0.1"


def test_unknown_key_returns_default(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert cfg.get("nope.nothing", "fallback") == "fallback"


def test_config_strings_round_trip_control_characters(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    value = 'line one\nline two\t"quoted"\\path'
    cfg.set("llm.model", value)
    cfg.save()
    assert Config.load(cfg.path).get("llm.model") == value


@pytest.mark.parametrize("value, expected", [
    (True, True), (False, False), ("true", True), ("false", False), ("1", True),
])
def test_rerank_accepts_legacy_string_booleans(tmp_path, value, expected):
    cfg = Config.load(tmp_path / "config.toml")
    cfg.data["rag"]["rerank"] = value
    assert cfg.get_bool("rag.rerank") is expected
