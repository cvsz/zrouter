# API Reference — NVIDIA Free-Model Router Proxy

The router exposes an OpenAI-compatible REST API at `http://localhost:8000/v1`.

## Base URL

```
http://localhost:8000/v1
```

## Authentication

If `ROUTER_TOKEN` is set, all endpoints except `/health` require:

```
Authorization: Bearer <ROUTER_TOKEN>
```

## Endpoints

### GET /health

Health check endpoint. No authentication required.

**Response:**
```json
{
  "ok": true,
  "keys": [
    {
      "key": "nvapi-aaa...bbb",
      "provider": "NVIDIA",
      "status": "ready",
      "ok": 10,
      "429": 0
    }
  ]
}
```

### GET /v1/models

List all allowlisted models. Requires authentication if `ROUTER_TOKEN` is set.

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "auto",
      "object": "model",
      "owned_by": "nvidia-free-router"
    },
    {
      "id": "free-general",
      "object": "model",
      "owned_by": "nvidia-free-router"
    },
    {
      "id": "gemma-3-27b",
      "object": "model",
      "owned_by": "nvidia-free-router"
    }
  ]
}
```

### POST /v1/chat/completions

Create a chat completion. Supports both streaming and non-streaming requests.

**Request:**
```json
{
  "model": "auto",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "write a regex for emails"}
  ],
  "max_tokens": 1024,
  "temperature": 0.7,
  "stream": false,
  "tools": null,
  "response_format": null,
  "images": null
}
```

**Response (non-streaming):**
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gemma-3-27b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Here is a regex for emails: ..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 25,
    "total_tokens": 35
  }
}
```

**Response headers:**
- `X-Router-Model` — The model that handled the request
- `X-Router-Key` — The API key used (masked)
- `X-Router-Cache` — Whether the response was cached (`true`/`false`)

### POST /v1/embeddings

Create embeddings. Requires authentication if `ROUTER_TOKEN` is set.

**Request:**
```json
{
  "model": "nv-embed",
  "input": "text to embed"
}
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "embedding": [0.1, 0.2, 0.3, ...]
    }
  ],
  "model": "nv-embed",
  "usage": {
    "prompt_tokens": 5,
    "total_tokens": 5
  }
}
```

### GET /v1/models (Router-specific)

The router's `/v1/models` endpoint returns allowlisted models plus route shortcuts:
- `auto` — Automatic prompt classification
- `free-general` — General route
- `free-code` — Code route
- `free-reasoning` — Reasoning route
- `free-fast` — Fast route
- `free-vision` — Vision route

## Model Selection

The `model` parameter accepts:
- `auto` — Auto-route based on prompt classification
- `free-<route>` — Force a specific route (e.g., `free-code`)
- `route:<route>` — Same as `free-<route>`
- Any substring of an allowlisted model ID (e.g., `glm-4.7`, `gemma-3-27b`)
- Exact model ID from the allowlist

## Rate Limiting

Each API key has a per-key rate limit (default 35 RPM). When a key hits the limit:
- The key is "benched" for the duration specified by `Retry-After` or the configured cooldown
- The same model is retried on the next available key
- If all keys are limited, the router waits up to `NVIDIA_MAX_WAIT` seconds

## Error Responses

| Status | Meaning |
|--------|---------|
| 400 | Invalid request (unknown route, invalid body) |
| 401 | Unauthorized (invalid or missing token) |
| 403 | Forbidden (key rejected) |
| 404 | Model not found or not allowlisted |
| 413 | Request entity too large (> 16 MiB) |
| 429 | Rate limited |
| 502 | All models/keys failed |

**Error body:**
```json
{
  "error": {
    "message": "error details",
    "type": "router_error",
    "code": 400
  }
}
```

## Caching

Responses are cached when:
- `temperature == 0`
- No `tools` specified
- Non-streaming request

Cache TTL is configurable via `NVIDIA_CACHE_TTL` (default 3600 seconds).

## Example: Using with OpenAI Python Client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="secret",  # or anything if ROUTER_TOKEN not set
)

response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "write a regex for emails"}],
    max_tokens=1024,
)

print(response.choices[0].message.content)
```

## Example: Using with cURL

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer secret" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "write a regex for emails"}],
    "max_tokens": 1024
  }'
```

## Example: Streaming with cURL

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer secret" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "write a regex for emails"}],
    "stream": true
  }'
```
