# MCP Tool Calling Restriction — AgentGateway Enterprise

## Context

Restrict which MCP servers and tools a client can access based on JWT claims (e.g., `aud`/clientid). Two approaches exist:

1. **Native MCP Authorization** (recommended) — built into AgentGateway, works at the MCP protocol level
2. **BYO ext-authz** — custom gRPC ext-auth service, works at the HTTP level

---

## Approach 1: Native MCP Authorization (Recommended)

Works at the **MCP protocol level**:
- `tools/list` → unauthorized tools are **filtered out** (client never sees them)
- `tools/call` on unauthorized tool → JSON-RPC error `-32602 Unknown tool`
- No custom ext-auth service needed

### CEL Variables Available

| Variable | Description | Example |
|---|---|---|
| `mcp.tool.name` | Tool being accessed/listed | `"dns_lookup"` |
| `jwt.sub` | JWT `sub` claim | `"service-app-a"` |
| `jwt.aud` | JWT `aud` claim | `"mcp-client-123"` |
| `jwt.<any_claim>` | Any JWT claim, including nested | `jwt.clientId`, `jwt.team` |

### Where to Configure

The `authorization` field is a sibling of `authentication` under `policies.mcp` on the `AgentgatewayBackend`, or under `spec.backend.mcp` on `AgentgatewayPolicy`/`EnterpriseAgentgatewayPolicy`.

Option A — On the `AgentgatewayBackend` directly:

```yaml
spec:
  policies:
    mcp:
      authentication: { ... }   # existing JWT/MCP OAuth config
      authorization:             # NEW
        action: Allow
        policy:
          matchExpressions:
            - '<CEL expression>'
```

Option B — On an `AgentgatewayPolicy` targeting the HTTPRoute:

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayPolicy
spec:
  targetRefs:
    - name: <httproute-name>
      kind: HTTPRoute
  backend:
    mcp:
      authentication: { ... }
      authorization:
        action: Allow
        policy:
          matchExpressions:
            - '<CEL expression>'
```

### Full Example: Two MCP Servers, Per-Client Tool Access

See [native-mcp-authz-example.yaml](native-mcp-authz-example.yaml)

### Runtime Behavior

| Client (aud) | `tools/list` | `tools/call` on unauthorized tool |
|---|---|---|
| Matched by Allow rule | Only authorized tools returned | Allowed |
| Not matched | Empty tools list | `-32602 Unknown tool` |
| Not in `audiences` list | **401** at authentication | **401** |

### Allow vs Deny Action

- `action: Allow` — only tools matching a `matchExpressions` rule are permitted (allowlist)
- `action: Deny` — tools matching a rule are blocked, everything else is permitted (blocklist)

```yaml
# Deny example: block sandbox clients from dangerous tools
authorization:
  action: Deny
  policy:
    matchExpressions:
      - 'jwt.aud == "sandbox-client" && mcp.tool.name == "delete_repository"'
```

### Note on `aud` Claim Format

If the JWT `aud` is an array (`"aud": ["app-a", "resource-server"]`), use `in`:

```yaml
matchExpressions:
  - '"app-a" in jwt.aud && mcp.tool.name == "echo"'
```

If `aud` is a single string, `jwt.aud == "app-a"` works directly.

---

## Approach 2: BYO ext-authz (HTTP-Level)

Works at the **HTTP level** before MCP protocol processing. The ext-auth service receives a gRPC `CheckRequest` and returns ALLOW/DENY.

### Limitation

- `tools/list` → **all-or-nothing** (403 or full list). Cannot filter individual tools.
- `tools/call` → can ALLOW or DENY (returns HTTP 403, not JSON-RPC error)

### Prerequisite: `forwardBody` on EnterpriseAgentgatewayPolicy

Without `forwardBody`, the ext-auth service cannot see the JSON-RPC payload (method + tool name):

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: mcp-ext-auth-policy
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: agentgateway
  traffic:
    extAuth:
      backendRef:
        name: <ext-auth-service>
        namespace: agentgateway-system
        port: 9001
      forwardBody:
        maxSize: 8192
      grpc: {}
```

### Sample gRPC CheckRequests

See [sample-grpc-check-requests.md](sample-grpc-check-requests.md)

### Data Available to the ext-auth Service

| Data Point | Where | How |
|---|---|---|
| **Client ID** | JWT `aud` claim | Decode `Authorization: Bearer <token>`, base64url-decode middle segment, read `aud` |
| **MCP server** | `path` | `/mcp` → identifies MCP backend. Multiple servers use different paths (e.g., `/mcp-github`, `/mcp-jira`) |
| **MCP method** | `body` → `method` | `"tools/call"`, `"tools/list"`, `"resources/read"`, `"initialize"`, etc. |
| **Tool name** | `body` → `params.name` | Only present when `method` is `"tools/call"` |
| **Resource URI** | `body` → `params.uri` | Only present when `method` is `"resources/read"` |
| **Prompt name** | `body` → `params.name` | Only present when `method` is `"prompts/get"` |

---

## JWT Auth vs MCP OAuth Auth

They serve **different purposes** and are **not interchangeable**.

| | **MCP Auth** | **JWT Auth** |
|---|---|---|
| **Where configured** | `AgentgatewayBackend.spec.policies.mcp.authentication` | `EnterpriseAgentgatewayPolicy.spec.traffic.jwtAuthentication` |
| **Purpose** | Full MCP OAuth 2.0 flow: discovery → client registration → token validation | Token validation only — client already has a JWT |
| **Discovery endpoints** | `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server` | None |
| **Client registration** | Yes — proxy registers MCP clients with IdP dynamically | No — client must already have credentials |
| **Use for** | MCP Inspector, AI coding assistants, VS Code (dynamic clients) | Service-to-service, pre-configured clients |
| **Token exchange** | Compatible (e.g., Entra → Databricks token exchange) | Compatible |
| **Tool-level authz** | Yes — add `authorization` alongside `authentication` | No — only HTTP-level ALLOW/DENY |
| **Target ref** | `AgentgatewayBackend` | `Gateway` or `HTTPRoute` |

**They are complementary.** You could use both on different levels (MCP auth on the Backend for MCP clients, JWT auth on the Gateway for service-to-service), but they cannot replace each other.

---

## Databricks Backend Example

### Adding Authorization to a Databricks MCP Backend

See [databricks-backend-with-authz.yaml](databricks-backend-with-authz.yaml)

---

## Comparison: Native vs ext-authz

| | Native `mcpAuthorization` | BYO ext-authz |
|---|---|---|
| `tools/list` filtering | Unauthorized tools hidden from response | All-or-nothing (403 or full list) |
| `tools/call` denial | JSON-RPC error `-32602 Unknown tool` | HTTP 403 Forbidden |
| Authorization level | MCP protocol (per-tool) | HTTP level (per-request) |
| JWT claims access | Built-in via `jwt.*` CEL variables | Must parse JWT manually |
| Server-per-route scoping | Policy targets HTTPRoute | Must parse path in ext-auth code |
| Complexity | Declarative YAML | Custom code + Docker image + deployment |

---

## Validated

- **Version:** AgentGateway Enterprise 2.3.0-beta.4
- **Date:** 2026-03-21

Test results (native MCP authorization with `action: Allow`):

| Test | Result |
|---|---|
| `tools/list` with 2 allowed tools | Only `echo` + `dns_lookup` returned (6 tools filtered out) |
| `tools/call echo` (authorized) | Success — tool executed normally |
| `tools/call sha256_hash` (unauthorized) | `-32602 Unknown tool: sha256_hash` |
| `tools/call base64_encode` (unauthorized) | `-32602 Unknown tool: base64_encode` |

---

## References

- [BYO ext auth service docs](https://docs.solo.io/agentgateway/2.1.x/security/extauth/byo-ext-auth-service/)
- [JWT auth for services](https://docs.solo.io/agentgateway/2.1.x/mcp/mcp-access/)
- [About MCP auth](https://docs.solo.io/agentgateway/2.1.x/mcp/auth/about/)
- [OSS authorization example](https://github.com/agentgateway/agentgateway/blob/main/examples/authorization/README.md)
- [OSS authorization config](https://github.com/agentgateway/agentgateway/blob/main/examples/authorization/config.yaml)
