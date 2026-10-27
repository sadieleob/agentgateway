# ServiceNow (OpenAPI to MCP, brokered elicitation with ServiceNow OAuth)

Upstream: `<instance>.service-now.com (ITSM REST APIs)`.
Verified: AGW 2026.10.1, 2026-10-26 (access + refresh token stored).

## Setup

The backend turns the ITSM OpenAPI schema in the ConfigMap into MCP tools. In ServiceNow, create an OAuth client (*OAuth - Authorization code grant*) with redirect URL `https://<gateway-host>/oauth-issuer/callback/upstream`; put its client ID in the policy and the secret in `servicenow-oauth-client`. Endpoints `/oauth_auth.do` and `/oauth_token.do`, scope `useraccount`. The schema's request examples contain ServiceNow demo `sys_id`s, not real records.

## Files

Individual CRs (`01-configmap-combined-servicenow-openapi-schema.yaml`, `02-secret-servicenow-oauth-client.yaml`, `03-backend-combined-servicenow-backend.yaml`, `04-eagpol-combined-servicenow-exchange.yaml`, `05-httproute-combined-servicenow-route.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/servicenow`.
