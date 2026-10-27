# Atlassian Rovo (elicitation, chained DCR)

Upstream: `mcp.atlassian.com/v1/mcp`.
Verified: AGW 2026.10.0, 2026-10-23. Same config running on the test cluster after the upgrade to 2026.10.1.

## Setup

Dynamic client registration: no OAuth app to create, the gateway registers a client against `base_url` (`https://mcp.atlassian.com`) at elicitation time. An Atlassian org admin must allow `https://<gateway-host>/oauth-issuer/callback/upstream` for the Rovo MCP server. Scopes: `read:jira-work offline_access` (`offline_access` gives a refresh token).

## Files

Individual CRs (`01-secret-combined-atlassian-token-exchange.yaml`, `02-backend-combined-atlassian-backend.yaml`, `03-eagpol-combined-atlassian-exchange.yaml`, `04-httproute-combined-atlassian-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/atlassian`.
