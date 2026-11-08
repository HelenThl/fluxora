import json
import re
import socket
from pathlib import Path

import pytest

from orchestrator.llm import LLMClient, Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "claim-triage"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No real LLM settings, no .env, and no network in any test."""
    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FLUXORA_NO_DOTENV", "1")

    def blocked(*args, **kwargs):
        raise RuntimeError("tests must not open network connections")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


class FakeTransport:
    """Stands in for a live provider: answers every rule prompt with valid JSON."""

    def __init__(self):
        self.calls = 0

    def __call__(self, settings, system, prompt):
        self.calls += 1
        rule_id = re.search(r"^Rule: (R\d+)", prompt, re.M).group(1)
        return json.dumps({"rule": f"Plain-English sentence for {rule_id}.", "confidence": "high"}), settings.model


@pytest.fixture
def fake_transport():
    return FakeTransport()


@pytest.fixture
def live_client(tmp_path, fake_transport):
    """A 'live' client whose provider is the fake transport and whose cache is a temp folder."""
    settings = Settings(provider="anthropic", api_key="test-key", model="fake-model", base_url=None, offline=False)
    return LLMClient(settings, cache_dir=tmp_path / "cache", transport=fake_transport, log=lambda _: None)
