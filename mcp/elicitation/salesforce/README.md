# Salesforce Hosted MCP (elicitation, External Client App, PKCE)

Upstream: `api.salesforce.com/platform/mcp/v1/... (path from Setup > API Catalog > MCP Servers)`.
Verified: AGW 2026.10.1, 2026-10-27 (`tools/list`, `tools/call` 200).

## Setup

Create a Salesforce **External Client App** with callback `https://<gateway-host>/oauth-issuer/callback/upstream`, scopes `mcp_api refresh_token openid`, PKCE required, and *Issue JWT-based access tokens for named users* (opaque tokens get 401 from the MCP server). Activate the MCP server (e.g. `sobject-all`) and copy its URL path. The Secret has **no `client_secret`** on purpose: with explicit URLs a client secret turns PKCE off.

`optional-eagpol-salesforce-tool-authz.yaml` (not in `crs-all.yaml`): members of one Entra group get only the 6 read tools of `sobject-all` (`tools/list` went 11 to 6 in testing).

## Files

Individual CRs (`01-secret-combined-salesforce-token-exchange.yaml`, `02-backend-combined-salesforce-backend.yaml`, `03-eagpol-combined-salesforce-exchange.yaml`, `04-httproute-combined-salesforce-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/salesforce`.
