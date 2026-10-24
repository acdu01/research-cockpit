"""Pluggable LLM adapter: claude-cli | codex-cli | api.

Generation only - embeddings are never routed here (always local).
API keys come from the environment (LLM_API_KEY, or the provider's usual
variable); they are never written to config or logged.
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
from typing import Protocol, runtime_checkable

import httpx

# Generation quality tracks the model more than anything else, so the Claude
# backends pin a strong default instead of inheriting whatever the CLI/session
# happens to be set to. Override with `rc config set llm.model <id>`.
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"
DEFAULT_ANTHROPIC_MODEL = DEFAULT_CLAUDE_MODEL
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does", "for",
    "from", "how", "if", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "this", "to", "what", "when", "where", "which",
    "who", "why", "with", "your",
}


class LLMError(RuntimeError):
    pass


_CLI_ERROR_MARKERS = (
    "please run /login",
    "api error:",
    "authentication_error",
    "oauth token has expired",
    "security token included in the request is expired",
    "invalid api key",
)


@runtime_checkable
class LLMAdapter(Protocol):
    def generate(self, prompt: str, system: str | None = None) -> str: ...


def _compose(prompt: str, system: str | None) -> str:
    return f"{system.strip()}\n\n---\n\n{prompt}" if system else prompt


class _CLIAdapter:
    """Shared subprocess plumbing for CLI-backed adapters."""

    name = "cli"

    def __init__(self, timeout: float = 180.0, model: str = ""):
        self.timeout = timeout
        self.model = model

    def _argv(self, prompt: str) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def generate(self, prompt: str, system: str | None = None) -> str:
        argv = self._argv(_compose(prompt, system))
        if shutil.which(argv[0]) is None:
            raise LLMError(
                f"'{argv[0]}' CLI not found on PATH. Install it or switch backends"
                " with: rc config set llm.backend api"
            )
        try:
            # stdin must be detached: `claude -p` treats piped stdin as prompt
            # input and would otherwise drain the caller's stdin (e.g. during
            # an interactive `rc review` session).
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"{argv[0]} timed out after {self.timeout:.0f}s") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:500]
            raise LLMError(f"{argv[0]} exited {proc.returncode}: {detail}")
        text = proc.stdout.strip()
        if not text:
            raise LLMError(f"{argv[0]} produced no output")
        # Some CLIs exit 0 but print an auth/API error instead of an answer
        # (e.g. `claude` with an expired token: "Please run /login · API Error:
        # 403 ..."). Treat that as a failure so the fallback engages; the length
        # guard keeps real answers that merely mention these phrases safe.
        lowered = text.lower()
        if len(text) < 400 and any(marker in lowered for marker in _CLI_ERROR_MARKERS):
            raise LLMError(f"{argv[0]} returned an error instead of an answer:"
                           f" {text[:200]}")
        return text


class ClaudeCLIAdapter(_CLIAdapter):
    name = "claude-cli"

    def __init__(self, timeout: float = 180.0, model: str = ""):
        super().__init__(timeout=timeout, model=model or DEFAULT_CLAUDE_MODEL)

    def _argv(self, prompt: str) -> list[str]:
        return ["claude", "-p", "--model", self.model, prompt]


class CodexCLIAdapter(_CLIAdapter):
    name = "codex-cli"

    def _argv(self, prompt: str) -> list[str]:
        # no pinned default: codex model ids churn; empty means the CLI's own
        argv = ["codex", "exec"]
        if self.model:
            argv += ["-m", self.model]
        return argv + [prompt]


class APIAdapter:
    """Direct HTTP to Anthropic or OpenAI using LLM_API_KEY from the env."""

    name = "api"

    def __init__(self, provider: str = "anthropic", model: str = "", timeout: float = 180.0):
        self.provider = provider
        self.model = model or (
            DEFAULT_ANTHROPIC_MODEL if provider == "anthropic" else DEFAULT_OPENAI_MODEL
        )
        self.timeout = timeout

    def _api_key(self) -> str:
        fallback = "ANTHROPIC_API_KEY" if self.provider == "anthropic" else "OPENAI_API_KEY"
        key = os.environ.get("LLM_API_KEY") or os.environ.get(fallback)
        if not key:
            raise LLMError(f"Set LLM_API_KEY (or {fallback}) to use the api backend")
        return key

    def generate(self, prompt: str, system: str | None = None) -> str:
        key = self._api_key()
        try:
            if self.provider == "anthropic":
                return self._anthropic(key, prompt, system)
            return self._openai(key, prompt, system)
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"{self.provider} API error {exc.response.status_code}:"
                f" {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.provider} API request failed: {exc}") from exc

    def _anthropic(self, key: str, prompt: str, system: str | None) -> str:
        body: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text.strip():
            raise LLMError("Anthropic API returned an empty response")
        return text.strip()

    def _openai(self, key: str, prompt: str, system: str | None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": self.model, "messages": messages},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        if not text.strip():
            raise LLMError("OpenAI API returned an empty response")
        return text.strip()


def _words(text: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in STOPWORDS
    ]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _clip(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _parse_passages(prompt: str) -> tuple[list[dict[str, str | int]], str]:
    pattern = re.compile(
        r"\[(\d+)\] \((.*?)\)\n(.*?)"
        r"(?=\n\n\[\d+\] \(|\n\n(?:Question|Topic to audit for coverage gaps):|\Z)",
        re.S,
    )
    passages = [
        {"n": int(match.group(1)), "title": match.group(2), "text": match.group(3).strip()}
        for match in pattern.finditer(prompt)
    ]
    query_match = re.search(
        r"\n\n(?:Question|Topic to audit for coverage gaps): (.*)\Z", prompt, re.S
    )
    return passages, query_match.group(1).strip() if query_match else ""


def _best_sentences(
    passages: list[dict[str, str | int]], query: str, limit: int
) -> list[tuple[int, str]]:
    query_terms = set(_words(query))
    ranked: list[tuple[float, int, str]] = []
    positive_overlap = False
    for index, passage in enumerate(passages):
        text = str(passage["text"])
        candidates = _sentences(text) or [_clip(text)]
        for sentence in candidates[:6]:
            sentence_terms = set(_words(sentence))
            overlap = len(query_terms & sentence_terms)
            positive_overlap = positive_overlap or overlap > 0
            score = overlap * 5 + len(sentence_terms) / 1000 - index / 100
            ranked.append((score, int(passage["n"]), sentence))
    if passages and not positive_overlap:
        return [
            (int(passage["n"]),
             _clip((_sentences(str(passage["text"])) or [str(passage["text"])])[0]))
            for passage in passages[:limit]
        ]
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen: list[tuple[int, str]] = []
    seen = set()
    for _, n, sentence in ranked:
        key = (n, sentence)
        if key in seen:
            continue
        seen.add(key)
        chosen.append((n, _clip(sentence)))
        if len(chosen) >= limit:
            break
    return chosen


class LocalAdapter:
    """Local heuristic fallback for RAG answers and flashcards."""

    name = "local"

    def generate(self, prompt: str, system: str | None = None) -> str:
        system_text = (system or "").lower()
        if "json array" in system_text and "flashcards" in system_text:
            return self._flashcards(prompt)
        if "json array" in system_text and "tag" in system_text:
            return self._tags(prompt)
        if "json array" in system_text and "annotations" in system_text:
            return self._annotations(prompt)
        if "coverage auditor" in system_text:
            return self._gaps(prompt)
        if "synthesize across the sources" in system_text:
            return self._synthesize(prompt)
        return self._answer(prompt)

    def _tags(self, prompt: str) -> str:
        excerpt_match = re.search(r"Excerpts:\n\n(.*)\Z", prompt, re.S)
        text = excerpt_match.group(1) if excerpt_match else prompt
        counts = collections.Counter(_words(text))
        return json.dumps([word for word, _ in counts.most_common(4)])

    def _annotations(self, prompt: str) -> str:
        excerpt_match = re.search(r"Excerpts:\n\n(.*)\Z", prompt, re.S)
        text = excerpt_match.group(1) if excerpt_match else prompt
        text = re.sub(r"\[p\.\d+\] ", "", text)
        return json.dumps(
            [{"text": _clip(sentence, limit=220)} for sentence in _sentences(text)[:4]]
        )

    def _answer(self, prompt: str) -> str:
        passages, query = _parse_passages(prompt)
        if not passages:
            return "No supporting passages were provided."
        snippets = _best_sentences(passages, query, limit=3)
        body = " ".join(f"{sentence} [{n}]" for n, sentence in snippets)
        return f"Based on the retrieved passages, {body}"

    def _synthesize(self, prompt: str) -> str:
        passages, query = _parse_passages(prompt)
        if not passages:
            return "No supporting passages were provided."
        snippets = _best_sentences(passages, query, limit=3)
        overview = " ".join(f"{sentence} [{n}]" for n, sentence in snippets)
        return (
            "Across the retrieved sources, the main themes are: "
            + overview
            + "\n\nContradictions: none identified in the retrieved passages."
        )

    def _gaps(self, prompt: str) -> str:
        passages, query = _parse_passages(prompt)
        coverage_terms = collections.Counter(
            word for passage in passages for word in _words(str(passage["text"]))
        )
        top_terms = ", ".join(word for word, _ in coverage_terms.most_common(4))
        coverage = top_terms or query or "the retrieved topic"
        covered_by = "".join(f"[{passage['n']}]" for passage in passages[:2])
        candidates_match = re.search(
            r"Citation-graph gap candidates .*?:\n(.*?)"
            r"(?=\n\n(?:Question|Topic to audit for coverage gaps):|\Z)",
            prompt,
            re.S,
        )
        candidates = []
        if candidates_match:
            candidates = [
                line[2:].strip()
                for line in candidates_match.group(1).splitlines()
                if line.startswith("- ")
            ]
        answer = (
            f"The retrieved passages mainly cover {coverage} {covered_by}.\n\n"
            "Likely gaps are alternative methods, broader evaluation settings, and "
            "counter-arguments that do not appear in the retrieved excerpts."
        )
        if candidates:
            answer += "\nPossible papers to add: " + "; ".join(candidates[:3]) + "."
        return answer

    def _flashcards(self, prompt: str) -> str:
        title_match = re.search(r"Paper: (.+)", prompt)
        title = title_match.group(1).strip() if title_match else "this paper"
        section_match = re.search(r"User's .*?:\n\n(.*)\Z", prompt, re.S)
        source_text = section_match.group(1).strip() if section_match else ""
        items = [line[2:].strip() for line in source_text.splitlines() if line.startswith("- ")]
        if not items:
            items = _sentences(source_text)
        cards = []
        for item in items[:5]:
            phrase = " ".join(item.rstrip(".").split()[:6]) or title
            cards.append(
                {
                    "question": f'What should you recall from {title} about "{phrase}"?',
                    "answer": _clip(item, limit=220),
                }
            )
        return json.dumps(cards)


class FallbackAdapter:
    name = "fallback"

    def __init__(self, primary: LLMAdapter, fallback: LLMAdapter):
        self.primary = primary
        self.fallback = fallback
        # After each generate(): which backend answered, and the primary's
        # error when the fallback did. Callers surface this - a silently
        # degraded answer looks like a bad model, not a broken backend.
        self.last_backend: str | None = None
        self.last_error: str | None = None

    def generate(self, prompt: str, system: str | None = None) -> str:
        try:
            text = self.primary.generate(prompt, system=system)
            self.last_backend = getattr(self.primary, "name", "primary")
            self.last_error = None
            return text
        except LLMError as primary_exc:
            try:
                text = self.fallback.generate(prompt, system=system)
                self.last_backend = getattr(self.fallback, "name", "fallback")
                self.last_error = str(primary_exc)
                return text
            except LLMError as fallback_exc:
                primary_name = getattr(self.primary, "name", "primary")
                fallback_name = getattr(self.fallback, "name", "fallback")
                raise LLMError(
                    f"{primary_name} failed: {primary_exc}; "
                    f"{fallback_name} also failed: {fallback_exc}"
                ) from fallback_exc


def degraded_notice(adapter: LLMAdapter) -> str | None:
    """Warning text when the last generation fell back; None when healthy."""
    error = getattr(adapter, "last_error", None)
    if not error:
        return None
    backend = getattr(adapter, "last_backend", "fallback")
    primary = getattr(getattr(adapter, "primary", None), "name", "primary")
    return (
        f"Answer produced by the '{backend}' fallback because '{primary}'"
        f" failed: {error}"
    )


def _make_adapter(backend: str, config) -> LLMAdapter:
    timeout = float(config.get("llm.timeout", 180))
    model = str(config.get("llm.model", "") or "")
    if backend == "claude-cli":
        return ClaudeCLIAdapter(timeout=timeout, model=model)
    if backend == "codex-cli":
        return CodexCLIAdapter(timeout=timeout, model=model)
    if backend == "api":
        return APIAdapter(
            provider=config.get("llm.api_provider", "anthropic"),
            model=config.get("llm.model", ""),
            timeout=timeout,
        )
    if backend == "local":
        return LocalAdapter()
    raise LLMError(f"Unknown llm.backend '{backend}' (use claude-cli | codex-cli | api | local)")


def get_adapter(config) -> LLMAdapter:
    backend = config.get("llm.backend", "claude-cli")
    primary = _make_adapter(backend, config)
    fallback_backend = config.get("llm.fallback_backend", "")
    if fallback_backend and fallback_backend != backend:
        return FallbackAdapter(primary, _make_adapter(fallback_backend, config))
    return primary


def extract_json_array(text: str) -> list:
    """Pull the first JSON array out of model output (tolerates fences/chrome)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[", text):
        try:
            parsed, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return []
