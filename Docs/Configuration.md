# Configuration

This document describes all configuration inputs that the Aether-V Server reads
from environment variables. Values can be provided by a local `.env` file, Docker
runtime configuration, or Kubernetes ConfigMap/Secret objects.

## Non-secret settings

These values normally live in `server/k8s/configmap.yaml` or `.env` files. The
defaults shown below match `server/app/core/config.py`. Application and build
version details are baked into the container from the repository `version`
artifact and surfaced automatically at runtime—there is no environment override
for the UI banner.

| Variable | Default | Required? | Notes |
| --- | --- | --- | --- |
| `DEBUG` | `false` | No | Enable verbose logging for troubleshooting. Keep `false` in production. |
| `ENVIRONMENT_NAME` | `Production Environment` | No | Display name for the deployment environment shown in the UI and logs. |
| `AUTH_ENABLED` | `true` | No | Toggle authentication middleware. Only disable for controlled development scenarios. |
| `ALLOW_DEV_AUTH` | `false` | When disabling auth | Safety latch when `AUTH_ENABLED=false`; must be `true` before disabling auth. |
| `OIDC_ISSUER_URL` | _(unset)_ | Yes (when auth enabled) | OpenID Connect issuer/authority URL, e.g. `https://login.microsoftonline.com/<tenant>/v2.0`. |
| `OIDC_CLIENT_ID` | _(unset)_ | Yes (when auth enabled) | OIDC application client ID that matches the IdP registration. |
| `OIDC_ROLE_NAME` | `vm-admin` | No | Role or group required for access. Use `*` to allow any authenticated principal. |
| `OIDC_REDIRECT_URI` | _(unset)_ | Yes (when auth enabled) | Callback URL registered with the IdP; must match the deployment hostname. |
| `OIDC_FORCE_HTTPS` | `true` | No | Enforce HTTPS redirects during login. Set `false` only for local HTTP testing. |
| `JWKS_CACHE_TTL` | `300` | No | Seconds to cache the OIDC signing keys. Increase if rate-limited by the IdP. |
| `MAX_TOKEN_AGE` | `3600` | No | Maximum accepted token age in seconds. Align with the IdP token lifetime. |
| `SESSION_MAX_AGE` | `3600` | No | Session cookie lifetime in seconds. Longer values keep sessions alive when idle. |
| `COOKIE_SECURE` | `true` | No | Set the secure flag on cookies. Leave `true` unless developing over HTTP. |
| `COOKIE_SAMESITE` | `lax` | No | SameSite policy for cookies. Use `none` for cross-site scenarios (requires HTTPS). |
| `HYPERV_HOSTS` | _(empty)_ | Recommended | Comma-separated list of Hyper-V hostnames. Without hosts no workloads can be managed. |
| `WINRM_TRANSPORT` | `ntlm` | No | WinRM authentication mechanism (`ntlm`, `basic`, or `credssp`). |
| `WINRM_PORT` | `5985` | No | WinRM port on Hyper-V hosts. Use `5986` when enforcing HTTPS. |
| `INVENTORY_REFRESH_INTERVAL` | `60` | No | Seconds between background host refreshes. Increase to reduce polling frequency. |
| `JOB_WORKER_CONCURRENCY` | `3` | No | Maximum number of provisioning jobs executed simultaneously. |
| `WEBSOCKET_TIMEOUT` | `1800` | No | Idle timeout (seconds) before closing WebSocket sessions. Default is 30 minutes. |
| `WEBSOCKET_PING_INTERVAL` | `30` | No | Heartbeat ping interval in seconds. Align with load balancer expectations. |
| `WEBSOCKET_REFRESH_TIME` | `1500` | No | Client reconnect hint (seconds). Default is 25 minutes. |
| `HOST_INSTALL_DIRECTORY` | `C\\Program Files\\Home Lab Virtual Machine Manager` | No | Remote path used when deploying assets to Hyper-V hosts. Customize for side-by-side installs. |
| `AGENT_STARTUP_CONCURRENCY` | `4` | No | Parallel host deployments performed during service startup. |
| `AGENT_ARTIFACTS_PATH` | `/app/agent` | Advanced | Container path containing embedded agent artifacts. Override only when repackaging the image. |
| `AGENT_HTTP_MOUNT_PATH` | `/agent` | Advanced | URL path where agent artifacts are exposed by the service. |
| `AGENT_DOWNLOAD_BASE_URL` | _(unset)_ | Recommended | Externally reachable base URL hosts use to download agent artifacts. Without it, automated deployments are disabled. |
| `AGENT_DOWNLOAD_MAX_ATTEMPTS` | `5` | No | Number of retries when hosts download artifacts. |
| `AGENT_DOWNLOAD_RETRY_INTERVAL` | `2.0` | No | Seconds between host download retry attempts. |
| `DUMMY_DATA` | `false` | No | Enable mock inventory data for demos without real hosts. |

## Secret settings

Sensitive values should be stored in a Kubernetes Secret or a secrets manager and
never committed to source control.

| Variable | Purpose | Notes |
| --- | --- | --- |
| `OIDC_CLIENT_SECRET` | Client secret for the OIDC application. | Required when using interactive login. |
| `API_TOKEN` | Static token for API-based automation. | Optional but required when integrating unattended callers. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `SESSION_SECRET_KEY` | Key used to sign session cookies. | Optional for development; required in production to keep sessions stable across restarts. |
| `WINRM_USERNAME` | Username for connecting to Hyper-V hosts. | Typically a domain account with necessary privileges. |
| `WINRM_PASSWORD` | Password for the WinRM account. | Consider using certificates for enhanced security. |

## Where values are consumed

The Pydantic settings model defined in `server/app/core/config.py` loads all variables
and provides helper methods for downstream code. Containerized deployments surface
non-secret values through `server/k8s/configmap.yaml`, while secret values are supplied
in `server/k8s/secret.yaml`. Local development uses `server/.env.example` as a template
for a developer-managed `.env` file.

Refer back to this document when updating any of these files to keep the configuration
surface consistent.
