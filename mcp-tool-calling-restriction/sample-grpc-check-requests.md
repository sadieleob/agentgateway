# Sample gRPC ext-authz CheckRequests for MCP Traffic

These are the `envoy.service.auth.v3.CheckRequest` messages the AgentGateway sends to a BYO ext-auth service for MCP requests.

**Prerequisite**: `forwardBody.maxSize` must be set on the `EnterpriseAgentgatewayPolicy` for the body to be included.

---

## tools/call (tool invocation — primary authorization target)

```
CheckRequest.attributes.request.http:
  method: "POST"
  path:   "/mcp"
  host:   "<gateway-address>:8080"
  scheme: "http"
  protocol: "HTTP/1.1"
  headers:
    "authorization": "Bearer <JWT>"
    "content-type":  "application/json"
    "accept":        "application/json, text/event-stream"
    "mcp-session-id": "<session-id>"
  body: |
    {
      "jsonrpc": "2.0",
      "method": "tools/call",
      "params": {
        "name": "dns_lookup",
        "arguments": { "hostname": "example.com" }
      },
      "id": 3
    }
```

## tools/list (tool discovery)

```
  method: "POST"
  path:   "/mcp"
  headers:
    "authorization": "Bearer <JWT>"
    "content-type":  "application/json"
    "accept":        "application/json, text/event-stream"
    "mcp-session-id": "<session-id>"
  body: |
    {
      "jsonrpc": "2.0",
      "method": "tools/list",
      "id": 2
    }
```

## initialize (session setup)

```
  method: "POST"
  path:   "/mcp"
  headers:
    "authorization": "Bearer <JWT>"
    "content-type":  "application/json"
    "accept":        "application/json, text/event-stream"
  body: |
    {
      "jsonrpc": "2.0",
      "method": "initialize",
      "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": { "name": "mcp-inspector", "version": "0.14.0" }
      },
      "id": 1
    }
```

## resources/list

```
  body: |
    {
      "jsonrpc": "2.0",
      "method": "resources/list",
      "id": 4
    }
```

## resources/read

```
  body: |
    {
      "jsonrpc": "2.0",
      "method": "resources/read",
      "params": {
        "uri": "file:///config/settings.json"
      },
      "id": 5
    }
```

## prompts/list

```
  body: |
    {
      "jsonrpc": "2.0",
      "method": "prompts/list",
      "id": 6
    }
```

## prompts/get

```
  body: |
    {
      "jsonrpc": "2.0",
      "method": "prompts/get",
      "params": {
        "name": "summarize",
        "arguments": { "topic": "kubernetes" }
      },
      "id": 7
    }
```

---

## Data Extraction Summary

| Data Point | Source in CheckRequest | Example |
|---|---|---|
| **Client ID** (`aud`) | JWT in `headers["authorization"]` | base64url-decode middle segment of Bearer token |
| **MCP server** | `path` | `/mcp` or `/mcp-github`, `/mcp-jira` |
| **MCP method** | `body` → `method` | `"tools/call"`, `"tools/list"` |
| **Tool name** | `body` → `params.name` | Only for `tools/call` |
| **Resource URI** | `body` → `params.uri` | Only for `resources/read` |
| **Prompt name** | `body` → `params.name` | Only for `prompts/get` |

## EnterpriseAgentgatewayPolicy with forwardBody

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
