# Datadog (elicitation, chained DCR)

Upstream: `mcp.datadoghq.com/v1/mcp`.
Verified: AGW 2026.10.0, 2026-10-21 and 2026-10-23; AGW 2026.10.1, 2026-10-26 (elicitations completed).

## Setup

Dynamic client registration: no OAuth app to create. `base_url` must be the authorization server issuer, `https://mcp.datadoghq.com/v1/mcp`. Scope: `mcp_all`.

## Files

Individual CRs (`01-secret-combined-datadog-token-exchange.yaml`, `02-backend-combined-datadog-backend.yaml`, `03-eagpol-combined-datadog-exchange.yaml`, `04-httproute-combined-datadog-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/datadog`.
