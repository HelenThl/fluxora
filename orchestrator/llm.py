"""Thin LLM client with a committed, content-addressed response cache.

Provider, key and model come from LLM_PROVIDER ("anthropic" or "openai"), LLM_API_KEY and LLM_MODEL.
LLM_BASE_URL optionally points the "openai" provider at any OpenAI-compatible endpoint.

Every response is stored in orchestrator/cache/<sha256>.json. The cache is committed, so the demo
runs offline. The cache is always checked first; a live call happens only on a miss with a key set.
Keys and prompts are never logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CACHE_DIR = Path(__file__).resolve().parent / "cache"
PROVIDERS = ("anthropic", "openai")
MAX_TOKENS = 16000
OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"

# Server-side refusal fallback is enabled by default for these Claude models.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """A live call failed or returned something unusable."""


class CacheMiss(LLMError):
    """Offline mode and no cached response for this prompt."""


@dataclass(frozen=True)
class Settings:
    provider: str | None
    api_key: str | None
    model: str | None
    base_url: str | None
    offline: bool


def get_settings(offline: bool = False) -> Settings:
    """Read the LLM settings from the environment. No key means offline."""

    def env(name: str) -> str | None:
        value = os.environ.get(name, "").strip()
        return value or None

    api_key = env("LLM_API_KEY")
    return Settings(
        provider=(env("LLM_PROVIDER") or "").lower() or None,
        api_key=api_key,
        model=env("LLM_MODEL"),
        base_url=env("LLM_BASE_URL"),
        offline=offline or api_key is None,
    )


def cache_key(model: str, system: str, prompt: str) -> str:
    return _sha256([model, system, prompt])


def prompt_digest(system: str, prompt: str) -> str:
    return _sha256([system, prompt])


def _sha256(parts: list[str]) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


# A transport takes (settings, system, prompt) and returns (text, model that answered).
Transport = Callable[[Settings, str, str], "tuple[str, str]"]


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        cache_dir: Path = CACHE_DIR,
        transport: Transport | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache_dir = cache_dir
        self._transport = transport
        self.log = log
        self.live_calls = 0
        self.cache_hits = 0

    @property
    def mode(self) -> str:
        return "offline (cache only)" if self.settings.offline else "live (cache first)"

    def complete(self, prompt: str, system: str = "") -> dict:
        """Return the cache entry for this prompt, calling the provider only on a miss."""
        entry = self._lookup(system, prompt)
        if entry is not None:
            self.cache_hits += 1
            self.log(f"  llm: cache hit {entry['key'][:12]}")
            return entry

        s = self.settings
        if s.offline:
            model = s.model or "any model"
            entries = self._entries()
            cached = sorted({e.get("model") for e in entries if e.get("model")})
            others = [m for m in cached if m != s.model]
            if s.model and s.model in cached and others:
                # A .env left on a model that is only partly cached. Its cached answers also change later
                # prompts (generate quotes the extracted sentences), so no model may hold this one.
                hint = (
                    f"LLM_MODEL is set to {s.model!r} (check .env), which is only partly cached. The cache also holds "
                    f"answers from {', '.join(others)}. For an offline run, unset LLM_MODEL or set LLM_MODEL={others[0]}."
                )
            elif s.model and cached and s.model not in cached:
                hint = (
                    f"LLM_MODEL is set to {s.model!r}, but this run is offline and the cache only holds answers from "
                    f"{', '.join(cached)}. For an offline run, unset LLM_MODEL (check .env) or set it to one of those; "
                    "for live calls, set LLM_API_KEY too."
                )
            else:
                hint = "Warm the cache by running once with LLM_PROVIDER, LLM_API_KEY and LLM_MODEL set."
            raise CacheMiss(f"No cached response for this prompt ({model}, prompt {prompt_digest(system, prompt)[:12]}). {hint}")
        if s.provider not in PROVIDERS:
            raise LLMError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}; got {s.provider!r}.")
        if not s.model:
            raise LLMError("LLM_MODEL is not set.")

        transport = self._transport or (_anthropic if s.provider == "anthropic" else _openai_compatible)
        text, served_by = transport(s, system, prompt)
        key = cache_key(s.model, system, prompt)
        entry = {
            "key": key,
            "provider": s.provider,
            "model": s.model,
            "served_by": served_by,
            "prompt_sha256": prompt_digest(system, prompt),
            "system": system,
            "prompt": prompt,
            "response": text,
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        self.live_calls += 1
        self.log(f"  llm: live call ({s.provider}, {s.model}) -> cached {key[:12]}")
        return entry

    def _lookup(self, system: str, prompt: str) -> dict | None:
        if self.settings.model:
            path = self.cache_dir / f"{cache_key(self.settings.model, system, prompt)}.json"
            return _read(path) if path.is_file() else None

        # No model configured (e.g. a fresh clone running offline): match on the prompt alone.
        digest = prompt_digest(system, prompt)
        matches = [e for e in self._entries() if e.get("prompt_sha256") == digest]
        models = sorted({e["model"] for e in matches})
        if len(models) > 1:
            raise LLMError(f"The cache holds answers from several models ({', '.join(models)}). Set LLM_MODEL to pick one.")
        return matches[0] if matches else None

    def _entries(self) -> list[dict]:
        if not self.cache_dir.is_dir():
            return []
        return [_read(p) for p in sorted(self.cache_dir.glob("*.json"))]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _anthropic(s: Settings, system: str, prompt: str) -> tuple[str, str]:
    import anthropic

    client = anthropic.Anthropic(api_key=s.api_key)
    kwargs: dict = {
        "model": s.model,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    try:
        if s.model in FALLBACK_MODELS:
            response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic rejected LLM_API_KEY (401).") from None
    except anthropic.PermissionDeniedError:
        raise LLMError("The Anthropic API key lacks permission for this request (403).") from None
    except anthropic.NotFoundError:
        raise LLMError(f"Anthropic does not know model {s.model!r} (404). Check LLM_MODEL.") from None
    except anthropic.RateLimitError:
        raise LLMError("Rate limited by Anthropic (429), even after retries. Try again shortly.") from None
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise LLMError("Could not reach the Anthropic API.") from None

    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request (stop_reason=refusal).")
    if response.stop_reason == "max_tokens":
        raise LLMError(f"The reply hit max_tokens={MAX_TOKENS} before finishing.")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return text, response.model


def _openai_compatible(s: Settings, system: str, prompt: str) -> tuple[str, str]:
    base = (s.base_url or OPENAI_DEFAULT_BASE).rstrip("/")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": s.model, "messages": messages}).encode("utf-8"),
        headers={"Authorization": f"Bearer {s.api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read(400).decode("utf-8", "replace")
        raise LLMError(f"{base} returned HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"Could not reach {base}: {e.reason}") from None

    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise LLMError("The reply was cut off by the endpoint's length limit.")
    return (choice["message"].get("content") or "").strip(), data.get("model", s.model)
