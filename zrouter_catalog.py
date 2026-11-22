"""Curated model catalog and provider-discovery metadata."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from zrouter_contracts import RouterError
from zrouter_config import _resource_path

if TYPE_CHECKING:
    from zrouter_application import FreeRouter

MODELS_PATH = _resource_path("models.json")


class ModelsCatalog:
    """Load and query the NVIDIA NIM models catalog (free/paid/provider metadata)."""

    def __init__(self, path: str = MODELS_PATH) -> None:
        self.path = path
        self.models: list[dict[str, Any]] = []
        self.providers: dict[str, str] = {}
        self.deny: list[str] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.models = (
            data.get("models", []) if isinstance(data.get("models"), list) else []
        )
        self.providers = (
            data.get("providers", {}) if isinstance(data.get("providers"), dict) else {}
        )
        self.deny = data.get("deny", []) if isinstance(data.get("deny"), list) else []
        self._by_id = {
            m["id"]: m for m in self.models if isinstance(m, dict) and "id" in m
        }

    def get(self, model_id: str) -> dict[str, Any] | None:
        """Return catalog entry for a model id, or None if not listed."""
        return self._by_id.get(model_id)

    def is_free(self, model_id: str) -> bool:
        entry = self.get(model_id)
        return bool(entry and entry.get("free", False))

    def provider(self, model_id: str) -> str:
        entry = self.get(model_id)
        if entry:
            return str(entry.get("provider", "unknown"))
        return "unknown"

    def routes(self, model_id: str) -> list[str]:
        entry = self.get(model_id)
        return list(entry.get("routes", [])) if entry else []

    def is_denied(self, model_id: str) -> bool:
        low = model_id.lower()
        return any(d in low for d in self.deny)

    def list_free(self) -> list[dict[str, Any]]:
        return [m for m in self.models if m.get("free")]

    def list_paid(self) -> list[dict[str, Any]]:
        return [m for m in self.models if not m.get("free")]

    def by_provider(self, provider: str) -> list[dict[str, Any]]:
        return [m for m in self.models if m.get("provider") == provider]

    # ------------------------------------------------------------------- discovery helpers

    @staticmethod
    def _detect_provider(model_id: str) -> str:
        """Heuristically detect the model provider from its ID."""
        low = model_id.lower()
        if "nemotron" in low or low.startswith("nv-") or "embed" in low:
            return "NVIDIA"
        if "llama" in low:
            return "Meta"
        if "gemma" in low:
            return "Google"
        if "deepseek" in low:
            return "DeepSeek"
        if "glm" in low:
            return "Zhipu AI"
        if "mistral" in low:
            return "Mistral AI"
        if "minimax" in low:
            return "MiniMax"
        if "seed" in low:
            return "Seed"
        return "unknown"

    @staticmethod
    def _detect_routes(model_id: str, deny: list[str] | None = None) -> list[str]:
        """Heuristically assign router routes to a model ID."""
        low = model_id.lower()
        deny = deny or []
        if any(d in low for d in deny):
            return []  # denied models get no chat routes
        routes: list[str] = []
        if "embed" in low:
            routes.append("embed")
        if any(
            k in low for k in ("code", "coder", "deepseek", "glm", "minimax", "seed")
        ):
            routes.append("code")
        if any(
            k in low
            for k in (
                "reasoning",
                "nemotron",
                "llama",
                "deepseek",
                "glm",
                "seed",
                "mistral-large",
            )
        ):
            routes.append("reasoning")
        if any(k in low for k in ("mini", "small", "8b", "4b", "2b", "n-e2b", "n-e4b")):
            routes.append("fast")
        if any(k in low for k in ("vision", "vl", "multimodal", "image")):
            routes.append("vision")
        if not routes:
            routes.append("general")
        return routes

    @staticmethod
    def _is_free(
        model_id: str, routes: list[str], deny: list[str] | None = None
    ) -> bool:
        """Never infer pricing from a model ID or route classification."""
        _ = (model_id, routes, deny)
        return False

    @classmethod
    def discover_from_api(
        cls,
        model_ids: list[str],
        deny: list[str] | None = None,
        providers: dict[str, str] | None = None,
    ) -> ModelsCatalog:
        """Classify a list of model IDs (from the NVIDIA API) into a catalog."""
        deny = deny or []
        providers = providers or {}
        models: list[dict[str, Any]] = []
        for mid in sorted(set(model_ids)):
            routes = cls._detect_routes(mid, deny)
            models.append(
                {
                    "id": mid,
                    "provider": providers.get(mid, cls._detect_provider(mid)),
                    "free": False,
                    "pricing_status": "unverified",
                    "routes": routes,
                    "description": f"Auto-discovered {mid}",
                }
            )
        cat = cls.__new__(cls)
        cat.path = MODELS_PATH
        cat.models = models
        cat.providers = dict(providers)
        cat.deny = list(deny)
        cat._by_id = {m["id"]: m for m in models}
        return cat

    def update_from_router(self, router: FreeRouter) -> int:
        """Fetch the live model list from the NVIDIA API and merge into this catalog."""
        try:
            live = router.available_ids(refresh=True)
        except RouterError:
            return 0
        if not live:
            return 0
        discovered = self.discover_from_api(
            live, deny=self.deny, providers=self.providers
        )
        # Preserve descriptions for known models; set new ones
        for m in discovered.models:
            existing = self._by_id.get(m["id"])
            if existing:
                if existing.get("description"):
                    m["description"] = existing["description"]
                m["free"] = existing.get("free") is True
                m["pricing_status"] = existing.get(
                    "pricing_status",
                    "curated" if existing.get("free") is True else "unverified",
                )
        self.models = discovered.models
        self._by_id = discovered._by_id
        return len(self.models)

    def save(self, path: str | None = None) -> None:
        """Persist the catalog to models.json."""
        target = path or self.path
        data: dict[str, Any] = {
            "models": self.models,
            "providers": self.providers,
            "deny": self.deny,
        }
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, target)


CATALOG = ModelsCatalog()
