"""Model configuration: provider/model registry, validation, and config I/O.

Provides the data layer for the ``hive config models`` command and the
interactive TUI model-selector widget.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a single LLM model."""

    name: str
    context_window: int | None = None
    description: str = ""


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for a single LLM provider."""

    id: str
    display_name: str
    api_key_env: str | None = None
    models: list[ModelInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider / model registry
# ---------------------------------------------------------------------------
PROVIDER_MODELS: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        id="anthropic",
        display_name="Anthropic (Claude)",
        api_key_env="ANTHROPIC_API_KEY",
        models=[
            ModelInfo("claude-sonnet-4-20250514", 200_000, "Balanced performance"),
            ModelInfo("claude-haiku-4-5-20251001", 200_000, "Fast & affordable"),
            ModelInfo("claude-opus-4-20250514", 200_000, "Highest capability"),
        ],
    ),
    "groq": ProviderInfo(
        id="groq",
        display_name="Groq (Llama, Mixtral)",
        api_key_env="GROQ_API_KEY",
        models=[
            ModelInfo("llama3-70b-8192", 8_192, "8K context, fast"),
            ModelInfo("llama3-8b-8192", 8_192, "8K context, fastest"),
            ModelInfo("mixtral-8x7b-32768", 32_768, "32K context"),
        ],
    ),
    "openai": ProviderInfo(
        id="openai",
        display_name="OpenAI (GPT)",
        api_key_env="OPENAI_API_KEY",
        models=[
            ModelInfo("gpt-4o", 128_000, "Flagship multimodal"),
            ModelInfo("gpt-4o-mini", 128_000, "Fast & affordable"),
            ModelInfo("gpt-4-turbo", 128_000, "GPT-4 Turbo"),
        ],
    ),
    "google": ProviderInfo(
        id="google",
        display_name="Google (Gemini)",
        api_key_env="GOOGLE_API_KEY",
        models=[
            ModelInfo("gemini-2.0-flash", 1_048_576, "Fast multimodal"),
            ModelInfo("gemini-1.5-pro", 2_097_152, "Long-context flagship"),
        ],
    ),
    "cerebras": ProviderInfo(
        id="cerebras",
        display_name="Cerebras",
        api_key_env="CEREBRAS_API_KEY",
        models=[
            ModelInfo("llama3.1-70b", 8_192, "Fast inference"),
            ModelInfo("llama3.1-8b", 8_192, "Fastest inference"),
        ],
    ),
    "mistral": ProviderInfo(
        id="mistral",
        display_name="Mistral",
        api_key_env="MISTRAL_API_KEY",
        models=[
            ModelInfo("mistral-large-latest", 128_000, "Flagship"),
            ModelInfo("mistral-small-latest", 128_000, "Cost-efficient"),
        ],
    ),
    "ollama": ProviderInfo(
        id="ollama",
        display_name="Ollama (Local)",
        api_key_env=None,
        models=[
            ModelInfo("llama3", None, "Local Llama 3"),
            ModelInfo("mistral", None, "Local Mistral"),
            ModelInfo("codellama", None, "Local Code Llama"),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Configuration file path (mirrors runner.py)
# ---------------------------------------------------------------------------
HIVE_CONFIG_FILE = Path.home() / ".hive" / "configuration.json"


def _load_config() -> dict[str, Any]:
    """Load ``~/.hive/configuration.json`` (returns ``{}`` on any error)."""
    if not HIVE_CONFIG_FILE.exists():
        return {}
    try:
        with open(HIVE_CONFIG_FILE) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_config(config: dict[str, Any]) -> None:
    """Atomically write *config* to ``~/.hive/configuration.json``."""
    HIVE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory, then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(
        dir=str(HIVE_CONFIG_FILE.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, str(HIVE_CONFIG_FILE))
    except BaseException:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def list_providers() -> list[ProviderInfo]:
    """Return all registered providers."""
    return list(PROVIDER_MODELS.values())


def get_provider_for_model(model_string: str) -> str | None:
    """Extract the provider id from a ``provider/model`` string.

    Returns ``None`` when the string does not match a known provider.
    """
    if "/" not in model_string:
        return None
    provider_id = model_string.split("/", 1)[0].lower()
    if provider_id in PROVIDER_MODELS:
        return provider_id
    return None


def get_current_model_config() -> dict[str, str | None]:
    """Return ``{"provider": ..., "model": ..., "full_model": ...}``."""
    config = _load_config()
    llm = config.get("llm", {})
    provider = llm.get("provider")
    model = llm.get("model")
    full_model = f"{provider}/{model}" if provider and model else None
    return {"provider": provider, "model": model, "full_model": full_model}


def validate_model_config(
    provider_id: str, model_name: str
) -> list[str]:
    """Validate a provider/model pair.  Returns a list of error strings (empty == OK)."""
    errors: list[str] = []

    if provider_id not in PROVIDER_MODELS:
        errors.append(f"Unknown provider: {provider_id}")
        return errors

    info = PROVIDER_MODELS[provider_id]
    known_models = [m.name for m in info.models]
    if model_name not in known_models:
        errors.append(
            f"Model '{model_name}' is not in the known list for provider "
            f"'{provider_id}'. Known models: {', '.join(known_models)}"
        )

    # Check API key
    if info.api_key_env and not os.environ.get(info.api_key_env):
        errors.append(
            f"API key not found: environment variable {info.api_key_env} is not set"
        )

    return errors


def save_model_config(provider_id: str, model_name: str) -> None:
    """Persist the chosen provider/model to ``~/.hive/configuration.json``."""
    config = _load_config()
    config.setdefault("llm", {})
    config["llm"]["provider"] = provider_id
    config["llm"]["model"] = model_name
    _save_config(config)
