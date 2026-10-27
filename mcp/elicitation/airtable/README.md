# Airtable (elicitation, chained DCR)

Upstream: `mcp.airtable.com/mcp`.
Verified: AGW 2026.10.1, 2026-10-26 (`tools/list`, `tools/call` 200).

## Setup

Dynamic client registration; `base_url` must be the authorization server issuer, `https://airtable.com/oauth2/v1`. Read-only scopes: `data.records:read schema.bases:read workspacesAndBases:read data.recordComments:read`.

## Files

Individual CRs (`01-secret-combined-airtable-token-exchange.yaml`, `02-backend-combined-airtable-backend.yaml`, `03-eagpol-combined-airtable-exchange.yaml`, `04-httproute-combined-airtable-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/airtable`.
