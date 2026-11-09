import json

import pytest

from orchestrator.llm import CacheMiss, LLMClient, LLMError, Settings, cache_key, get_settings


def settings(**overrides):
    base = dict(provider="anthropic", api_key="test-key", model="fake-model", base_url=None, offline=False)
    return Settings(**{**base, **overrides})


def test_no_key_means_offline(monkeypatch):
    assert get_settings().offline is True
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    assert get_settings().offline is False
    assert get_settings(offline=True).offline is True


def test_cache_key_depends_on_model_and_prompt():
    assert cache_key("m", "", "p") == cache_key("m", "", "p")
    assert cache_key("m", "", "p") != cache_key("other", "", "p")
    assert cache_key("m", "", "p") != cache_key("m", "", "p2")


def test_offline_miss_raises_a_clear_error(tmp_path):
    client = LLMClient(settings(offline=True), cache_dir=tmp_path, log=lambda _: None)
    with pytest.raises(CacheMiss, match="Warm the cache"):
        client.complete("a prompt nobody has cached")


def test_offline_miss_names_the_model_mismatch(tmp_path, fake_transport):
    LLMClient(settings(), cache_dir=tmp_path, transport=fake_transport, log=lambda _: None).complete("Rule: R01\nx")
    offline = LLMClient(settings(model="another-model", api_key=None, offline=True), cache_dir=tmp_path, log=lambda _: None)
    with pytest.raises(CacheMiss, match=r"LLM_MODEL is set to 'another-model'.*fake-model.*unset LLM_MODEL"):
        offline.complete("Rule: R01\nx")


def test_offline_miss_on_a_partly_cached_model_names_the_other_model(tmp_path, fake_transport):
    # The configured model has some cache entries, just not this one; another model is also cached.
    LLMClient(settings(), cache_dir=tmp_path, transport=fake_transport, log=lambda _: None).complete("Rule: R01\nx")
    LLMClient(settings(model="partial-model"), cache_dir=tmp_path, transport=fake_transport, log=lambda _: None).complete("Rule: R02\ny")
    offline = LLMClient(settings(model="partial-model", offline=True), cache_dir=tmp_path, log=lambda _: None)
    with pytest.raises(CacheMiss, match=r"'partial-model'.*only partly cached.*fake-model.*LLM_MODEL=fake-model"):
        offline.complete("Rule: R01\nx")


def test_live_call_is_cached_then_reused(tmp_path, fake_transport):
    client = LLMClient(settings(), cache_dir=tmp_path, transport=fake_transport, log=lambda _: None)
    first = client.complete("Rule: R01\nanything")
    second = client.complete("Rule: R01\nanything")
    assert fake_transport.calls == 1
    assert first == second
    stored = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert stored["model"] == "fake-model"
    assert "test-key" not in json.dumps(stored)


def test_cache_with_two_models_needs_llm_model(tmp_path, fake_transport):
    for model in ("model-a", "model-b"):
        LLMClient(settings(model=model), cache_dir=tmp_path, transport=fake_transport, log=lambda _: None).complete(
            "Rule: R01\nsame prompt"
        )
    offline = LLMClient(settings(model=None, offline=True), cache_dir=tmp_path, log=lambda _: None)
    with pytest.raises(LLMError, match="LLM_MODEL"):
        offline.complete("Rule: R01\nsame prompt")


def test_live_mode_needs_a_known_provider(tmp_path, fake_transport):
    client = LLMClient(settings(provider="other"), cache_dir=tmp_path, transport=fake_transport, log=lambda _: None)
    with pytest.raises(LLMError, match="LLM_PROVIDER"):
        client.complete("Rule: R01\nx")


def test_openai_timeout_becomes_a_clear_error(monkeypatch):
    from orchestrator import llm

    def slow(*_args, **kwargs):
        assert kwargs["timeout"] == 7.0
        raise TimeoutError("The read operation timed out")

    monkeypatch.setenv("LLM_TIMEOUT", "7")
    monkeypatch.setattr(llm.urllib.request, "urlopen", slow)
    with pytest.raises(LLMError, match="LLM_TIMEOUT"):
        llm._openai_compatible(settings(provider="openai", base_url="http://example.invalid/v1"), "", "p")
