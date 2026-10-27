# GitHub (elicitation, OAuth App)

Upstream: `api.githubcopilot.com/mcp/`.
Verified: AGW 2026.10.1, 2026-10-26 (elicitation completed, upstream token stored).

## Setup

GitHub has no dynamic client registration. Register a **GitHub OAuth App** with callback URL `https://<gateway-host>/oauth-issuer/callback/upstream` and put its client ID and secret in the token-exchange Secret. Scopes: `repo read:org`.

## Files

Individual CRs (`01-secret-combined-github-token-exchange.yaml`, `02-backend-combined-github-backend.yaml`, `03-eagpol-combined-github-exchange.yaml`, `04-httproute-combined-github-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/github`.
