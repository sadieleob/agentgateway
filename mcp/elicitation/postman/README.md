# Postman (elicitation, chained DCR)

Upstream: `mcp.postman.com/minimal`.
Verified: AGW 2026.10.1, 2026-10-26 (`tools/list`, `tools/call` 200).

## Setup

Dynamic client registration against `base_url` `https://mcp.postman.com`: no OAuth app to create, no scopes.

## Files

Individual CRs (`01-secret-combined-postman-token-exchange.yaml`, `02-backend-combined-postman-backend.yaml`, `03-eagpol-combined-postman-exchange.yaml`, `04-httproute-combined-postman-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/postman`.
