# GitHub without per-user OAuth (GitHub App installation token, group-gated)

Upstream: `self-hosted github-mcp-server (http mode) in the cluster`.
Verified: AGW 2026.10.0, 2026-10-19.

## Setup

No browser consent. A **GitHub App** private key is stored in `github-app-privatekey`; the External Secrets Operator `GithubAccessToken` generator mints a short-lived installation token every 30 minutes into `github-mcp-credentials` (`Authorization: Bearer ...`), and the backend injects it upstream. Users still sign in to the gateway with Entra, and `07-eagpol-github-noauth-auth.yaml` allows only members of one Entra group (needs the `groups` claim in the access token). Trade-off: one shared GitHub identity for everyone, no per-user revoke at GitHub.

Requires ESO installed. Build/push a github-mcp-server image that starts in http mode (`http --listen-host 0.0.0.0`, port 8082) and set `REPLACE_WITH_GITHUB_MCP_SERVER_IMAGE`. Do not set `GITHUB_PERSONAL_ACCESS_TOKEN` on the pod: it takes precedence over the injected header.

## Files

Individual CRs (`01-secret-github-app-privatekey.yaml`, `02-eso-generator-github-token.yaml`, `03-externalsecret-github-mcp-credentials-es.yaml`, `04-deployment-github-mcp-server.yaml`, `05-service-github-mcp-server.yaml`, `06-backend-github-app-backend.yaml`, `07-eagpol-github-noauth-auth.yaml`, `08-httproute-github-noauth-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/github-noauth`.
