# Kagent Tool Server via AgentGateway with Entra ID Auth

Expose the kagent-tool-server (124 tools, Streamable HTTP MCP) through Enterprise AgentGateway with Microsoft Entra ID downstream authentication.

## Architecture

```
                         DOWNSTREAM (authenticated)                    UPSTREAM (no auth)
                    ┌─────────────────────────────┐            ┌──────────────────────────┐
                    │                             │            │                          │
  ┌──────────┐     │  ┌──────────────────────┐    │            │  ┌────────────────────┐  │
  │ Claude   │     │  │   AgentGateway       │    │            │  │ kagent-tool-server │  │
  │ Code /   │ TLS │  │                      │    │    HTTP    │  │                    │  │
  │ VS Code  │────────│  1. OAuth discovery  │───────────────────│  Plain HTTP :8084   │  │
  │          │     │  │  2. JWT validation   │    │            │  │  No auth required  │  │
  │ MCP      │     │  │  3. Token stripping  │    │            │  │  124 tools         │  │
  │ Client   │     │  │  4. Proxy to backend │    │            │  │                    │  │
  └──────────┘     │  └──────────────────────┘    │            │  └────────────────────┘  │
       │           │           │                  │            │                          │
       │           │           │                  │            │   kagent namespace       │
       │           └───────────┼──────────────────┘            └──────────────────────────┘
       │                       │                                  (cluster-internal)
       │                       │
       │              ┌────────▼─────────┐
       │              │   Entra ID       │
       └──────────────│                  │
        Browser SSO   │  Tenant: 5e7d..  │
        redirect      │  App: bf87e..    │
                      └──────────────────┘
```

### Downstream vs Upstream Auth

**Downstream** (client → AgentGateway): Authenticated. The MCP client (Claude Code, VS Code)
must present a valid Entra ID JWT. AgentGateway handles the full OAuth flow:
- Publishes `.well-known/oauth-protected-resource` metadata so clients auto-discover auth
- Runs the OAuth authorization code flow via elicitation (redirects user to Entra login)
- Validates the JWT (signature, issuer, audience) before allowing access

**Upstream** (AgentGateway → kagent-tool-server): No authentication. The kagent-tool-server
runs as a plain HTTP service inside the cluster (`TOKEN_PASSTHROUGH=false`). AgentGateway
validates and strips the user's token — the upstream MCP server never sees it. This is the
standard pattern: the gateway owns the auth boundary, backend services trust cluster-internal
traffic.

### OAuth Flow (step by step)

```
1. MCP client connects to https://<AGW_HOSTNAME>/kagent/mcp
2. AGW returns 401 + WWW-Authenticate header
3. Client fetches /.well-known/oauth-protected-resource/kagent/mcp
   → discovers authorization_servers URL
4. Client fetches /.well-known/oauth-authorization-server/kagent/mcp
   → discovers authorize/token endpoints
5. Client opens browser → Entra login page
6. User authenticates with Entra ID SSO
7. Entra redirects back with auth code → AGW issuer proxy exchanges for access token
8. Client reconnects to /kagent/mcp with Bearer token
9. AGW validates JWT (issuer, audience, signature via JWKS)
10. AGW proxies request to kagent-tools.kagent:8084/mcp (no token forwarded)
11. kagent-tool-server responds with tool list / tool results
```

## Prerequisites

- Enterprise AgentGateway deployed in `agentgateway-system` namespace
- `entra-jwks` AgentgatewayBackend already exists (points to `login.microsoftonline.com`)
- `auth-server` HTTPRoute already exists (routes `/oauth-issuer` to the issuer proxy)
- Kagent deployed in `kagent` namespace with `kagent-tools` service on port 8084
- Entra app registration with redirect URI: `https://<AGW_HOSTNAME>/oauth-issuer/callback`

## Entra ID App Registration

| Field | Value |
|---|---|
| Tenant ID | `<ENTRA_TENANT_ID>` |
| Client ID | `<ENTRA_CLIENT_ID>` |
| Audience | `api://<ENTRA_CLIENT_ID>` |
| Scope | `api://<ENTRA_CLIENT_ID>/agentgateway` |

## Apply

```bash
kubectl apply -f 01-backend.yaml
kubectl apply -f 02-secret.yaml
kubectl apply -f 03-authn-policy.yaml
kubectl apply -f 04-exchange-policy.yaml
kubectl apply -f 05-httproute.yaml
```

## Verify

```bash
# All resources accepted
kubectl -n agentgateway-system get eagbe,eagpol,httproute | grep kagent

# OAuth discovery works
curl -sk https://<AGW_HOSTNAME>/.well-known/oauth-protected-resource/kagent/mcp

# MCP endpoint returns 401 (auth required)
curl -sk -o /dev/null -w '%{http_code}' https://<AGW_HOSTNAME>/kagent/mcp
```

## Connect from Claude Code / VS Code

MCP server URL: `https://<AGW_HOSTNAME>/kagent/mcp`

The client will auto-discover the OAuth flow and redirect to Entra login.
