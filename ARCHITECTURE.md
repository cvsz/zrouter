# zrouter architecture

## Design intent

Adopt selected architectural patterns from OpenMausBot without importing its Electron/React runtime or copying implementation code. zrouter remains a Python-first router with a stable CLI and OpenAI-compatible HTTP surface.

## Runtime layers

```text
CLI / GUI / TUI / Web Dashboard / OpenAI clients
                    |
          Compatibility Interfaces
                    |
       Request Validation + Auth Boundary
                    |
         Router Application / Policy
          |        |          |
      Model     Provider    Failover /
      Catalog   Registry    Rate Limiter
          |        |          |
          +--------+----------+
                    |
           HTTP Transport (requests)
                    |
          NVIDIA NIM / compatible APIs

      Bot utilities remain a separate bounded subsystem
      with explicit storage and approval boundaries.
```

## OpenMausBot patterns adapted

| OpenMausBot concept | zrouter adaptation | Constraint |
|---|---|---|
| Driver/provider registry | `ProviderRegistry` and immutable `ProviderDefinition` | OpenAI-compatible HTTP transport; no Node runtime |
| Dynamic model catalog | `ModelsCatalog` + explicit route allowlist | Discovery never establishes pricing |
| Event-driven lifecycle | Router outcomes and health/statistics boundaries | Add events only where consumers exist; avoid unused event bus |
| Streaming lifecycle | Existing SSE response ownership and close-on-cancel rules | Always close upstream response |
| Permission broker | Proxy bearer auth and explicit bot approval boundaries | No unauthenticated public bind |
| Local-first persistence | JSON config/statistics and bot stores | Restrict file permissions; document encryption status accurately |

## Current module boundaries

- `zrouter.py`: compatibility facade, CLI, router application, request/response contracts.
- `zrouter_core.py`: provider definitions, registry, and endpoint validation.
- `zrouter_runtime.py`: thread-safe rate limiter, statistics persistence, TTL/LRU cache, and key masking primitives; `zrouter.py` re-exports the stable names.
- `zrouter_bot_models.py`: bot enums and serializable domain models; this is the canonical definition module.
- `zrouter_bot_storage.py`: local bot-home paths, vault persistence, and per-bot memory persistence.
- `zrouter_bot.py`: bot services/managers and compatibility re-exports for model and storage types. Existing `from zrouter_bot import ...` imports remain supported.
- `web_app.py`: Flask web adapter; delegates inference to `FreeRouter`.
- `models.json`: curated model metadata. `free: true` is an explicit curation decision, not a value inferred from model names.

## Routing and cost invariants

1. Live `/models` data answers whether an upstream model is currently available.
2. The route configuration answers whether a model is allowed to receive traffic.
3. A model name, route category, or successful API response does not prove that a model is free.
4. Discovery marks newly observed models as `pricing_status=unverified` and `free=false`.
5. If no configured route candidate is available, return a controlled 404. Never fall back to every live model.
6. Route patterns are exact by default. Explicit glob syntax is supported for intentional groups.

## Compatibility strategy

Keep public imports and commands in `zrouter.py` stable while extracting internal contracts into small modules. New modules must have direct unit tests. Do not replace the Python transport or add a database/service unless measurable requirements justify the operational cost.

## Known follow-up audit items

- `zrouter_bot.Vault` stores plaintext JSON. POSIX file/directory modes are restricted to `0600`/`0700`, but that does not encrypt data or protect against the same OS user; do not store high-value production credentials there.
- The bot file handler and JSON stores need a dedicated permission, atomic-write, and corruption-recovery review.
- The existing README/validation report contains historical coverage/build claims that must be replaced with evidence from exact CI commits.
