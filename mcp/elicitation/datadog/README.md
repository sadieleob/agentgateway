# Datadog MCP (elicitation, chained DCR)

Upstream: Datadog's remote MCP server `https://mcp.datadoghq.com/v1/mcp` (US1; region-specific).
Verified on AGW 2026.10.0, 2026-10-23 (see [../README.md](../README.md)).

## Datadog side (org admin, Organization Settings → MCP)

1. Enable MCP access for the org (enable write access only if users need write tools).
2. **MCP OAuth Redirect URLs** → add `https://<gateway-host>/oauth-issuer/callback/upstream`.
3. Users need the **MCP Read** permission (and **MCP Write** for write tools) plus the
   resource-level permissions of what they query. The MCP server only shows what the user can see.

Datadog supports dynamic client registration, so no OAuth app or client secret is needed.

`base_url` in the secret **must include `/v1/mcp`**: the gateway requires it to equal the `issuer`
in Datadog's authorization-server metadata. With the bare host the authorize step fails with
`authorization server metadata issuer "https://mcp.datadoghq.com/v1/mcp" does not match base_url`.

Scope: `mcp_all` (the only scope Datadog advertises).

## Apply

```bash
kubectl apply -f 01-backend.yaml -f 02-secret-token-exchange.yaml \
  -f 03-eagpol-token-exchange.yaml -f 04-httproute.yaml
```

Connect: `https://<gateway-host>/mcp/datadog`.
