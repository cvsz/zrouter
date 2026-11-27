# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of zrouter seriously. If you discover a security vulnerability, please report it to us.

### How to Report

Please do not report security vulnerabilities through public GitHub issues.

Instead, use GitHub's private vulnerability reporting feature if it is enabled for this repository. If it is unavailable, contact the repository owner privately through an authenticated channel. Do not disclose vulnerabilities in public issues.

Include as much of the following information as possible to help us better understand and resolve the issue:

- Type of issue (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- Location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit the vulnerability

This information will help us triage your report more quickly.

## Security Policy

zrouter is designed with security in mind:

- **No hardcoded API keys** - All API keys must be provided via environment variables or provider.json (which is gitignored)
- **No secrets in Docker images** - provider.json is not copied into Docker images
- **Token-based authentication** - The proxy server supports bearer token authentication via `ROUTER_TOKEN`. It is **mandatory** when binding to a non-loopback interface (e.g. `0.0.0.0`); `serve()` fails closed and refuses to start unauthenticated on `0.0.0.0`. `/health` and `/stats` require a valid token when one is configured.
- **Input validation** - All request bodies are validated as JSON objects
- **Request size limits** - Maximum request body size is 16 MiB
- **Thread-safe** - All shared state is protected by locks
- **No system command execution** - No shell=True or similar dangerous patterns

## Supported Providers

zrouter supports multiple LLM providers:

| Provider | Base URL | Env Var |
|----------|----------|---------|
| NVIDIA | https://integrate.api.nvidia.com/v1 | NVIDIA_API_KEYS |
| OpenRouter | https://openrouter.ai/api/v1 | OPENROUTER_API_KEYS |
| Groq | https://api.groq.com/openai/v1 | GROQ_API_KEYS |
| Together AI | https://api.together.xyz/v1 | TOGETHER_API_KEYS |
| Google | https://generativelanguage.googleapis.com/v1beta/openai/ | GOOGLE_API_KEYS |
| DeepSeek | https://api.deepseek.com/v1 | DEEPSEEK_API_KEYS |
| Meta | https://integrate.api.nvidia.com/v1 | META_API_KEYS |
| Mistral AI | https://api.mistral.ai/v1 | MISTRAL_API_KEYS |
| Qwen | https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1 | QWEN_API_KEYS |
| ZEAZ | https://zeaz.ai/v1 | ZEAZ_API_KEYS |
| OpenAI | https://api.openai.com/v1 | OPENAI_API_KEYS |
| Anthropic | https://api.anthropic.com/v1 | ANTHROPIC_API_KEYS |
| Gemini | https://generativelanguage.googleapis.com/v1beta/openai/ | GEMINI_API_KEYS |
| Cerebras | https://api.cerebras.ai/v1 | CEREBRAS_API_KEYS |

## Security Best Practices for Users

1. **Never commit API keys** - provider.json is gitignored for a reason
2. **Use environment variables** - Prefer environment variables over provider.json for production
3. **Use ROUTER_TOKEN** - Always set ROUTER_TOKEN when running the proxy on public interfaces
4. **Limit key scope** - Use API keys with the minimum required permissions
5. **Rotate keys regularly** - Rotate API keys periodically
6. **Monitor usage** - Check stats endpoint for unusual activity

## Known limitations

- The current `zrouter_bot.Vault` implementation stores credential values as ordinary JSON and is **not encrypted at rest**. The vault file is restricted to mode `0600` and its directory to `0700` on POSIX systems, but this does not protect against the same OS user, root, or a compromised process. Do not use it as a substitute for an OS-backed secret manager or store high-value production credentials there.
- Local bot memory, routine, and skill stores are also JSON files. Treat access to the bot data directory as access to its contents.
- Model discovery reports upstream availability only. Newly discovered models are not considered free until explicitly curated in the model catalog and route allowlist.
