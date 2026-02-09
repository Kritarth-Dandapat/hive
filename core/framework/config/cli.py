"""CLI sub-commands for ``hive config``."""

from __future__ import annotations

import argparse
import os
import sys


def register_config_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``config`` command group."""

    config_parser = subparsers.add_parser(
        "config",
        help="Manage Hive configuration",
        description="View and modify Hive configuration settings.",
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_cmd",
        help="Configuration commands",
    )

    # config models
    models_parser = config_subparsers.add_parser(
        "models",
        help="View or change the LLM model configuration",
        description=(
            "Interactive TUI for selecting the LLM provider and model, "
            "or use --list / --set for non-interactive usage."
        ),
    )
    models_parser.add_argument(
        "--list",
        action="store_true",
        dest="list_models",
        help="List available providers and models, then exit",
    )
    models_parser.add_argument(
        "--set",
        type=str,
        dest="set_model",
        metavar="PROVIDER/MODEL",
        help="Set the model directly (e.g. groq/llama3-70b-8192)",
    )
    models_parser.add_argument(
        "--show",
        action="store_true",
        dest="show_current",
        help="Show the current model configuration, then exit",
    )
    models_parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Skip the interactive TUI (useful in scripts or CI)",
    )
    models_parser.set_defaults(func=cmd_config_models)

    # Default handler for bare ``hive config``
    config_parser.set_defaults(func=lambda args: cmd_config_help(config_parser, args))


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def cmd_config_help(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Show help when ``hive config`` is called without a sub-command."""
    if not getattr(args, "config_cmd", None):
        parser.print_help()
        return 0
    return 0


def cmd_config_models(args: argparse.Namespace) -> int:
    """Handle ``hive config models``."""

    from framework.config.models import (
        PROVIDER_MODELS,
        get_current_model_config,
        save_model_config,
        validate_model_config,
    )

    # --show: display current configuration
    if getattr(args, "show_current", False):
        current = get_current_model_config()
        if current["full_model"]:
            print(f"Current model: {current['full_model']}")
        else:
            print("No model configured (will use default: anthropic/claude-sonnet-4-20250514)")
        return 0

    # --list: print providers and models
    if getattr(args, "list_models", False):
        current = get_current_model_config()
        for pid, info in PROVIDER_MODELS.items():
            has_key = (
                "✓" if info.api_key_env and os.environ.get(info.api_key_env)
                else ("n/a" if info.api_key_env is None else "✗")
            )
            marker = " [current]" if pid == current["provider"] else ""
            print(f"\n{info.display_name}  [API key: {has_key}]{marker}")
            for m in info.models:
                ctx = f"{m.context_window:,}" if m.context_window else "?"
                cur = " *" if (
                    m.name == current["model"] and pid == current["provider"]
                ) else ""
                print(f"  {pid}/{m.name}  [{ctx} ctx] {m.description}{cur}")
        print()
        return 0

    # --set: non-interactive model change
    if getattr(args, "set_model", None):
        model_string: str = args.set_model
        if "/" not in model_string:
            print(
                f"Error: model must be in PROVIDER/MODEL format (got '{model_string}')",
                file=sys.stderr,
            )
            return 1

        provider_id, model_name = model_string.split("/", 1)
        provider_id = provider_id.lower()

        errors = validate_model_config(provider_id, model_name)
        for e in errors:
            print(f"Warning: {e}", file=sys.stderr)

        if provider_id not in PROVIDER_MODELS:
            print(
                f"Error: unknown provider '{provider_id}'. "
                f"Known providers: {', '.join(PROVIDER_MODELS.keys())}",
                file=sys.stderr,
            )
            return 1

        save_model_config(provider_id, model_name)
        print(f"Model set to: {provider_id}/{model_name}")
        return 0

    # Default: launch interactive TUI (unless --no-tui)
    if getattr(args, "no_tui", False) or not sys.stdout.isatty():
        # Fall back to --list behaviour
        args.list_models = True
        return cmd_config_models(args)

    from framework.tui.widgets.model_selector import run_model_selector_tui

    saved = run_model_selector_tui()
    return 0 if saved else 1
