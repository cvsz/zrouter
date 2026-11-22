# Deployment, Migration, and Recovery

## Deployment status

No production deployment has been performed by this change. The repository's target production host, OS, service owner, network path, and current deployed commit have not been verified. Treat all commands below as a controlled deployment runbook, not evidence that a target environment is ready.

## Local development

Requirements: Python 3.10+.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,web]'
make lint
make test
```

Set provider credentials through a protected environment or a protected key file. Do not put real credentials in shell history, source control, PR text, test fixtures, or build artifacts.

## Container images

Two images are supported:

- `Dockerfile`: OpenAI-compatible HTTP proxy, bound to `0.0.0.0:8000` inside the container. A router bearer token is mandatory.
- `Dockerfile.web`: Flask/Gunicorn dashboard and OpenAI-compatible API.

Both images:
- run as a non-root user with a writable home directory;
- include all extracted router modules and runtime dependencies;
- use `/livez` for Docker liveness checks;
- persist bot metadata and router statistics under named volumes when using Compose;
- do not copy `provider.json` or credentials into the image.

### Docker Compose (recommended web deployment)

Create local secret files. Keep the directory outside source control; `secrets/` is gitignored.

```bash
install -d -m 0700 secrets
umask 077
printf '%s' "$NVIDIA_API_KEYS" > secrets/nvidia_api_keys.txt
printf '%s' "$ROUTER_TOKEN" > secrets/router_token.txt
chmod 0400 secrets/nvidia_api_keys.txt secrets/router_token.txt
sudo chown 10001:10001 secrets/nvidia_api_keys.txt secrets/router_token.txt
unset NVIDIA_API_KEYS ROUTER_TOKEN

docker compose -f docker-compose.web.yml config --quiet
docker compose -f docker-compose.web.yml up -d --build
docker compose -f docker-compose.web.yml ps
```

The image runs as fixed non-root UID/GID `10001:10001`. For local file-backed Compose secrets, the files must be readable by that container identity; the commands above assign ownership to UID/GID 10001 and mode 0400. Docker Compose's local file-backed secrets do not remap file ownership/mode on every platform, so verify this on the target Docker engine.

The Compose file mounts these files as Docker secrets:
- `/run/secrets/nvidia_api_keys`, read through `NVIDIA_KEYS_FILE`;
- `/run/secrets/router_token`, read through `ROUTER_TOKEN_FILE`.

The host port is bound to `127.0.0.1` by default. Put a separately reviewed TLS reverse proxy in front of it if remote access is required. Do not change the bind address to a public interface without a reviewed network/authentication configuration.

Persistent volumes:
- `zrouter_bot_data`: bot metadata and non-secret local memory.
- `zrouter_stats`: router statistics.

The default container does **not** mount Linux SecretService, macOS Keychain, or Windows Credential Locker. Vault secret operations intentionally fail closed inside these images. Do not assume that mounting the bot data volume enables native keyring support.

### Runtime smoke checks

```bash
curl --fail http://127.0.0.1:8000/livez
curl --fail -H "Authorization: Bearer $ROUTER_TOKEN" http://127.0.0.1:8000/health
```

`/livez` returns only process liveness and is intentionally unauthenticated. `/health`, `/stats`, `/v1/models`, and inference endpoints remain protected by the configured bearer token.

## Native OS keyring validation

The CI workflow `.github/workflows/runtime-validation.yml` runs a real secret-store round-trip on:
- Linux with D-Bus + GNOME Keyring SecretService;
- macOS Keychain;
- Windows Credential Locker.

These tests write only synthetic, uniquely named test secrets and delete them after the test. CI evidence must be checked for the exact PR head SHA. A passing CI matrix does not prove that the production host has an unlocked/configured credential store.

## NVIDIA NIM live smoke test

The optional `.github/workflows/nvidia-nim-smoke.yml` workflow is manual-only. It requires:
- repository secret `NVIDIA_NIM_API_KEY`;
- an explicitly curated NVIDIA model marked free in `models.json`;
- the exact typed confirmation `RUN_ONE_NVIDIA_NIM_REQUEST`.

It sends one synthetic, non-sensitive prompt to the official HTTPS NVIDIA NIM endpoint, with no retries and a bounded timeout. It does not print the key or response body. Provider pricing/quotas can change; a catalog `free: true` flag is not a billing guarantee. Verify current account terms before triggering the workflow. No live provider call has been made by this PR unless a workflow run is explicitly shown in Actions.

## Legacy vault migration

The vault migration is a data-format change and is **not backward-compatible** with the earlier plaintext vault implementation.

Preconditions:
1. Identify the exact host/user that owns the legacy vault.
2. Stop all zrouter/bot processes that can write the vault.
3. Create and verify an encrypted, access-restricted backup using the environment's approved backup mechanism. Never put the plaintext backup in Git, CI artifacts, or issue/PR comments.
4. Configure and unlock the host-native credential store. Confirm that `KeyringVaultBackend` selects SecretService, macOS Keychain, or Windows Credential Locker.
5. Verify the running process identity can access the selected store.

Run migration locally on the target host, not in the default Docker image:

```python
from pathlib import Path
from zrouter_bot_storage import Vault

vault_path = Path.home() / ".zrouter_bot" / "vault.json"
migrated_count = Vault.migrate_legacy(vault_path, confirm=True)
vault = Vault(vault_path)
assert len(vault.list()) == migrated_count
print(f"Verified {migrated_count} migrated vault entries")
```

The migration stores secret values in the native keyring and replaces the JSON file with a metadata-only index. It attempts to remove newly written keyring entries if migration fails, but a process crash can leave orphaned keyring items. Migration cannot securely erase historical filesystem blocks, snapshots, or backups. Keep the encrypted backup until a restore test and operational acceptance have passed.

## Rollback and recovery

- **Before vault migration:** stop the service, restore the protected pre-change data backup, and restore the previously deployed application artifact/configuration.
- **After vault migration:** do not blindly roll back to a pre-keyring release. That release expects plaintext values and cannot read the metadata-only keyring index. There is no automatic downgrade or plaintext export path. Prefer forward-fix/restore of the keyring-backed release.
- A downgrade that recreates the old plaintext format requires a separately approved, offline recovery procedure with explicit acceptance of the at-rest plaintext risk. Do not improvise this on a live host.
- If the native keyring is unavailable, do not create a plaintext fallback. Restore the keyring service/host backup or recover forward.
- Preserve the encrypted pre-migration backup and validate the restore before deleting any retained copy.

## Production acceptance checklist

Do not mark a target environment ready until the operator verifies:

- [ ] Target host, OS/version, service identity, deployment owner, and deployed commit are recorded.
- [ ] Docker/Compose or native runtime version and image digests are recorded.
- [ ] Required secret files/secret-store entries exist, are readable only by the intended principal, and are not exposed through process arguments or logs.
- [ ] Router bearer authentication and external TLS/reverse-proxy path are verified.
- [ ] Native keyring integration is verified on the actual host if vault operations are required.
- [ ] Persistent data volumes, backup encryption, retention, restore, and migration rollback are tested.
- [ ] Liveness, authenticated health, streaming disconnect, and bounded-load checks pass.
- [ ] Provider/model allowlist and current NVIDIA NIM pricing/quotas are verified by the operator.
- [ ] Monitoring, resource limits, restart behavior, incident escalation, and recovery ownership are defined.

No deployment, migration, credential rotation, or production mutation is authorized or performed by this PR.
