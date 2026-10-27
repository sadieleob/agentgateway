# Dynatrace hosted MCP (brokered elicitation, fixed OAuth client, PKCE)

Upstream: `<env>.apps.dynatrace.com/platform-reserved/mcp-gateway/v0.1/servers/dynatrace-mcp/mcp`.
Verified: AGW 2026.10.1, 2026-10-26 (`initialize`, `tools/list` 200).

## Setup

Create a Dynatrace OAuth client (client ID + secret) with scopes `mcp-gateway:servers:invoke mcp-gateway:servers:read storage:logs:read storage:metrics:read`. The policy uses typed `entElicitation.brokered.chainedAuth` with `pkce: Always` plus `entTokenExchange.solo.elicitation`.

**`resource` workaround.** Dynatrace needs RFC 8707 `resource` on the token request; AGW 2026.10.1 only sends it where it is written by hand (`authorizeUrl`), not on token or refresh requests. So `accessTokenUrl` points to an in-cluster route on the gateway (`/oauth-upstream/dynatrace/token`) whose `AgentgatewayPolicy` appends `resource=<Dynatrace MCP URL>` to the form body and forwards to `sso.dynatrace.com`. That route uses a plain-HTTP listener `internal-http` (port 8080) on the Gateway, which `00-shared/02-gateway.yaml` does not have. Add it first:

```bash
kubectl -n agentgateway-system patch gateway agentgateway-mcp --type=json -p='[{"op":"add","path":"/spec/listeners/-","value":{"name":"internal-http","port":8080,"protocol":"HTTP","allowedRoutes":{"namespaces":{"from":"Same"}}}}]'
```

## Files

Individual CRs (`01-secret-dynatrace-oauth-client.yaml`, `02-backend-combined-dynatrace-backend.yaml`, `03-backend-dynatrace-sso.yaml`, `04-eagpol-combined-dynatrace-exchange.yaml`, `05-agpol-dynatrace-token-resource.yaml`, `06-httproute-combined-dynatrace-route.yaml`, `07-httproute-dynatrace-token-resource.yaml`) or all of them in `crs-all.yaml`. Shared CRs (Entra JWKS
backend, OAuth issuer route, CORS) are in [`../00-shared/`](../00-shared/). Replace every `REPLACE_WITH_*` value.

```bash
kubectl apply -f crs-all.yaml
```

Connect: `https://<gateway-host>/mcp/dynatrace`.
