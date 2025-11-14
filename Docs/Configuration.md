# Configuration

This document describes all configuration inputs that the Aether-V Server reads
from environment variables. Values can be provided by a local `.env` file, Docker
runtime configuration, or Kubernetes ConfigMap/Secret objects.

## Kerberos Authentication

Aether-V requires Kerberos authentication for WinRM connectivity to support secure double-hop operations and Hyper-V cluster management. 

**For comprehensive Kerberos setup instructions, see [Kerberos-Authentication.md](Kerberos-Authentication.md)** which covers:
- Why Kerberos is required (double-hop, cluster operations, security)
- Keytab generation procedures
- Resource-Based Constrained Delegation (RBCD) configuration
- Migration from legacy NTLM/Basic/CredSSP authentication
- Security advisories and best practices

## Non-secret settings

These values normally live in `server/k8s/configmap.yaml` or `.env` files. The
defaults shown below match `server/app/core/config.py`. Application and build
version details are baked into the container from the repository `version`
artifact and surfaced automatically at runtime—there is no environment override
for the UI banner.

| Variable                        | Default                      | Required?               | Notes                                                                                                                |
| ------------------------------- | ---------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `DEBUG`                         | `false`                      | No                      | Enable verbose logging for troubleshooting. Keep `false` in production.                                              |
| `APP_NAME`                     | `Aether-V Server`           | No                      | Base application name used in logs and UI metadata banners.                       |
| `ENVIRONMENT_NAME`              | `Production Environment`     | No                      | Display name for the deployment environment shown in the UI and logs.                                                |
| `AUTH_ENABLED`                  | `true`                       | No                      | Toggle authentication middleware. Only disable for controlled development scenarios.                                 |
| `ALLOW_DEV_AUTH`                | `false`                      | When disabling auth     | Safety latch when `AUTH_ENABLED=false`; must be `true` before disabling auth.                                        |
| `OIDC_ISSUER_URL`               | _(unset)_                    | Yes (when auth enabled) | OpenID Connect issuer/authority URL, e.g. `https://login.microsoftonline.com/<tenant>/v2.0`.                         |
| `OIDC_CLIENT_ID`                | _(unset)_                    | Yes (when auth enabled) | OIDC application client ID that matches the IdP registration.                                                        |
| `OIDC_API_AUDIENCE`             | _(unset)_                    | Recommended             | Expected audience URI for API access tokens (for example `api://<client-id>`).                                       |
| `OIDC_READER_PERMISSIONS`       | `Aether.Reader`              | Yes                     | Comma/space separated scopes or app roles that grant read-only API access.                                           |
| `OIDC_WRITER_PERMISSIONS`       | `Aether.Writer`              | Yes                     | Scopes or roles that allow create/update/delete operations.                                                          |
| `OIDC_ADMIN_PERMISSIONS`        | `Aether.Admin`               | Optional                | Elevated scopes or roles for future administrative features.                                                         |
| `OIDC_REDIRECT_URI`             | _(unset)_                    | Yes (when auth enabled) | Callback URL registered with the IdP; must match the deployment hostname.                                            |
| `OIDC_ROLE_NAME`                | _(unset)_                    | Legacy                  | Optional single-role fallback for backwards compatibility with older deployments.                                   |
| `OIDC_FORCE_HTTPS`              | `true`                       | No                      | Enforce HTTPS redirects during login. Set `false` only for local HTTP testing.                                       |
| `OIDC_END_SESSION_ENDPOINT`     | _(unset)_                    | No                      | Optional override for the IdP single logout endpoint discovered from metadata.                                       |
| `OIDC_POST_LOGOUT_REDIRECT_URI` | _(unset)_                    | No                      | Absolute or relative path the IdP should redirect to after logout completes.                                         |
| `JWKS_CACHE_TTL`                | `300`                        | No                      | Seconds to cache the OIDC signing keys. Increase if rate-limited by the IdP.                                         |
| `MAX_TOKEN_AGE`                 | `3600`                       | No                      | Maximum accepted token age in seconds. Align with the IdP token lifetime.                                            |
| `SESSION_MAX_AGE`               | `3600`                       | No                      | Session cookie lifetime in seconds. Longer values keep sessions alive when idle.                                     |
| `COOKIE_SECURE`                 | `true`                       | No                      | Set the secure flag on cookies. Leave `true` unless developing over HTTP.                                            |
| `COOKIE_SAMESITE`               | `lax`                        | No                      | SameSite policy for cookies. Use `none` for cross-site scenarios (requires HTTPS).                                   |
| `HYPERV_HOSTS`                  | _(empty)_                    | Recommended             | Comma-separated list of Hyper-V hostnames. Without hosts no workloads can be managed.                                |
| `WINRM_KERBEROS_PRINCIPAL`      | _(unset)_                    | Yes                     | Kerberos SPN for WinRM authentication that is registered to the service account (e.g., `HTTP/aetherv.example.com@AD.EXAMPLE.COM`).                   |
| `WINRM_KERBEROS_REALM`          | _(unset)_                    | No                      | Optional Kerberos realm override. Defaults to the realm portion of `WINRM_KERBEROS_PRINCIPAL` when left unset.        |
| `WINRM_KERBEROS_KDC`            | _(unset)_                    | No                      | Optional KDC server override. When provided the server writes a temporary `krb5.conf` so GSSAPI/kinit honour the host. |
| `WINRM_PORT`                    | `5985`                       | No                      | WinRM port on Hyper-V hosts. Use `5986` when enforcing HTTPS.                                                        |
| `WINRM_OPERATION_TIMEOUT`       | `15.0`                       | No                      | Seconds to wait for individual WinRM operations before cancelling the request.    |
| `WINRM_CONNECTION_TIMEOUT`      | `30.0`                       | No                      | Network connect timeout (seconds) when establishing WinRM sessions.               |
| `WINRM_READ_TIMEOUT`            | `30.0`                       | No                      | Maximum time (seconds) to wait for WinRM responses before retrying.               |
| `WINRM_POLL_INTERVAL_SECONDS`   | `1.0`                        | No                      | Interval (seconds) between WinRM runspace status checks during long operations.   |
| `INVENTORY_REFRESH_INTERVAL`    | `60`                         | No                      | Seconds between background host refreshes. Increase to reduce polling frequency.                                     |
| `JOB_WORKER_CONCURRENCY`        | `6`                          | No                      | Maximum number of provisioning jobs executed simultaneously.                                                         |
| `JOB_LONG_TIMEOUT_SECONDS`      | `900.0`                        | No                      | Timeout applied to long-running orchestration jobs such as VM provisioning or deletion.                              |
| `JOB_SHORT_TIMEOUT_SECONDS`     | `60.0`                         | No                      | Timeout applied to quick orchestration jobs (power actions, script triggers).                                        |
| `REMOTE_TASK_MIN_CONCURRENCY`   | `6`                          | No                      | Initial number of concurrent WinRM/PowerShell operations the orchestrator will run.                                  |
| `REMOTE_TASK_MAX_CONCURRENCY`   | `24`                         | No                      | Baseline upper bound on simultaneous remote operations before dynamic scaling considers resource headroom.          |
| `REMOTE_TASK_DYNAMIC_CEILING`   | `48`                         | No                      | Hard ceiling for automatic fast-pool expansion driven by local resource utilisation.                                 |
| `REMOTE_TASK_SCALE_UP_BACKLOG`  | `2`                          | No                      | Minimum queued remote tasks required before scaling worker threads above the baseline.                               |
| `REMOTE_TASK_IDLE_SECONDS`      | `30.0`                       | No                      | Idle period (seconds) before surplus remote workers are released.                                                    |
| `REMOTE_TASK_SCALE_UP_DURATION_THRESHOLD` | `30.0`            | No                      | Historical average duration metric retained for diagnostics; no longer blocks scaling decisions.                     |
| `REMOTE_TASK_JOB_CONCURRENCY`   | `6`                          | No                      | Dedicated worker slots reserved for long-running job operations.                                                     |
| `REMOTE_TASK_RESOURCE_SCALE_INTERVAL_SECONDS` | `15.0`        | No                      | Frequency (seconds) of local resource sampling and scaling evaluation.                                               |
| `REMOTE_TASK_RESOURCE_OBSERVATION_WINDOW_SECONDS` | `45.0`    | No                      | Continuous period the pool must sit at capacity with backlog before increasing the max limit.                       |
| `REMOTE_TASK_RESOURCE_CPU_THRESHOLD` | `60.0`                 | No                      | Maximum average CPU utilisation during the observation window to permit scaling.                                     |
| `REMOTE_TASK_RESOURCE_MEMORY_THRESHOLD` | `70.0`              | No                      | Maximum average memory utilisation during the observation window to permit scaling.                                  |
| `REMOTE_TASK_RESOURCE_SCALE_INCREMENT` | `2`                  | No                      | Number of additional fast-pool workers granted when the resource checks allow an expansion.                          |
| `WEBSOCKET_TIMEOUT`             | `1800`                       | No                      | Idle timeout (seconds) before closing WebSocket sessions. Default is 30 minutes.                                     |
| `WEBSOCKET_PING_INTERVAL`       | `30`                         | No                      | Heartbeat ping interval in seconds. Align with load balancer expectations.                                           |
| `WEBSOCKET_REFRESH_TIME`        | `1500`                       | No                      | Client reconnect hint (seconds). Default is 25 minutes.                                                              |
| `HOST_INSTALL_DIRECTORY`        | `C:\Program Files\Aether-V` | No                      | Remote path used when deploying assets to Hyper-V hosts. Customize for side-by-side installs.                        |
| `HOST_DEPLOYMENT_TIMEOUT`       | `60.0`                       | No                      | Seconds allowed for individual WinRM operations during host script deployment.                                       |
| `AGENT_STARTUP_CONCURRENCY`     | `3`                          | No                      | Parallel host deployments performed during service startup.                                                          |
| `AGENT_STARTUP_INGRESS_TIMEOUT` | `120.0`                      | No                      | Maximum time to wait for ingress routing before the initial agent deployment begins.                                 |
| `AGENT_STARTUP_INGRESS_POLL_INTERVAL` | `3.0`                 | No                      | Interval between readiness probes when waiting for ingress routing.                                                 |
| `AGENT_DOWNLOAD_BASE_URL`       | _(unset)_                    | Recommended             | Externally reachable base URL hosts use to download agent artifacts. Without it, automated deployments are disabled. |
| `AGENT_DOWNLOAD_MAX_ATTEMPTS`   | `5`                          | No                      | Number of retries when hosts download artifacts.                                                                     |
| `AGENT_DOWNLOAD_RETRY_INTERVAL` | `2.0`                        | No                      | Seconds between host download retry attempts.                                                                        |
| `DUMMY_DATA`                    | `false`                      | No                      | Enable mock inventory data for demos without real hosts.                                                             |

## Secret settings

Sensitive values should be stored in a Kubernetes Secret or a secrets manager and
never committed to source control.

| Variable                   | Purpose                                          | Notes                                                                                                                                    |
| -------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `OIDC_CLIENT_SECRET`       | Client secret for the OIDC application.          | Required when using interactive login.                                                                                                   |
| `SESSION_SECRET_KEY`       | Key used to sign session cookies.                | Optional for development; required in production to persist authenticated sessions across restarts.                                      |
| `WINRM_KEYTAB_B64`         | Base64-encoded Kerberos keytab for WinRM access. | Required for Kerberos authentication. Generate with `base64 < service.keytab \| tr -d '\n'` and set as single-line value.                |

Service principals and other non-interactive callers authenticate by requesting OAuth tokens directly from the identity provider (for example, using a Microsoft Entra application client ID and secret) and presenting those bearer tokens to Aether-V. Access tokens should be requested with the API audience (for example `api://<client-id>/.default`) so the resulting token contains the configured app roles. No static API keys are required or supported.

## Stateless authorization mapping

Aether-V derives permissions from token claims so deployments remain stateless. Configure the environment variables listed above so they match the scopes or app roles defined in Microsoft Entra ID:

- **Reader** (`OIDC_READER_PERMISSIONS`): allows access to `GET` endpoints and WebSocket subscriptions. Tokens typically expose these as OAuth scopes in the `scp` or `scope` claim for user flows, or app roles in the `roles` claim for service principals.
- **Writer** (`OIDC_WRITER_PERMISSIONS`): grants the reader capabilities plus create/update/delete operations. Map this to the scopes or app roles that correspond to modification privileges.
- **Admin** (`OIDC_ADMIN_PERMISSIONS`): reserved for future administrative APIs. Configure it now to match any privileged roles you plan to issue.

Tokens are validated against the configured issuer, signing keys (JWKS), and the acceptable audiences (`OIDC_API_AUDIENCE`, `OIDC_CLIENT_ID`, or `api://<client-id>`). User tokens should carry the required scopes in the `scp` claim, while workload identities should emit matching app roles in the `roles` claim.

## Where values are consumed

The Pydantic settings model defined in `server/app/core/config.py` loads all variables
and provides helper methods for downstream code. Containerized deployments surface
non-secret values through `server/k8s/configmap.yaml`, while secret values are supplied
in `server/k8s/secret.yaml`. Local development uses `server/.env.example` as a template
for a developer-managed `.env` file.

Refer back to this document when updating any of these files to keep the configuration
surface consistent.
