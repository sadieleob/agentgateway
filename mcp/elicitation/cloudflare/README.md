# Cloudflare (elicitation, chained DCR)

Upstream: `mcp.cloudflare.com/mcp`.
Verified: AGW 2026.10.1, 2026-10-26 (access + refresh token stored).

## Setup

Dynamic client registration against `base_url` `https://mcp.cloudflare.com`. Scopes: `user:read account:read`.

## Files

Individual CRs (`01-secret-combined-cloudflare-token-exchange.yaml`, `02-backend-combined-cloudflare-backend.yaml`, `03-eagpol-combined-cloudflare-exchange.yaml`, `04-httproute-combined-cloudflare-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/cloudflare`.
