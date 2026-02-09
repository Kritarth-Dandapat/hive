"""Tests for ``hive config models`` CLI and configuration helpers."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from framework.config.models import (
    PROVIDER_MODELS,
    get_current_model_config,
    get_provider_for_model,
    list_providers,
    save_model_config,
    validate_model_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Point HIVE_CONFIG_FILE at a temp directory so tests never touch ``~/.hive``."""
    config_file = tmp_path / "configuration.json"
    monkeypatch.setattr("framework.config.models.HIVE_CONFIG_FILE", config_file)
    return config_file


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Unit tests – models module
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    """Validate the static provider / model registry."""

    def test_providers_not_empty(self):
        assert len(PROVIDER_MODELS) > 0

    def test_each_provider_has_models(self):
        for pid, info in PROVIDER_MODELS.items():
            assert len(info.models) > 0, f"Provider {pid} has no models"

    def test_each_provider_has_display_name(self):
        for pid, info in PROVIDER_MODELS.items():
            assert info.display_name, f"Provider {pid} missing display_name"

    def test_list_providers_returns_all(self):
        providers = list_providers()
        assert len(providers) == len(PROVIDER_MODELS)


class TestGetProviderForModel:

    def test_known_provider(self):
        assert get_provider_for_model("groq/llama3-70b-8192") == "groq"
        assert get_provider_for_model("anthropic/claude-sonnet-4-20250514") == "anthropic"
        assert get_provider_for_model("openai/gpt-4o") == "openai"

    def test_unknown_provider(self):
        assert get_provider_for_model("unknown/model") is None

    def test_no_slash(self):
        assert get_provider_for_model("claude-sonnet-4-20250514") is None


class TestValidateModelConfig:

    def test_valid_config(self):
        errors = validate_model_config("ollama", "llama3")
        # ollama has no API key requirement
        assert len(errors) == 0

    def test_unknown_provider(self):
        errors = validate_model_config("nonexistent", "model")
        assert any("Unknown provider" in e for e in errors)

    def test_unknown_model(self):
        errors = validate_model_config("groq", "nonexistent-model")
        assert any("not in the known list" in e for e in errors)

    def test_missing_api_key(self):
        with patch.dict(os.environ, {}, clear=False):
            # Ensure GROQ_API_KEY is not set
            os.environ.pop("GROQ_API_KEY", None)
            errors = validate_model_config("groq", "llama3-70b-8192")
            assert any("GROQ_API_KEY" in e for e in errors)

    def test_api_key_present(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            errors = validate_model_config("groq", "llama3-70b-8192")
            assert not any("GROQ_API_KEY" in e for e in errors)


class TestConfigReadWrite:
    """Read/write to ``~/.hive/configuration.json`` via helpers."""

    def test_get_current_no_file(self, tmp_config):
        result = get_current_model_config()
        assert result["provider"] is None
        assert result["model"] is None
        assert result["full_model"] is None

    def test_save_and_get(self, tmp_config):
        save_model_config("groq", "llama3-70b-8192")

        result = get_current_model_config()
        assert result["provider"] == "groq"
        assert result["model"] == "llama3-70b-8192"
        assert result["full_model"] == "groq/llama3-70b-8192"

    def test_save_preserves_other_keys(self, tmp_config):
        # Write an initial config with extra keys
        tmp_config.parent.mkdir(parents=True, exist_ok=True)
        tmp_config.write_text(json.dumps({"custom_key": "value", "llm": {}}))

        save_model_config("openai", "gpt-4o")

        data = json.loads(tmp_config.read_text())
        assert data["custom_key"] == "value"
        assert data["llm"]["provider"] == "openai"
        assert data["llm"]["model"] == "gpt-4o"

    def test_save_creates_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "sub" / "dir" / "configuration.json"
        monkeypatch.setattr("framework.config.models.HIVE_CONFIG_FILE", nested)
        save_model_config("anthropic", "claude-haiku-4-5-20251001")
        assert nested.exists()
        data = json.loads(nested.read_text())
        assert data["llm"]["provider"] == "anthropic"

    def test_overwrite_existing(self, tmp_config):
        save_model_config("groq", "llama3-70b-8192")
        save_model_config("openai", "gpt-4o")

        result = get_current_model_config()
        assert result["full_model"] == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestConfigModelsCLI:
    """Test the ``hive config models`` CLI commands via subprocess."""

    def test_config_help(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "framework", "config", "--help"],
            capture_output=True, text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "models" in result.stdout

    def test_config_models_help(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "framework", "config", "models", "--help"],
            capture_output=True, text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "--list" in result.stdout
        assert "--set" in result.stdout
        assert "--show" in result.stdout

    def test_config_models_list(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "framework", "config", "models", "--list"],
            capture_output=True, text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 0
        assert "Anthropic" in result.stdout
        assert "Groq" in result.stdout
        assert "OpenAI" in result.stdout

    def test_config_models_show_default(self, tmp_config):
        """Without a config file the default message is printed."""
        from framework.config.cli import cmd_config_models

        args = argparse.Namespace(
            show_current=True, list_models=False, set_model=None, no_tui=False,
        )
        # tmp_config fixture ensures no real config is read
        from io import StringIO
        from unittest.mock import patch as mock_patch
        buf = StringIO()
        with mock_patch("sys.stdout", buf):
            ret = cmd_config_models(args)
        assert ret == 0
        output = buf.getvalue()
        assert "default" in output.lower() or "not configured" in output.lower()

    def test_config_models_set_invalid_format(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "framework", "config", "models", "--set", "badformat"],
            capture_output=True, text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 1
        assert "PROVIDER/MODEL" in result.stderr

    def test_config_models_set_unknown_provider(self, project_root):
        result = subprocess.run(
            [sys.executable, "-m", "framework", "config", "models",
             "--set", "fake_provider/some-model"],
            capture_output=True, text=True,
            cwd=str(project_root / "core"),
        )
        assert result.returncode == 1
        assert "unknown provider" in result.stderr.lower()

    def test_config_models_set_and_show(self, tmp_config):
        """Set a model and then verify with --show."""
        from framework.config.cli import cmd_config_models

        from io import StringIO
        from unittest.mock import patch as mock_patch

        # --set
        set_args = argparse.Namespace(
            show_current=False, list_models=False,
            set_model="groq/llama3-70b-8192", no_tui=False,
        )
        buf = StringIO()
        with mock_patch("sys.stdout", buf):
            ret = cmd_config_models(set_args)
        assert ret == 0
        assert "groq/llama3-70b-8192" in buf.getvalue()

        # --show
        show_args = argparse.Namespace(
            show_current=True, list_models=False, set_model=None, no_tui=False,
        )
        buf2 = StringIO()
        with mock_patch("sys.stdout", buf2):
            ret2 = cmd_config_models(show_args)
        assert ret2 == 0
        assert "groq/llama3-70b-8192" in buf2.getvalue()
