import shutil
import socket

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app

pytestmark = pytest.mark.skipif(shutil.which("dotnet") is None, reason="needs the .NET 8 SDK")


def test_doctor_says_ready_on_a_healthy_machine():
    result = CliRunner().invoke(app, ["doctor", "--port", "5091"])
    assert result.exit_code == 0, result.output
    for check in ("Python 3.11+", ".NET 8 SDK", "Cache covers the demo", "Recorded repair patch", "Reference cases unchanged"):
        line = next(l for l in result.output.splitlines() if check in l)
        assert line.startswith("OK"), line
    assert "READY" in result.output


def test_doctor_fails_on_a_busy_judge_port():
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        result = CliRunner().invoke(app, ["doctor", "--port", str(port)])
    assert result.exit_code == 1
    assert next(l for l in result.output.splitlines() if f"Port {port} free" in l).startswith("FAIL")
    assert "--port" in result.output


def test_doctor_catches_llm_model_without_a_key(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "some-other-model")
    result = CliRunner().invoke(app, ["doctor", "--port", "5091"])
    assert result.exit_code == 1
    assert "Unset LLM_MODEL" in result.output and "NOT READY" in result.output


def test_doctor_warns_when_a_live_key_is_set(monkeypatch):
    # A live key in .env means `fluxora demo` would call the API on a miss: not an offline stage.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "partly-cached-model")
    result = CliRunner().invoke(app, ["doctor", "--port", "5091"])
    assert next(l for l in result.output.splitlines() if "LLM mode" in l).startswith("WARN")
    assert "--offline" in result.output
