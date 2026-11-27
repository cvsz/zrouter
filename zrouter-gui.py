#!/usr/bin/env python3
"""
zcloud-gui — NVIDIA Free-Model Router GUI

A tkinter-based desktop GUI for the zrouter.py router with:
- API key / provider management
- Free/paid model listing with filtering
- Chat interface with auto-routing and streaming
- Side-by-side model comparison
- Theme system: Cute Professional Premium / Dark Premium
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from ttkthemes import ThemedStyle

# Add project root to path so we can import zrouter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import zrouter
from zrouter import (
    CATALOG,
    PROVIDERS,
    FreeRouter,
    RouterError,
)

# --------------------------------------------------------------------------- #
# Theme system — Cute Professional Premium / Dark Premium
# --------------------------------------------------------------------------- #

THEMES: dict[str, dict] = {
    "cute_professional_premium": {
        "name": "Cute Professional Premium",
        "bg": "#FFF0F5",
        "surface": "#FFFFFF",
        "primary": "#FF6B9D",
        "secondary": "#4ECDC4",
        "accent": "#FFD93D",
        "text": "#2D3436",
        "text_secondary": "#636E72",
        "success": "#55A355",
        "warning": "#FFA07A",
        "error": "#FF6B6B",
        "border": "#DDA0DD",
        "font": ("Segoe UI", 10),
        "font_bold": ("Segoe UI", 10, "bold"),
        "font_title": ("Segoe UI", 12, "bold"),
        "font_mono": ("Consolas", 10),
    },
    "dark_premium": {
        "name": "Dark Premium",
        "bg": "#1A1A2E",
        "surface": "#16213E",
        "primary": "#E94560",
        "secondary": "#0F3460",
        "accent": "#FFD700",
        "text": "#E2E2E2",
        "text_secondary": "#A9A9A9",
        "success": "#00FF88",
        "warning": "#FFA500",
        "error": "#FF4444",
        "border": "#4ECDC4",
        "font": ("Segoe UI", 10),
        "font_bold": ("Segoe UI", 10, "bold"),
        "font_title": ("Segoe UI", 12, "bold"),
        "font_mono": ("Consolas", 10),
    },
}


CHAT_HISTORY_PATH = os.path.join(
    os.environ.get("NVIDIA_ROUTER_HOME", os.path.expanduser("~/.nvidia_free_router")),
    "chat_history.json",
)


class NVIDIARouterGUI:
    """Main GUI application for the NVIDIA Free-Model Router."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("zcloud — NVIDIA Free-Model Router")
        self.root.geometry("1100x750")

        self.router: FreeRouter | None = None
        self.router_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.theme_name: str = "cute_professional_premium"
        self.chat_history: list[dict] = []

        self._build_ui()
        self._load_settings()
        self._refresh_providers()
        self._refresh_models()
        self._load_chat_history()
        self._apply_theme()

    # ------------------------------------------------------------------ theme

    def _apply_theme(self) -> None:
        """Apply the selected theme to all widgets."""
        theme = THEMES[self.theme_name]
        self.root.configure(bg=theme["bg"])

        style = ThemedStyle(self.root)
        style.theme_use("clam")

        style.configure("TFrame", background=theme["surface"])
        style.configure("TNotebook", background=theme["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=theme["surface"],
            foreground=theme["text"],
            font=theme["font_bold"],
            padding=[10, 5],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", theme["primary"])],
            foreground=[("selected", "white")],
        )
        style.configure(
            "TLabel",
            background=theme["surface"],
            foreground=theme["text"],
            font=theme["font"],
        )
        style.configure(
            "TButton",
            background=theme["primary"],
            foreground="white",
            font=theme["font_bold"],
            borderwidth=0,
            focuscolor=theme["accent"],
        )
        style.map(
            "TButton",
            background=[("active", theme["secondary"])],
            foreground=[("active", "white")],
        )
        style.configure(
            "TEntry",
            fieldbackground=theme["surface"],
            foreground=theme["text"],
            bordercolor=theme["border"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=theme["surface"],
            background=theme["surface"],
            foreground=theme["text"],
            arrowcolor=theme["text"],
        )
        style.configure(
            "TScrollbar",
            background=theme["surface"],
            troughcolor=theme["bg"],
            bordercolor=theme["border"],
            arrowcolor=theme["text"],
        )

        self.root.option_add("*Menu.background", theme["surface"])
        self.root.option_add("*Menu.foreground", theme["text"])
        self.root.option_add("*Menu.activeBackground", theme["primary"])
        self.root.option_add("*Menu.activeForeground", "white")

        self._apply_theme_to_widget(self.root, theme)

    def _apply_theme_to_widget(self, widget: tk.Widget, theme: dict) -> None:
        """Recursively apply theme colors to widgets."""
        widget_class = widget.winfo_class()

        if widget_class in ("ScrolledText", "Text"):
            widget.configure(
                bg=theme["surface"],
                fg=theme["text"],
                insertbackground=theme["primary"],
                selectbackground=theme["accent"],
                selectforeground=theme["text"],
                font=theme["font_mono"],
            )
        elif widget_class == "Frame":
            widget.configure(bg=theme["surface"])
        elif widget_class == "Labelframe":
            widget.configure(bg=theme["surface"], fg=theme["text"])
        elif widget_class in ("Label", "Button"):
            try:
                widget.configure(bg=theme["surface"], fg=theme["text"])
            except tk.TclError:
                pass

        try:
            for child in widget.winfo_children():
                self._apply_theme_to_widget(child, theme)
        except tk.TclError:
            pass

    def _load_chat_history(self) -> None:
        """Load chat history from disk."""
        try:
            with open(CHAT_HISTORY_PATH, encoding="utf-8") as f:
                self.chat_history = json.load(f)
            # Replay history into chat output
            for entry in self.chat_history:
                role = entry.get("role", "user")
                text = entry.get("text", "")
                model = entry.get("model", "")
                if role == "user":
                    self._append_chat(f"{text}\n", "user")
                else:
                    self._append_chat(f"\n[{model}] {text}\n", "assistant")
        except (OSError, ValueError):
            self.chat_history = []

    def _save_chat_history(self) -> None:
        """Persist chat history to disk."""
        try:
            os.makedirs(os.path.dirname(CHAT_HISTORY_PATH), exist_ok=True)
            with open(CHAT_HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(self.chat_history, f, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        # Menu
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Settings / API Keys", command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(
            label="Refresh Providers", command=self._refresh_providers
        )
        tools_menu.add_command(label="Refresh Models", command=self._refresh_models)
        tools_menu.add_command(
            label="Discover Models (API)", command=self._discover_models
        )

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)

        # Main notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ===== Chat Tab =====
        self.chat_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.chat_frame, text="Chat")

        ctrl = ttk.Frame(self.chat_frame)
        ctrl.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(ctrl, text="Route:").pack(side=tk.LEFT)
        self.route_var = tk.StringVar(value="auto")
        self.route_combo = ttk.Combobox(
            ctrl,
            textvariable=self.route_var,
            width=15,
            values=["auto", "general", "code", "reasoning", "fast", "vision"],
            state="readonly",
        )
        self.route_combo.pack(side=tk.LEFT, padx=5)

        ttk.Label(ctrl, text="Model:").pack(side=tk.LEFT, padx=(10, 0))
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(
            ctrl,
            textvariable=self.model_var,
            width=30,
            state="readonly",
        )
        self.model_combo.pack(side=tk.LEFT, padx=5)
        self.model_combo.set("auto")

        ttk.Label(ctrl, text="Max Tokens:").pack(side=tk.LEFT, padx=(10, 0))
        self.max_tokens_var = tk.IntVar(value=1024)
        ttk.Spinbox(
            ctrl,
            from_=1,
            to=8192,
            textvariable=self.max_tokens_var,
            width=8,
        ).pack(side=tk.LEFT, padx=5)

        self.stream_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ctrl,
            text="Stream",
            variable=self.stream_var,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(ctrl, text="Send", command=self._send_chat).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(ctrl, text="Clear", command=self._clear_chat).pack(side=tk.RIGHT)

        self.chat_output = scrolledtext.ScrolledText(
            self.chat_frame,
            wrap=tk.WORD,
            font=("Consolas", 11),
        )
        self.chat_output.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chat_output.config(state=tk.DISABLED)

        input_frame = ttk.Frame(self.chat_frame)
        input_frame.pack(fill=tk.X, padx=5, pady=5)

        self.chat_input = scrolledtext.ScrolledText(
            input_frame,
            wrap=tk.WORD,
            height=4,
            font=("Consolas", 11),
        )
        self.chat_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.chat_input.bind("<Return>", self._on_enter)

        btn_frame = ttk.Frame(input_frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(btn_frame, text="Send", command=self._send_chat).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Stop", command=self._stop_chat).pack(
            fill=tk.X, pady=2
        )

        self.root.bind("<Control-Return>", lambda e: self._send_chat())

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, relief=tk.SUNKEN
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # ===== Models Tab =====
        self.models_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.models_frame, text="Models")

        models_ctrl = ttk.Frame(self.models_frame)
        models_ctrl.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(models_ctrl, text="Provider:").pack(side=tk.LEFT)
        self.model_provider_var = tk.StringVar(value="All")
        self.model_provider_combo = ttk.Combobox(
            models_ctrl,
            textvariable=self.model_provider_var,
            width=15,
            state="readonly",
        )
        self.model_provider_combo.pack(side=tk.LEFT, padx=5)

        self.model_free_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            models_ctrl,
            text="Free only",
            variable=self.model_free_var,
            command=self._refresh_models_table,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(models_ctrl, text="Refresh", command=self._refresh_models).pack(
            side=tk.RIGHT, padx=5
        )

        columns = ("model", "provider", "tier", "routes", "description")
        self.models_tree = ttk.Treeview(
            self.models_frame,
            columns=columns,
            show="headings",
            height=15,
        )
        for col, width in zip(columns, [200, 120, 60, 180, 400]):
            self.models_tree.heading(col, text=col.title())
            self.models_tree.column(col, width=width)
        self.models_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ===== Providers Tab =====
        self.providers_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.providers_frame, text="Providers")

        prov_ctrl = ttk.Frame(self.providers_frame)
        prov_ctrl.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(prov_ctrl, text="Refresh", command=self._refresh_providers).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(
            prov_ctrl, text="Add Provider Key", command=self._add_provider_key
        ).pack(side=tk.RIGHT, padx=5)

        prov_columns = ("provider", "base_url", "keys", "env_var")
        self.providers_tree = ttk.Treeview(
            self.providers_frame,
            columns=prov_columns,
            show="headings",
            height=10,
        )
        for col, width in zip(prov_columns, [150, 300, 60, 150]):
            self.providers_tree.heading(col, text=col.title())
            self.providers_tree.column(col, width=width)
        self.providers_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Key rotation status
        key_frame = ttk.LabelFrame(self.providers_frame, text="Key Rotation Status")
        key_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        key_columns = ("key", "provider", "status", "ok", "fail", "429")
        self.key_tree = ttk.Treeview(
            key_frame,
            columns=key_columns,
            show="headings",
            height=8,
        )
        for col, width in zip(key_columns, [220, 140, 80, 60, 60, 60]):
            self.key_tree.heading(col, text=col.title())
            self.key_tree.column(col, width=width)
        self.key_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ===== Stats Tab =====
        self.stats_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.stats_frame, text="Stats")

        stats_ctrl = ttk.Frame(self.stats_frame)
        stats_ctrl.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(stats_ctrl, text="Refresh Stats", command=self._refresh_stats).pack(
            side=tk.RIGHT, padx=5
        )

        stats_columns = ("model", "ok", "fail", "429", "avg_s")
        self.stats_tree = ttk.Treeview(
            self.stats_frame,
            columns=stats_columns,
            show="headings",
            height=15,
        )
        for col, width in zip(stats_columns, [200, 80, 80, 80, 80]):
            self.stats_tree.heading(col, text=col.title())
            self.stats_tree.column(col, width=width)
        self.stats_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ===== Model Comparison Tab =====
        self.compare_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.compare_frame, text="Compare Models")

        comp_ctrl = ttk.Frame(self.compare_frame)
        comp_ctrl.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(comp_ctrl, text="Model A:").pack(side=tk.LEFT, padx=(0, 5))
        self.comp_model_a_var = tk.StringVar()
        self.comp_model_a_combo = ttk.Combobox(
            comp_ctrl,
            textvariable=self.comp_model_a_var,
            width=25,
            state="readonly",
        )
        self.comp_model_a_combo.pack(side=tk.LEFT, padx=5)

        ttk.Label(comp_ctrl, text="Model B:").pack(side=tk.LEFT, padx=(15, 5))
        self.comp_model_b_var = tk.StringVar()
        self.comp_model_b_combo = ttk.Combobox(
            comp_ctrl,
            textvariable=self.comp_model_b_var,
            width=25,
            state="readonly",
        )
        self.comp_model_b_combo.pack(side=tk.LEFT, padx=5)

        ttk.Label(comp_ctrl, text="Prompt:").pack(side=tk.LEFT, padx=(15, 5))
        self.comp_prompt_entry = ttk.Entry(comp_ctrl, width=40)
        self.comp_prompt_entry.pack(side=tk.LEFT, padx=5)

        ttk.Button(comp_ctrl, text="Compare", command=self._compare_models).pack(
            side=tk.LEFT, padx=5
        )

        self.comp_paned = ttk.PanedWindow(self.compare_frame, orient=tk.HORIZONTAL)
        self.comp_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.comp_output_a = scrolledtext.ScrolledText(
            self.comp_paned,
            wrap=tk.WORD,
            font=("Consolas", 10),
            width=40,
        )
        self.comp_paned.add(self.comp_output_a, weight=1)

        self.comp_output_b = scrolledtext.ScrolledText(
            self.comp_paned,
            wrap=tk.WORD,
            font=("Consolas", 10),
            width=40,
        )
        self.comp_paned.add(self.comp_output_b, weight=1)

        # ===== Settings Tab =====
        self.settings_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_frame, text="Settings")

        sett_frame = ttk.Frame(self.settings_frame)
        sett_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(
            sett_frame, text="API Keys (comma-separated):", font=("bold", 11)
        ).pack(anchor=tk.W, pady=(0, 5))
        self.api_keys_text = scrolledtext.ScrolledText(
            sett_frame,
            height=6,
            font=("Consolas", 10),
        )
        self.api_keys_text.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(sett_frame, text="Router Configuration:", font=("bold", 11)).pack(
            anchor=tk.W, pady=(10, 5)
        )

        cfg_frame = ttk.Frame(sett_frame)
        cfg_frame.pack(fill=tk.X, pady=5)

        ttk.Label(cfg_frame, text="RPM:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.cfg_rpm = tk.IntVar(value=35)
        ttk.Spinbox(
            cfg_frame,
            from_=1,
            to=1000,
            textvariable=self.cfg_rpm,
            width=10,
        ).grid(row=0, column=1, sticky=tk.W, padx=5)

        ttk.Label(cfg_frame, text="Cache TTL (s):").grid(
            row=1, column=0, sticky=tk.W, padx=5
        )
        self.cfg_cache_ttl = tk.IntVar(value=3600)
        ttk.Spinbox(
            cfg_frame,
            from_=0,
            to=86400,
            textvariable=self.cfg_cache_ttl,
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, padx=5)

        ttk.Label(cfg_frame, text="Timeout (s):").grid(
            row=2, column=0, sticky=tk.W, padx=5
        )
        self.cfg_timeout = tk.IntVar(value=90)
        ttk.Spinbox(
            cfg_frame,
            from_=5,
            to=300,
            textvariable=self.cfg_timeout,
            width=10,
        ).grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(cfg_frame, text="Max Wait (s):").grid(
            row=3, column=0, sticky=tk.W, padx=5
        )
        self.cfg_max_wait = tk.IntVar(value=60)
        ttk.Spinbox(
            cfg_frame,
            from_=0,
            to=600,
            textvariable=self.cfg_max_wait,
            width=10,
        ).grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Button(
            sett_frame,
            text="Save Settings",
            command=self._save_settings,
        ).pack(anchor=tk.E, pady=10)

    # ------------------------------------------------------------------ Settings

    def _on_tab_changed(self, event: tk.Event) -> None:
        """Refresh stats when the Stats tab is selected."""
        selected = self.notebook.select()
        tab_text = self.notebook.tab(selected, "text")
        if tab_text == "Stats":
            self._refresh_stats()

    def _open_settings(self) -> None:
        """Switch to the Settings tab."""
        self.notebook.select(self.settings_frame)

    def _load_settings(self) -> None:
        keys = os.environ.get("NVIDIA_API_KEYS", "")
        self.api_keys_text.insert("1.0", keys)

    def _save_settings(self) -> None:
        keys = self.api_keys_text.get("1.0", tk.END).strip()
        os.environ["NVIDIA_API_KEYS"] = keys
        zrouter.CFG.rpm = self.cfg_rpm.get()
        zrouter.CFG.cache_ttl = self.cfg_cache_ttl.get()
        zrouter.CFG.timeout = self.cfg_timeout.get()
        zrouter.CFG.max_wait = self.cfg_max_wait.get()
        messagebox.showinfo("Settings", "Settings saved.")

    # ------------------------------------------------------------------ Providers

    def _refresh_providers(self) -> None:
        for item in self.providers_tree.get_children():
            self.providers_tree.delete(item)

        for p in PROVIDERS.list_providers():
            self.providers_tree.insert(
                "",
                tk.END,
                values=(p["name"], p["base_url"], p["key_count"], p["env_var"]),
            )

        self._refresh_key_status()

    def _refresh_key_status(self) -> None:
        """Refresh per-key rotation status (ready/benched/dead)."""
        for item in self.key_tree.get_children():
            self.key_tree.delete(item)

        if self.router is None:
            return

        for k in self.router.keys:
            st = (
                "DEAD (401/403)"
                if k.dead
                else "ready"
                if k.is_ready()
                else f"limited {k.benched_until - time.time():.0f}s"
            )
            self.key_tree.insert(
                "",
                tk.END,
                values=(k.label, k.provider, st, k.ok, k.fail, k.hits_429),
            )

    def _add_provider_key(self) -> None:
        provider = simpledialog.askstring(
            "Provider",
            "Provider name (e.g. Groq, OpenRouter):",
        )
        if not provider:
            return
        key = simpledialog.askstring(
            "API Key",
            f"API key for {provider}:",
            show="*",
        )
        if not key:
            return
        base_url = simpledialog.askstring(
            "Base URL",
            f"Base URL for {provider} (or leave blank for default):",
        )
        env_var = simpledialog.askstring(
            "Env Var",
            f"Environment variable name (e.g. {provider.upper()}_API_KEYS):",
        )

        cfg = PROVIDERS.get(provider)
        if cfg:
            keys_list = list(cfg["api_keys"])
            keys_list.append(key.strip())
            cfg["api_keys"] = keys_list
        else:
            PROVIDERS.providers[provider] = {
                "api_keys": [key.strip()],
                "base_url": base_url or zrouter.CFG.base_url,
                "env_var": env_var or f"{provider.upper()}_API_KEYS",
            }

        self._refresh_providers()
        messagebox.showinfo("Provider", f"Key added for {provider}.")

    def _refresh_stats(self) -> None:
        """Refresh model statistics from the router stats store."""
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)

        if self.router is None:
            return

        stats = self.router.stats
        if stats is None or not stats.data:
            return

        for model, v in sorted(
            stats.data["models"].items(),
            key=lambda x: x[1]["ok"] + x[1]["fail"],
            reverse=True,
        ):
            ok = v["ok"]
            fail = v["fail"]
            n429 = v["429"]
            avg_s = v["lat_sum"] / ok if ok else 0
            self.stats_tree.insert(
                "",
                tk.END,
                values=(model, ok, fail, n429, f"{avg_s:.2f}"),
            )

    # ------------------------------------------------------------------ Models

    def _refresh_models(self) -> None:
        self._refresh_models_table()
        providers = self._get_selected_provider()
        free_only = self.model_free_var.get()

        models = CATALOG.models
        if providers != "All":
            models = CATALOG.by_provider(providers)
        if free_only:
            models = CATALOG.list_free()

        model_ids = sorted([m.get("id", "") for m in models])
        self.model_combo["values"] = ["auto"] + model_ids
        if not self.model_var.get():
            self.model_var.set("auto")

        self.comp_model_a_combo["values"] = model_ids
        self.comp_model_b_combo["values"] = model_ids
        if model_ids and not self.comp_model_a_var.get():
            self.comp_model_a_var.set(model_ids[0])
        if len(model_ids) > 1 and not self.comp_model_b_var.get():
            self.comp_model_b_var.set(model_ids[1])

        providers_list = ["All"] + sorted(
            {m.get("provider", "unknown") for m in CATALOG.models}
        )
        self.model_provider_combo["values"] = providers_list

    def _get_selected_provider(self) -> str:
        return self.model_provider_var.get()

    def _refresh_models_table(self) -> None:
        for item in self.models_tree.get_children():
            self.models_tree.delete(item)

        models = CATALOG.models
        provider = self._get_selected_provider()
        if provider != "All":
            models = CATALOG.by_provider(provider)
        if self.model_free_var.get():
            models = CATALOG.list_free()

        for m in sorted(models, key=lambda x: str(x.get("id", ""))):
            self.models_tree.insert(
                "",
                tk.END,
                values=(
                    m.get("id", ""),
                    m.get("provider", "unknown"),
                    "free" if m.get("free") else "paid",
                    ",".join(m.get("routes", [])),
                    m.get("description", ""),
                ),
            )

    def _discover_models(self) -> None:
        if not self.router:
            messagebox.showwarning(
                "Discovery",
                "Initialize router first (go to Chat and click Send).",
            )
            return

        def _discover() -> None:
            self.status_var.set("Discovering models...")
            try:
                count = self.router.available_ids(refresh=True)
                self.root.after(0, lambda: self._refresh_models())
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Discovery",
                        f"Discovered {len(count)} model(s).",
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0,
                    lambda e=exc: messagebox.showerror("Discovery", str(e)),
                )
            finally:
                self.root.after(0, lambda: self.status_var.set("Ready"))

        threading.Thread(target=_discover, daemon=True).start()

    def _compare_models(self) -> None:
        model_a = self.comp_model_a_var.get()
        model_b = self.comp_model_b_var.get()
        prompt = self.comp_prompt_entry.get().strip()

        if not model_a or not model_b:
            messagebox.showwarning(
                "Comparison",
                "Please select both models to compare.",
            )
            return
        if not prompt:
            messagebox.showwarning("Comparison", "Please enter a prompt.")
            return
        if not self.router:
            try:
                self._ensure_router()
            except RouterError as exc:
                messagebox.showerror("No API Key", str(exc))
                return

        self.comp_output_a.config(state=tk.NORMAL)
        self.comp_output_b.config(state=tk.NORMAL)
        self.comp_output_a.delete("1.0", tk.END)
        self.comp_output_b.delete("1.0", tk.END)
        self.comp_output_a.insert(
            tk.END,
            f"Model: {model_a}\n{'=' * 50}\n\n",
        )
        self.comp_output_b.insert(
            tk.END,
            f"Model: {model_b}\n{'=' * 50}\n\n",
        )
        self.comp_output_a.config(state=tk.DISABLED)
        self.comp_output_b.config(state=tk.DISABLED)
        self.status_var.set("Comparing models...")

        def _compare() -> None:
            try:
                router = self._ensure_router()
                msgs = [{"role": "user", "content": prompt}]

                out_a = router.chat(msgs, model=model_a, max_tokens=512)
                text_a = out_a["text"]
                self.root.after(
                    0,
                    lambda t=text_a: self._update_comp_output(self.comp_output_a, t),
                )

                out_b = router.chat(msgs, model=model_b, max_tokens=512)
                text_b = out_b["text"]
                self.root.after(
                    0,
                    lambda t=text_b: self._update_comp_output(self.comp_output_b, t),
                )
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0,
                    lambda e=exc: messagebox.showerror("Compare Error", str(e)),
                )
            finally:
                self.root.after(0, lambda: self.status_var.set("Ready"))

        threading.Thread(target=_compare, daemon=True).start()

    def _update_comp_output(
        self,
        widget: scrolledtext.ScrolledText,
        text: str,
    ) -> None:
        widget.config(state=tk.NORMAL)
        widget.insert(tk.END, text)
        widget.config(state=tk.DISABLED)
        widget.see(tk.END)

    # ------------------------------------------------------------------ Chat

    def _ensure_router(self) -> FreeRouter:
        if self.router is None:
            keys_str = self.api_keys_text.get("1.0", tk.END).strip()
            os.environ["NVIDIA_API_KEYS"] = keys_str
            self.router = FreeRouter()
        return self.router

    def _send_chat(self) -> None:
        prompt = self.chat_input.get("1.0", tk.END).strip()
        if not prompt:
            return
        if not self.router:
            try:
                self._ensure_router()
            except RouterError as exc:
                messagebox.showerror("No API Key", str(exc))
                return

        self._append_chat(f"You: {prompt}\n", "user")
        self.chat_history.append(
            {
                "role": "user",
                "text": prompt,
                "timestamp": datetime.datetime.now().isoformat(),
            }
        )
        self.chat_input.delete("1.0", tk.END)
        self.stop_event.clear()

        def _chat() -> None:
            try:
                router = self._ensure_router()
                route = self.route_var.get()
                model = self.model_var.get() or None
                max_tokens = self.max_tokens_var.get()
                stream = self.stream_var.get()

                msgs = [{"role": "user", "content": prompt}]

                if stream:
                    for delta in router.chat_stream(
                        msgs,
                        route=route,
                        model=model,
                        max_tokens=max_tokens,
                    ):
                        if self.stop_event.is_set():
                            break
                        self.root.after(
                            0,
                            lambda d=delta: self._append_chat(d, "stream"),
                        )
                    if not self.stop_event.is_set():
                        self.root.after(
                            0,
                            lambda: self._append_chat("\n", "stream"),
                        )
                else:
                    out = router.chat(
                        msgs,
                        route=route,
                        model=model,
                        max_tokens=max_tokens,
                    )
                    text = out["text"]
                    model_used = out["model"]
                    self.root.after(
                        0,
                        lambda t=text, m=model_used: self._append_chat(
                            f"\n[{m}] {t}\n",
                            "assistant",
                        ),
                    )
                    self.chat_history.append(
                        {
                            "role": "assistant",
                            "text": text,
                            "model": model_used,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                    )
                    self._save_chat_history()
            except RouterError as exc:
                self.root.after(
                    0,
                    lambda e=exc: messagebox.showerror("Router Error", str(e)),
                )
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: messagebox.showerror("Error", str(e)))
            finally:
                self.root.after(0, lambda: self.status_var.set("Ready"))

        self.status_var.set("Sending...")
        self.router_thread = threading.Thread(target=_chat, daemon=True)
        self.router_thread.start()

    def _stop_chat(self) -> None:
        self.stop_event.set()
        self.status_var.set("Stopping...")

    def _clear_chat(self) -> None:
        self.chat_output.config(state=tk.NORMAL)
        self.chat_output.delete("1.0", tk.END)
        self.chat_output.config(state=tk.DISABLED)

    def _on_enter(self, event: tk.Event) -> str:
        if event.state & 0x4:  # Ctrl pressed
            self._send_chat()
            return "break"
        return ""

    def _append_chat(self, text: str, tag: str = "") -> None:
        self.chat_output.config(state=tk.NORMAL)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if tag == "user":
            self.chat_output.insert(tk.END, f"[{timestamp}] ", "ts")
            self.chat_output.insert(tk.END, text, "user")
        elif tag == "assistant":
            self.chat_output.insert(tk.END, f"[{timestamp}] ", "ts")
            self.chat_output.insert(tk.END, text, "assistant")
        elif tag == "stream":
            self.chat_output.insert(tk.END, text, "stream")
        else:
            self.chat_output.insert(tk.END, f"[{timestamp}] {text}", "sys")
        self.chat_output.tag_config("ts", foreground="#666666")
        self.chat_output.tag_config(
            "user",
            foreground="#0066cc",
            font=("Consolas", 11, "bold"),
        )
        self.chat_output.tag_config(
            "assistant",
            foreground="#006600",
            font=("Consolas", 11, "bold"),
        )
        self.chat_output.tag_config("stream", foreground="#000000")
        self.chat_output.tag_config(
            "sys",
            foreground="#888888",
            font=("Consolas", 10, "italic"),
        )
        self.chat_output.see(tk.END)
        self.chat_output.config(state=tk.DISABLED)

    # ------------------------------------------------------------------ About

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About",
            "zcloud — NVIDIA Free-Model Router GUI\n\n"
            "A desktop GUI for the zrouter.py router.\n"
            "Routes chats through free NVIDIA NIM models.\n\n"
            "Built with tkinter.",
        )


def main() -> None:
    root = tk.Tk()
    NVIDIARouterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
