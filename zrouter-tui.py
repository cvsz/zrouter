#!/usr/bin/env python3
"""
zcloud-tui — NVIDIA Free-Model Router TUI

A textual-based terminal UI for the zrouter.py router with:
- Chat interface with auto-routing
- Model listing with free/paid filtering
- Provider status monitoring
- Keyboard-driven navigation
- Dark mode support
"""

from __future__ import annotations

import datetime
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

# Add project root to path so we can import zrouter
sys.path.insert(
    0, __import__("os").path.dirname(__import__("os").path.abspath(__file__))
)

import zrouter
from zrouter import CATALOG, PROVIDERS, FreeRouter, RouterError


class ChatScreen(Screen):
    """Chat screen with streaming responses."""

    BINDINGS = [  # noqa: RUF012
        Binding("ctrl+enter", "send", "Send"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("escape", "stop", "Stop"),
        Binding("tab", "focus_next", "Next"),
    ]

    router: FreeRouter | None = None
    is_streaming: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with TabbedContent(), TabPane("Chat", id="chat-pane"), Vertical():
            with Horizontal():
                yield Label("Route:", classes="ctrl-label")
                yield Select(
                    [
                        ("auto", "auto"),
                        ("general", "general"),
                        ("code", "code"),
                        ("reasoning", "reasoning"),
                        ("fast", "fast"),
                        ("vision", "vision"),
                    ],
                    value="auto",
                    id="route-select",
                )
                yield Label("Model:", classes="ctrl-label")
                yield Select(
                    [("auto", "auto")],
                    value="auto",
                    id="model-select",
                )
                yield Label("Max Tokens:", classes="ctrl-label")
                yield Input(value="1024", id="max-tokens", type="integer")
                yield Button("Send", id="send-btn", variant="primary")
                yield Button("Stop", id="stop-btn", variant="error")

            yield TextArea(
                placeholder="Type your message here...",
                id="chat-input",
            )

            yield VerticalScroll(
                Static(
                    "",
                    id="chat-output",
                    classes="chat-output",
                ),
                id="chat-scroll",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._update_model_select()

    def _update_model_select(self) -> None:
        models = [m.get("id", "") for m in CATALOG.models]
        models.sort()
        select = self.query_one("#model-select", Select)
        select.set_options([("auto", "auto")] + [(m, m) for m in models])

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            await self._send_chat()
        elif event.button.id == "stop-btn":
            self.is_streaming = False

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            await self._send_chat()

    async def _send_chat(self) -> None:
        input_widget = self.query_one("#chat-input", TextArea)
        prompt = input_widget.text.strip()
        if not prompt:
            return

        route_select = self.query_one("#route-select", Select)
        model_select = self.query_one("#model-select", Select)
        max_tokens_input = self.query_one("#max-tokens", Input)

        route = route_select.value or "auto"
        model = model_select.value or None
        max_tokens = int(max_tokens_input.value or 1024)

        # Ensure router
        if self.router is None:
            import os

            keys = os.environ.get("NVIDIA_API_KEYS", "")
            os.environ["NVIDIA_API_KEYS"] = keys
            try:
                self.router = FreeRouter()
            except RouterError as exc:
                self._append_chat(f"Error: {exc}\n", "error")
                return

        # Display user message
        self._append_chat(f"You: {prompt}\n", "user")
        input_widget.text = ""
        self.is_streaming = True

        # Run chat in thread
        import threading as _threading

        def _chat() -> None:
            try:
                router = self.router
                msgs = [{"role": "user", "content": prompt}]

                from zrouter import Settings

                cfg = Settings()
                cfg.rpm = int(
                    os.environ.get("NVIDIA_RPM", str(cfg.rpm))
                )  # use current cfg

                if self.is_streaming:
                    for delta in router.chat_stream(
                        msgs, route=route, model=model, max_tokens=max_tokens
                    ):
                        if not self.is_streaming:
                            break
                        self.app.call_from_thread(self._append_chat, delta, "stream")
                    if self.is_streaming:
                        self.app.call_from_thread(self._append_chat, "\n", "stream")
                else:
                    out = router.chat(
                        msgs, route=route, model=model, max_tokens=max_tokens
                    )
                    self.app.call_from_thread(
                        self._append_chat,
                        f"[{out['model']}] {out['text']}\n",
                        "assistant",
                    )
            except RouterError as exc:
                self.app.call_from_thread(
                    self._append_chat, f"Router Error: {exc}\n", "error"
                )
            except Exception as exc:  # noqa: BLE001
                self.app.call_from_thread(self._append_chat, f"Error: {exc}\n", "error")
            finally:
                self.app.call_from_thread(self._set_ready)

        _threading.Thread(target=_chat, daemon=True).start()

    def _append_chat(self, text: str, tag: str = "") -> None:
        output = self.query_one("#chat-output", Static)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        if tag == "user":
            prefix = f"[{timestamp}] You: "
            output.update(
                output.renderable + prefix + text
                if output.renderable
                else prefix + text
            )
        elif tag == "assistant":
            prefix = f"[{timestamp}] Assistant: "
            output.update(
                output.renderable + prefix + text
                if output.renderable
                else prefix + text
            )
        elif tag == "stream":
            output.update(output.renderable + text if output.renderable else text)
        else:
            output.update(output.renderable + text if output.renderable else text)

        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.scroll_end()

    def _set_ready(self) -> None:
        self.is_streaming = False

    def action_send(self) -> None:
        self._send_chat_sync()

    def _send_chat_sync(self) -> None:
        import asyncio as _asyncio

        _asyncio.create_task(self._send_chat())

    def action_stop(self) -> None:
        self.is_streaming = False

    def action_focus_next(self) -> None:
        self.focus_next()


class ModelsScreen(Screen):
    """Models listing screen."""

    BINDINGS = [  # noqa: RUF012
        Binding("ctrl+q", "quit", "Quit"),
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical():
            yield Label("Models Catalog", classes="title")
            yield Label(
                "Filter by provider and tier. Press Enter on a model to select.",
                classes="subtitle",
            )

            with Horizontal():
                yield Select(
                    [("All", "All")]
                    + [
                        (p, p)
                        for p in sorted(
                            {m.get("provider", "unknown") for m in CATALOG.models}
                        )
                    ],
                    value="All",
                    id="provider-filter",
                )
                yield Select(
                    [
                        ("All tiers", "all"),
                        ("Free only", "free"),
                        ("Paid only", "paid"),
                    ],
                    value="all",
                    id="tier-filter",
                )
                yield Button("Refresh", id="refresh-btn", variant="primary")

            yield Static(
                "",
                id="models-output",
                classes="models-output",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._refresh_models()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._refresh_models()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-btn":
            self._refresh_models()

    def _refresh_models(self) -> None:
        provider_filter = self.query_one("#provider-filter", Select).value
        tier_filter = self.query_one("#tier-filter", Select).value

        models = CATALOG.models
        if provider_filter != "All":
            models = CATALOG.by_provider(provider_filter)
        if tier_filter == "free":
            models = CATALOG.list_free()
        elif tier_filter == "paid":
            models = CATALOG.list_paid()

        lines = []
        for m in sorted(models, key=lambda x: str(x.get("id", ""))):
            tier = "free" if m.get("free") else "paid"
            routes = ",".join(m.get("routes", []))
            lines.append(
                f"{m.get('id', ''):<40} {m.get('provider', 'unknown'):<16} {tier:<8} {routes:<24} {m.get('description', '')}"
            )

        output = self.query_one("#models-output", Static)
        output.update("\n".join(lines) if lines else "No models match filters.")

    def action_back(self) -> None:
        self.app.pop_screen()


class ProvidersScreen(Screen):
    """Providers status screen."""

    BINDINGS = [  # noqa: RUF012
        Binding("ctrl+q", "quit", "Quit"),
        Binding("escape", "back", "Back"),
        Binding("a", "add_key", "Add Key"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical():
            yield Label("Providers", classes="title")
            yield Static(
                "",
                id="providers-output",
                classes="providers-output",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._refresh_providers()

    def _refresh_providers(self) -> None:
        lines = []
        for p in PROVIDERS.list_providers():
            status = "✓ configured" if p["has_keys"] else "✗ no keys"
            lines.append(
                f"{p['name']:<20} {p['base_url']:<45} keys={p['key_count']:<3} {status}"
            )

        output = self.query_one("#providers-output", Static)
        output.update("\n".join(lines) if lines else "No providers configured.")

    def action_add_key(self) -> None:
        self.app.push_screen(
            _KeyInputScreen(),
            callback=lambda result: self._refresh_providers() if result else None,
        )

    def action_back(self) -> None:
        self.app.pop_screen()


class _KeyInputScreen(Screen):
    """Screen for adding a provider API key."""

    BINDINGS = [  # noqa: RUF012
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical():
            yield Label("Add API Key", classes="title")
            yield Input(placeholder="Provider name (e.g. Groq)", id="provider-input")
            yield Input(placeholder="API key", id="key-input", password=True)
            yield Input(placeholder="Base URL (optional)", id="base-url-input")
            yield Input(placeholder="Env var name (optional)", id="env-var-input")
            yield Button("Add", id="add-key-btn", variant="primary")
            yield Button("Cancel", id="cancel-btn")

        yield Footer()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-key-btn":
            self._add_key()
        elif event.button.id == "cancel-btn":
            self.app.pop_screen()

    def _add_key(self) -> None:
        provider = self.query_one("#provider-input", Input).value.strip()
        key = self.query_one("#key-input", Input).value.strip()
        base_url = self.query_one("#base-url-input", Input).value.strip()
        env_var = self.query_one("#env-var-input", Input).value.strip()

        if not provider or not key:
            self.notify("Provider and key are required", severity="error")
            return

        import os

        cfg = PROVIDERS.get(provider)
        if cfg:
            keys_list = list(cfg["api_keys"])
            keys_list.append(key)
            cfg["api_keys"] = keys_list
        else:
            PROVIDERS.providers[provider] = {
                "api_keys": [key],
                "base_url": base_url or zrouter.CFG.base_url,
                "env_var": env_var or f"{provider.upper()}_API_KEYS",
            }

        if env_var:
            os.environ[env_var] = key

        self.notify(f"Key added for {provider}")
        self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()


class ZCloudTUI(App):
    """Main TUI application."""

    TITLE = "zcloud — NVIDIA Free-Model Router"
    CSS = """
    Screen {
        align: center middle;
    }
    .title {
        text-align: center;
        text-style: bold;
        color: #0066cc;
        margin-bottom: 1;
    }
    .subtitle {
        text-align: center;
        color: #666666;
        margin-bottom: 1;
    }
    .ctrl-label {
        width: 12;
    }
    #chat-output {
        width: 100%;
        height: 1fr;
        border: solid #666666;
        padding: 1;
    }
    #chat-input {
        width: 100%;
        height: 6;
    }
    .models-output {
        width: 100%;
        height: 1fr;
        border: solid #666666;
        padding: 1;
    }
    .providers-output {
        width: 100%;
        height: 1fr;
        border: solid #666666;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with TabbedContent():
            with TabPane("Chat", id="chat-tab"):
                yield ChatScreen()
            with TabPane("Models", id="models-tab"):
                yield ModelsScreen()
            with TabPane("Providers", id="providers-tab"):
                yield ProvidersScreen()

        yield Footer()

    BINDINGS = [  # noqa: RUF012
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]


def main() -> None:
    app = ZCloudTUI()
    app.run()


if __name__ == "__main__":
    main()
