# Configuration

This document describes all configuration inputs that the Aether-V Orchestrator reads
from environment variables. Values can be provided by a local `.env` file, Docker
runtime configuration, or Kubernetes ConfigMap/Secret objects.

## Non-secret settings

These values normally live in `server/k8s/configmap.yaml` or `.env` files. The
defaults shown below match `server/app/core/config.py`.

| Variable | Default | Purpose | Notes |
| --- | --- | --- | --- |
| `DEBUG` | `false` | Enable verbose logging for troubleshooting. | Keep `false` in production. |
| `APP_VERSION` | `0.1.0` | Application version banner. | Optional override for custom builds. |
| `ENVIRONMENT_NAME` | `Production Environment` | Display name for the deployment environment. | Shown in UI and logs. |
| `AUTH_ENABLED` | `true` | Toggle authentication middleware. | Set `false` only for controlled development scenarios. |
| `ALLOW_DEV_AUTH` | `false` | Safety latch when `AUTH_ENABLED=false`. | Must be `true` before disabling auth. |
| `OIDC_ISSUER_URL` | _required when auth enabled_ | OpenID Connect issuer/authority URL. | Example: `https://login.microsoftonline.com/<tenant>/v2.0`. |
| `OIDC_CLIENT_ID` | _required when auth enabled_ | OIDC application client ID. | Matches the IdP application registration. |
| `OIDC_ROLE_NAME` | `vm-admin` | Role or group required for access. | Use `*` to allow any authenticated principal. |
| `OIDC_REDIRECT_URI` | _required for OIDC login_ | Callback URL registered with the IdP. | Must match deployment hostname. |
| `OIDC_FORCE_HTTPS` | `true` | Enforce HTTPS redirects during login. | Set `false` only for local HTTP testing. |
| `JWKS_CACHE_TTL` | `300` | Seconds to cache the OIDC signing keys. | Increase if rate-limited by the IdP. |
| `MAX_TOKEN_AGE` | `3600` | Maximum accepted age (seconds) for access tokens. | Align with IdP token lifetime. |
| `SESSION_MAX_AGE` | `3600` | Session cookie lifetime in seconds. | Extending increases idle session duration. |
| `COOKIE_SECURE` | `true` | Set the secure flag on cookies. | Leave `true` unless developing over HTTP. |
| `COOKIE_SAMESITE` | `lax` | SameSite policy for cookies. | Use `none` for cross-site scenarios (requires HTTPS). |
| `HYPERV_HOSTS` | _(empty)_ | Comma-separated list of Hyper-V hostnames. | Required for production workloads. |
| `WINRM_TRANSPORT` | `ntlm` | WinRM authentication mechanism. | Supports `ntlm`, `basic`, or `credssp`. |
| `WINRM_PORT` | `5985` | WinRM port on Hyper-V hosts. | Use `5986` when enforcing HTTPS. |
| `INVENTORY_REFRESH_INTERVAL` | `60` | Seconds between background host refreshes. | Increase to reduce polling frequency. |
| `WEBSOCKET_TIMEOUT` | `1800` | Idle timeout (seconds) before closing WebSocket sessions. | Default is 30 minutes. |
| `WEBSOCKET_PING_INTERVAL` | `30` | Heartbeat ping interval in seconds. | Align with load balancer expectations. |
| `WEBSOCKET_REFRESH_TIME` | `1500` | Client reconnect hint (seconds). | Default is 25 minutes. |
| `HOST_INSTALL_DIRECTORY` | `C:\\Program Files\\Home Lab Virtual Machine Manager` | Remote path used when deploying assets to Hyper-V hosts. | Customize for parallel or test installations. |
| `DUMMY_DATA` | `false` | Enable mock inventory data. | Useful for UI demos without real hosts. |
| `ARTIFACTS_BASE_PATH` | `/app/artifacts` | Container path for bundled ISOs/scripts. | Typically left at the default. |

## Secret settings

Sensitive values should be stored in a Kubernetes Secret or a secrets manager and
never committed to source control.

| Variable | Purpose | Notes |
| --- | --- | --- |
| `OIDC_CLIENT_SECRET` | Client secret for the OIDC application. | Required when using interactive login. |
| `API_TOKEN` | Static token for API-based automation. | Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `SESSION_SECRET_KEY` | Key used to sign session cookies. | Must be present in production to keep sessions stable. |
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
