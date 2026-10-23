# GitHub MCP (elicitation)

Upstream: GitHub's remote MCP server `https://api.githubcopilot.com/mcp/`.
Verified on AGW 2026.10.0, 2026-10-23 (see [../README.md](../README.md)).

## GitHub side

GitHub's OAuth server has no dynamic client registration, so register a client:

1. GitHub → Settings → Developer settings → **OAuth Apps** → New OAuth App.
2. **Authorization callback URL**: `https://<gateway-host>/oauth-issuer/callback/upstream`
   (the gateway is the OAuth client; not the MCP client's callback).
3. Copy the client ID and generate a client secret → `02-secret-token-exchange.yaml`.
4. For org-owned repositories the OAuth App must be approved by an org owner.

Scopes used: `repo read:org`.

## Apply

```bash
kubectl apply -f 01-backend.yaml -f 02-secret-token-exchange.yaml \
  -f 03-eagpol-token-exchange.yaml -f 04-httproute.yaml
```

Connect: `https://<gateway-host>/mcp/github`.
