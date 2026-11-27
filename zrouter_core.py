"""Validated provider registry contracts for zrouter."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def validate_base_url(value: str) -> str:
    """Normalize an upstream URL and reject unsafe plaintext endpoints."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            "provider base_url must be a non-empty URL without surrounding whitespace"
        )
    if any(ord(char) < 32 for char in value):
        raise ValueError("provider base_url contains control characters")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("provider base_url is malformed") from exc
    if parsed.scheme not in {"https", "http"} or not hostname:
        raise ValueError("provider base_url must use HTTPS and include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("provider base_url must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("provider base_url must not contain a query or fragment")
    if parsed.scheme == "http":
        is_loopback = hostname.casefold() == "localhost"
        try:
            is_loopback = is_loopback or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        if not is_loopback:
            raise ValueError(
                "plaintext HTTP is allowed only for loopback provider endpoints"
            )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    """Immutable provider endpoint and credential-source declaration."""

    name: str
    base_url: str
    env_var: str
    api_keys: tuple[str, ...]


class ProviderRegistry:
    """Validated registry for OpenAI-compatible upstream provider definitions."""

    def __init__(self, definitions: tuple[ProviderDefinition, ...] = ()) -> None:
        names = [item.name.casefold() for item in definitions]
        if len(names) != len(set(names)):
            raise ValueError("provider names must be unique (case-insensitive)")
        self.definitions = tuple(definitions)

    @classmethod
    def from_config(cls, data: object, default_base_url: str) -> ProviderRegistry:
        if not isinstance(data, dict):
            raise TypeError("provider config root must be a JSON object")
        raw = data.get("providers", {})
        if not isinstance(raw, dict):
            raise TypeError("provider config 'providers' must be an object")
        fallback = validate_base_url(default_base_url)
        definitions: list[ProviderDefinition] = []
        for name, config in raw.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > 64
                or any(ord(char) < 32 for char in name)
            ):
                raise ValueError(
                    "provider names must be non-empty strings of at most 64 characters"
                )
            if not isinstance(config, dict):
                raise TypeError(f"provider {name!r} configuration must be an object")
            keys = config.get("api_keys", [])
            if not isinstance(keys, list) or any(
                not isinstance(key, str) for key in keys
            ):
                raise ValueError(
                    f"provider {name!r} api_keys must be a list of strings"
                )
            env_var = config.get("env_var", "")
            if not isinstance(env_var, str) or (
                env_var and not _ENV_VAR_RE.fullmatch(env_var)
            ):
                raise ValueError(
                    f"provider {name!r} env_var must be a valid "
                    "environment variable name"
                )
            base_url = validate_base_url(config.get("base_url", fallback))
            definitions.append(
                ProviderDefinition(
                    name=name.strip(),
                    base_url=base_url,
                    env_var=env_var,
                    api_keys=tuple(key.strip() for key in keys if key.strip()),
                )
            )
        return cls(tuple(definitions))

    def get(self, name: str) -> ProviderDefinition | None:
        return next((item for item in self.definitions if item.name == name), None)

    def as_mapping(self) -> dict[str, dict[str, object]]:
        return {
            item.name: {
                "api_keys": list(item.api_keys),
                "base_url": item.base_url,
                "env_var": item.env_var,
            }
            for item in self.definitions
        }

    def all_keys(self) -> list[tuple[str, str, str]]:
        return [
            (item.name, item.base_url, key)
            for item in self.definitions
            for key in item.api_keys
        ]

    def list_providers(self) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "base_url": item.base_url,
                "env_var": item.env_var,
                "key_count": len(item.api_keys),
                "has_keys": bool(item.api_keys),
            }
            for item in sorted(
                self.definitions, key=lambda entry: entry.name.casefold()
            )
        ]
