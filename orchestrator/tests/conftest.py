import json
import re
import socket
from pathlib import Path

import pytest

from orchestrator.llm import LLMClient, Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "claim-triage"


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def isolate(monkeypatch):
    """No real LLM settings, no .env, and no network except loopback (the judge's own API).

    LLM_MODEL stays unset on purpose: that is a fresh clone, so the offline tests also prove the
    committed cache answers every prompt from a single model.

    Module-scoped fixtures run before the autouse fixture below, so they must call this themselves.
    """
    for name in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FLUXORA_NO_DOTENV", "1")

    real_create_connection, real_connect = socket.create_connection, socket.socket.connect

    def create_connection(address, *args, **kwargs):
        if address[0] not in LOOPBACK:
            raise RuntimeError(f"tests must not open network connections (tried {address[0]})")
        return real_create_connection(address, *args, **kwargs)

    def connect(self, address):
        if isinstance(address, tuple) and address[0] not in LOOPBACK:
            raise RuntimeError(f"tests must not open network connections (tried {address[0]})")
        return real_connect(self, address)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    isolate(monkeypatch)


class FakeTransport:
    """Stands in for a live provider: answers every rule prompt with valid JSON."""

    def __init__(self):
        self.calls = 0

    def __call__(self, settings, system, prompt):
        self.calls += 1
        rule_id = re.search(r"^Rule: (R\d+)", prompt, re.M).group(1)
        if "Write the BODY of the method" in prompt:
            return f"return default; // {rule_id}", settings.model
        return json.dumps({"rule": f"Plain-English sentence for {rule_id}.", "confidence": "high"}), settings.model


@pytest.fixture
def fake_transport():
    return FakeTransport()


@pytest.fixture
def live_client(tmp_path, fake_transport):
    """A 'live' client whose provider is the fake transport and whose cache is a temp folder."""
    settings = Settings(provider="anthropic", api_key="test-key", model="fake-model", base_url=None, offline=False)
    return LLMClient(settings, cache_dir=tmp_path / "cache", transport=fake_transport, log=lambda _: None)
