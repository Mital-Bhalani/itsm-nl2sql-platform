"""Provider selection, missing keys and fallback in agent/llm.py (no network calls)."""

import pytest

import llm


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(llm, "load_env", lambda: None)
    for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_FALLBACK_PROVIDER", "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY", "OPENAI_MODEL", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def fake_caller(name, fail=False):
    def call(system, user, model):
        if fail:
            raise llm.AgentAPIError(f"{name} down")
        return f"{name}:{model}", 3, 2, None
    return call


def test_defaults(env):
    assert llm.default_provider() == "openai"
    assert llm.default_model("openai") == "gpt-4o-mini"
    assert llm.default_model("anthropic") == "claude-opus-5-5"
    env.setenv("LLM_PROVIDER", "anthropic")
    env.setenv("LLM_MODEL", "claude-sonnet-5-5")
    assert llm.default_model("anthropic") == "claude-sonnet-5-5"
    assert llm.default_model("openai") == "gpt-4o-mini"  # LLM_MODEL only for the default provider


def test_available_providers_reflect_keys(env):
    env.setenv("OPENAI_API_KEY", "x")
    status = {p["name"]: p["configured"] for p in llm.available_providers()}
    assert status == {"openai": True, "anthropic": False}


def test_missing_key_raises(env):
    with pytest.raises(llm.AgentAPIError, match="ANTHROPIC_API_KEY is not set"):
        llm.complete("s", "u", provider="anthropic")


def test_unknown_provider(env):
    with pytest.raises(llm.AgentAPIError, match="Unknown provider"):
        llm.complete("s", "u", provider="nope")


def test_complete_uses_chosen_provider(env):
    env.setenv("ANTHROPIC_API_KEY", "x")
    env.setitem(llm.CALLERS, "anthropic", fake_caller("anthropic"))
    reply = llm.complete("s", "u", provider="anthropic", model="m1")
    assert (reply.text, reply.provider, reply.model, reply.tokens_in) == ("anthropic:m1", "anthropic", "m1", 3)


def test_fallback_only_when_provider_not_explicit(env):
    env.setenv("OPENAI_API_KEY", "x")
    env.setenv("ANTHROPIC_API_KEY", "x")
    env.setenv("LLM_FALLBACK_PROVIDER", "anthropic")
    env.setitem(llm.CALLERS, "openai", fake_caller("openai", fail=True))
    env.setitem(llm.CALLERS, "anthropic", fake_caller("anthropic"))
    assert llm.complete("s", "u").provider == "anthropic"
    with pytest.raises(llm.AgentAPIError, match="openai down"):
        llm.complete("s", "u", provider="openai")
