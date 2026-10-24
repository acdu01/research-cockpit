"""Config loading/saving. TOML at ~/.research-cockpit/config.toml (override with RC_HOME)."""

from __future__ import annotations

import copy
import json
import os
import tomllib
from pathlib import Path
from typing import Any


def rc_home() -> Path:
    return Path(os.environ.get("RC_HOME", "~/.research-cockpit")).expanduser()


def _defaults() -> dict[str, Any]:
    home = rc_home()
    return {
        "llm": {
            "backend": "claude-cli",  # claude-cli | codex-cli | api
            "fallback_backend": "local",  # local fallback keeps ask/review usable offline
            # passed to the backend (claude --model / codex -m / api body).
            # empty -> claude backends use claude-opus-4-8; codex uses its own.
            "model": "",
            "api_provider": "anthropic",  # anthropic | openai
            "timeout": 180,
        },
        "embeddings": {
            # "hash" selects a dependency-free bag-of-words embedder (tests/offline)
            "model": "BAAI/bge-small-en-v1.5",
        },
        "citations": {
            "source": "openalex",  # openalex -> s2 fallback is automatic
            "s2_api_key": "",
            "mailto": "",  # optional: gets you into OpenAlex's polite pool
        },
        "store": {"path": str(home / "rc.db")},
        "rag": {
            "top_k": 8, "chunk_tokens": 512, "chunk_overlap": 64,
            "retrieval": "dense", "rerank": False,
        },
        "ui": {"host": "127.0.0.1", "port": 8501},
    }


class Config:
    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or rc_home() / "config.toml"
        data = _defaults()
        if path.exists():
            with open(path, "rb") as f:
                user = tomllib.load(f)
            for section, values in user.items():
                if isinstance(values, dict):
                    data.setdefault(section, {}).update(values)
                else:
                    data[section] = values
        return cls(data, path)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        # coerce to the existing value's type where sensible
        old = node.get(parts[-1])
        if isinstance(old, bool):
            value = str(value).lower() in ("1", "true", "yes")
        elif isinstance(old, int):
            value = int(value)
        node[parts[-1]] = value

    def get_bool(self, dotted: str, default: bool = False) -> bool:
        """Accept TOML booleans and string values saved by older CLI versions."""
        value = self.get(dotted, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_dump_toml(self.data))

    @property
    def store_path(self) -> Path:
        return Path(self.get("store.path")).expanduser()

    @property
    def ui_host(self) -> str:
        # Hard localhost-only rule: never honor a non-loopback host.
        host = str(self.get("ui.host", "127.0.0.1"))
        return host if host in ("127.0.0.1", "localhost", "::1") else "127.0.0.1"


def _dump_toml(data: dict[str, Any]) -> str:
    """Minimal TOML writer for our flat {section: {key: scalar}} config shape."""
    lines: list[str] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, val in values.items():
            lines.append(f"{key} = {_toml_value(val)}")
        lines.append("")
    return "\n".join(lines)


def _toml_value(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    # JSON basic-string escapes also form valid TOML string escapes.
    return json.dumps(str(val), ensure_ascii=False)


def deep_copy_defaults() -> dict[str, Any]:
    return copy.deepcopy(_defaults())
