# Atlassian Rovo MCP (elicitation, chained DCR)

Upstream: `https://mcp.atlassian.com/v1/mcp`.
Verified on AGW 2026.10.0, 2026-10-23 (see [../README.md](../README.md)).

## Atlassian side

Atlassian's MCP authorization server supports dynamic client registration, so there is no OAuth
app to create: the gateway registers a client against `base_url` at elicitation time
(`02-secret-token-exchange.yaml` has no `client_id`/`client_secret`).

An Atlassian org admin must allow the gateway callback
`https://<gateway-host>/oauth-issuer/callback/upstream` for the Rovo MCP server.

Scopes used: `read:jira-work offline_access` (`offline_access` → refresh token, no re-consent when
the access token expires).

## Apply

```bash
kubectl apply -f 01-backend.yaml -f 02-secret-token-exchange.yaml \
  -f 03-eagpol-token-exchange.yaml -f 04-httproute.yaml
```

Connect: `https://<gateway-host>/mcp/atlassian`.
