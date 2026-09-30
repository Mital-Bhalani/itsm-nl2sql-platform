"""
Language-model providers for the NL2SQL agent.

    from llm import complete
    reply = complete(system_prompt, question)                         # default provider
    reply = complete(system_prompt, question, provider="anthropic")   # a specific one

Two providers are supported: OpenAI and Anthropic (Claude). Which one runs is set by
environment variables (read from the project-root .env as well):

    LLM_PROVIDER            openai (default) | anthropic
    LLM_MODEL               model for the default provider (optional)
    LLM_FALLBACK_PROVIDER   provider to try when the first one fails (optional)
    OPENAI_API_KEY          key for openai;  OPENAI_MODEL is still honoured (default gpt-4o-mini)
    ANTHROPIC_API_KEY       key for anthropic; ANTHROPIC_MODEL optional (default claude-opus-5-5)
    LLM_ALLOWED_MODELS      extra models the API may be asked for, comma-separated, each
                            "model" or "provider:model" (the configured defaults are always allowed)

Every failure (missing package, missing key, network, no credits) raises AgentAPIError so
callers can tell "the model could not be reached" apart from "the SQL was wrong".
"""

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

TIMEOUT_SECONDS = 60
MAX_RETRIES = 1
MAX_TOKENS = 4000

PROVIDERS = {
    "openai": {"key": "OPENAI_API_KEY", "model_env": "OPENAI_MODEL", "default_model": "gpt-4o-mini",
               "label": "OpenAI"},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "model_env": "ANTHROPIC_MODEL",
                  "default_model": "claude-opus-5-5", "label": "Anthropic Claude"},
}


class AgentAPIError(RuntimeError):
    """The language-model call failed (missing key, no credits, network). Not an SQL problem."""


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str
    latency_ms: int
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None  # prompt tokens served from the provider's prompt cache


# -----------------------------------------------------------------------------
#  Configuration
# -----------------------------------------------------------------------------
def load_env():
    """Copy KEY=value lines from the project-root .env into os.environ (existing values win)."""
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def default_provider():
    load_env()
    return (os.getenv("LLM_PROVIDER") or "openai").strip().lower()


def default_model(provider):
    """LLM_MODEL applies to the default provider only; otherwise the provider's own setting."""
    load_env()
    spec = _spec(provider)
    if provider == default_provider() and os.getenv("LLM_MODEL"):
        return os.environ["LLM_MODEL"].strip()
    return (os.getenv(spec["model_env"]) or spec["default_model"]).strip()


def available_providers():
    """[{name, label, default_model, configured, is_default}] for every known provider."""
    load_env()
    chosen = default_provider()
    return [{"name": name, "label": spec["label"], "default_model": default_model(name),
             "configured": bool(os.getenv(spec["key"])), "is_default": name == chosen}
            for name, spec in PROVIDERS.items()]


def _spec(provider):
    if provider not in PROVIDERS:
        raise AgentAPIError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}")
    return PROVIDERS[provider]


def allowed_models(provider):
    """Models the API accepts for a provider: its configured default plus LLM_ALLOWED_MODELS."""
    load_env()
    allowed = {default_model(provider), PROVIDERS[provider]["default_model"]}
    for entry in (os.getenv("LLM_ALLOWED_MODELS") or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, _, model = entry.rpartition(":")
        if not name or name == provider:
            allowed.add(model)
    return allowed


# Provider error messages can echo part of the API key ("Incorrect API key provided: sk-...").
KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9])sk-(?:ant-|proj-)?[A-Za-z0-9_*-]{6,}")


def redact(text):
    """Remove API keys (configured values and anything shaped like one) from an error message."""
    text = str(text)
    for spec in PROVIDERS.values():
        key = os.getenv(spec["key"])
        if key and len(key) >= 8:
            text = text.replace(key, "[redacted]")
    return KEY_PATTERN.sub("[redacted]", text)


# -----------------------------------------------------------------------------
#  Provider calls
# -----------------------------------------------------------------------------
# One SDK client per provider, built on first use and kept: the client owns the HTTP connection
# pool, so reusing it saves a TLS handshake per question (the first call after a start was
# measured at 50 s once; later calls take about 5 s).
_clients: dict[str, object] = {}
_clients_lock = threading.Lock()


def _client(provider):
    with _clients_lock:
        client = _clients.get(provider)
        if client is None:
            if provider == "openai":
                import openai
                client = openai.OpenAI(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
            else:
                import anthropic
                client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
            _clients[provider] = client
        return client


def reset_clients():
    """Drop the cached SDK clients (after a key change, or in tests)."""
    with _clients_lock:
        _clients.clear()


def warm_up(provider=None):
    """
    Import the SDK, build the client and open one connection to the provider (a cheap model
    lookup, no tokens) so the first real question does not pay the cold-start cost. Best effort:
    returns True when the provider answered, False otherwise; never raises.
    """
    load_env()
    provider = (provider or default_provider()).strip().lower()
    try:
        spec = _spec(provider)
        if not os.getenv(spec["key"]):
            return False
        client = _client(provider)
        client.with_options(timeout=15).models.retrieve(default_model(provider))
        return True
    except Exception:  # noqa: BLE001 - warm-up must never break the caller
        return False


def _call_openai(system, user, model):
    try:
        import openai
    except ModuleNotFoundError as exc:
        raise AgentAPIError("The 'openai' package is not installed: pip install -r requirements.txt") from exc
    try:
        client = _client("openai")
        reply = client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    except openai.OpenAIError as exc:
        raise AgentAPIError(f"{type(exc).__name__}: {redact(exc)}") from exc
    usage = reply.usage
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    cached = getattr(details, "cached_tokens", None) if details else None
    return (reply.choices[0].message.content or "",
            usage.prompt_tokens if usage else None, usage.completion_tokens if usage else None, cached)


def _call_anthropic(system, user, model):
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise AgentAPIError("The 'anthropic' package is not installed: pip install -r requirements.txt") from exc
    try:
        client = _client("anthropic")
        # The system prompt (the whole semantic catalog) is identical across questions, so it
        # is marked for prompt caching. Current Claude models take no temperature; effort
        # controls how much they think. If a safety classifier declines, the server-side
        # fallback re-runs the request on another model inside the same call.
        reply = client.beta.messages.create(
            model=model, max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": user}])
    except anthropic.AnthropicError as exc:
        raise AgentAPIError(f"{type(exc).__name__}: {redact(exc)}") from exc
    if reply.stop_reason == "refusal":
        raise AgentAPIError("The model declined to answer (stop_reason = refusal).")
    text = "".join(block.text for block in reply.content if block.type == "text")
    cached = getattr(reply.usage, "cache_read_input_tokens", None)
    return text, reply.usage.input_tokens, reply.usage.output_tokens, cached


CALLERS = {"openai": _call_openai, "anthropic": _call_anthropic}


def _complete_once(system, user, provider, model):
    spec = _spec(provider)
    if not os.getenv(spec["key"]):
        raise AgentAPIError(f"{spec['key']} is not set (add it to .env) - {spec['label']} unavailable.")
    started = time.perf_counter()
    text, tokens_in, tokens_out, tokens_cached = CALLERS[provider](system, user, model)
    return LLMReply(text=text, provider=provider, model=model,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    tokens_in=tokens_in, tokens_out=tokens_out, tokens_cached=tokens_cached)


def complete(system, user, provider=None, model=None):
    """
    One chat completion. Falls back to LLM_FALLBACK_PROVIDER (with its default model) when
    the chosen provider fails and no provider was explicitly requested.
    """
    load_env()
    explicit = provider is not None
    provider = (provider or default_provider()).strip().lower()
    model = model or default_model(provider)
    try:
        return _complete_once(system, user, provider, model)
    except AgentAPIError as first:
        fallback = (os.getenv("LLM_FALLBACK_PROVIDER") or "").strip().lower()
        if explicit or not fallback or fallback == provider:
            raise
        try:
            return _complete_once(system, user, fallback, default_model(fallback))
        except AgentAPIError as second:
            raise AgentAPIError(f"{provider}: {first} | fallback {fallback}: {second}") from second
