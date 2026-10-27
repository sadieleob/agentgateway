# Microsoft MCP Server for Enterprise (elicitation, Entra app)

Upstream: `mcp.svc.cloud.microsoft/enterprise`.
Verified: 2026-10-24 on the test cluster: `initialize`, `tools/list` 200; `microsoft_graph_list_properties` (entity `application`) returned data.

## Setup

Register an Entra app for the upstream (separate from the gateway's app) with delegated permission `MCP.Application.Read.All` on Microsoft's MCP Server for Enterprise (appId `e8c77dc2-69b3-43f4-bc51-3213c9d915b4`, Microsoft's public app ID), a client secret, and Web redirect URI `https://<gateway-host>/oauth-issuer/callback/upstream`. Scopes: `api://e8c77dc2-69b3-43f4-bc51-3213c9d915b4/MCP.Application.Read.All offline_access`. The server is read-only Entra directory data (public preview).

## Files

Individual CRs (`01-secret-combined-o365-token-exchange.yaml`, `02-backend-combined-o365-backend.yaml`, `03-eagpol-combined-o365-exchange.yaml`, `04-httproute-combined-o365-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/o365`.
