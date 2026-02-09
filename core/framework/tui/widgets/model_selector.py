"""Interactive TUI for selecting LLM provider and model.

Launched via ``hive config models`` (with ``--tui`` or as default when a
terminal is attached).  Uses Textual widgets that are consistent with the
existing Hive TUI infrastructure in ``framework.tui``.
"""

from __future__ import annotations

import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Button, Footer, Header, Label, OptionList, Static
from textual.widgets.option_list import Option

from framework.config.models import (
    PROVIDER_MODELS,
    get_current_model_config,
    save_model_config,
    validate_model_config,
)


class ModelSelectorApp(App[bool]):
    """Textual application for interactive LLM model configuration."""

    TITLE = "Hive Model Configuration"

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }
    #provider-container, #model-container, #config-container {
        height: auto;
        max-height: 50%;
        margin: 1 2;
        border: solid $primary;
        padding: 1 2;
    }
    #config-container {
        height: auto;
        max-height: 30%;
    }
    .section-title {
        text-style: bold;
        margin-bottom: 1;
        color: $text;
    }
    #status-label {
        margin: 1 2;
        color: $success;
    }
    #button-bar {
        dock: bottom;
        height: 3;
        margin: 0 2;
        layout: horizontal;
    }
    #button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit_app", "Cancel"),
        Binding("enter", "select_option", "Select", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._provider_ids: list[str] = list(PROVIDER_MODELS.keys())
        current = get_current_model_config()
        self._selected_provider: str = current["provider"] or self._provider_ids[0]
        self._selected_model: str | None = current["model"]

    # ---- compose -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical():
            # Provider selector
            with Container(id="provider-container"):
                yield Label("Select LLM Provider", classes="section-title")
                yield OptionList(id="provider-list")

            # Model selector
            with Container(id="model-container"):
                yield Label("Select Model", classes="section-title")
                yield OptionList(id="model-list")

            # Config summary
            with Container(id="config-container"):
                yield Label("Configuration", classes="section-title")
                yield Static(id="config-summary")

            yield Label("", id="status-label")

        with Container(id="button-bar"):
            yield Button("Save", variant="primary", id="save-btn")
            yield Button("Cancel", variant="default", id="cancel-btn")

        yield Footer()

    # ---- lifecycle ----------------------------------------------------------
    def on_mount(self) -> None:
        self._populate_providers()
        self._populate_models()
        self._update_summary()

    # ---- provider list ------------------------------------------------------
    def _populate_providers(self) -> None:
        provider_list: OptionList = self.query_one("#provider-list", OptionList)
        provider_list.clear_options()

        current = get_current_model_config()
        for pid in self._provider_ids:
            info = PROVIDER_MODELS[pid]
            has_key = (
                "✓" if info.api_key_env and os.environ.get(info.api_key_env)
                else ("n/a" if info.api_key_env is None else "✗")
            )
            marker = " [current]" if pid == current["provider"] else ""
            label = f"{info.display_name}  [{has_key}]{marker}"
            provider_list.add_option(Option(label, id=pid))

        # Highlight the currently-selected provider
        idx = self._provider_ids.index(self._selected_provider)
        provider_list.highlighted = idx

    # ---- model list ---------------------------------------------------------
    def _populate_models(self) -> None:
        model_list: OptionList = self.query_one("#model-list", OptionList)
        model_list.clear_options()

        info = PROVIDER_MODELS.get(self._selected_provider)
        if info is None:
            return

        current = get_current_model_config()
        for m in info.models:
            ctx = f"{m.context_window:,}" if m.context_window else "?"
            marker = " [current]" if (
                m.name == current["model"] and self._selected_provider == current["provider"]
            ) else ""
            label = f"{m.name}  [{ctx} ctx] {m.description}{marker}"
            model_list.add_option(Option(label, id=m.name))

        if info.models:
            # Try to highlight the previously-selected model, else first
            names = [m.name for m in info.models]
            if self._selected_model in names:
                model_list.highlighted = names.index(self._selected_model)
            else:
                model_list.highlighted = 0
                self._selected_model = info.models[0].name

    # ---- summary pane -------------------------------------------------------
    def _update_summary(self) -> None:
        summary: Static = self.query_one("#config-summary", Static)
        current = get_current_model_config()

        info = PROVIDER_MODELS.get(self._selected_provider)
        api_status = "n/a"
        if info and info.api_key_env:
            api_status = "✓ Configured" if os.environ.get(info.api_key_env) else "✗ Not set"
        elif info and info.api_key_env is None:
            api_status = "n/a (local)"

        lines = [
            f"Current:  {current.get('full_model') or '(not configured)'}",
            f"Selected: {self._selected_provider}/{self._selected_model}",
            f"API Key:  {api_status}",
        ]
        summary.update("\n".join(lines))

    # ---- event handlers -----------------------------------------------------
    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        option_list = event.option_list
        option_id = event.option.id if event.option else None

        if option_list.id == "provider-list" and option_id:
            self._selected_provider = str(option_id)
            self._populate_models()
            self._update_summary()
        elif option_list.id == "model-list" and option_id:
            self._selected_model = str(option_id)
            self._update_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._do_save()
        elif event.button.id == "cancel-btn":
            self.exit(False)

    def action_quit_app(self) -> None:
        self.exit(False)

    # ---- save ---------------------------------------------------------------
    def _do_save(self) -> None:
        if not self._selected_model:
            self.query_one("#status-label", Label).update("No model selected")
            return

        warnings = validate_model_config(self._selected_provider, self._selected_model)
        # Show warnings but still allow saving (they may be non-fatal)
        status_label = self.query_one("#status-label", Label)
        if warnings:
            status_label.update("⚠  " + "; ".join(warnings))

        save_model_config(self._selected_provider, self._selected_model)
        status_label.update(
            f"✓ Saved: {self._selected_provider}/{self._selected_model}"
        )
        self.exit(True)


def run_model_selector_tui() -> bool:
    """Launch the interactive model selector.  Returns ``True`` if saved."""
    app = ModelSelectorApp()
    return app.run() or False
