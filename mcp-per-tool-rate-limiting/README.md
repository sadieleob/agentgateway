# MCP Per-Tool Rate Limiting

Rate limit MCP traffic per tool name using CEL descriptors that inspect the JSON-RPC request body.

## Problem

Common requirements for MCP rate limiting:
1. Rate limit MCP traffic **per tool name** (e.g., limit `create_issue` to 3 calls/min, `echo` to 10 calls/min)
2. Differentiate between expensive and cheap tools with different rate limits
3. NOT count non-tool operations (initialize, tools/list) against tool limits

## Two Approaches

### 1. Local Rate Limiting (simple, per-route)

A token-bucket rate limit on the MCP HTTPRoute. Counts ALL MCP operations equally.

**When to use:** simple per-route ceiling, all tools equally expensive, no differentiation needed.

**File:** `01-local-rate-limit.yaml`

### 2. Global Per-Tool Rate Limiting (CEL descriptors)

Uses CEL to parse the JSON-RPC body and extract `method` + `params.name`. Each tool gets its own counter bucket in Redis. Only `tools/call` requests are counted; `initialize` and `tools/list` pass through uncounted.

**When to use:** per-tool differentiation, expensive vs cheap tools, exclude non-tool operations.

**File:** `02-global-per-tool-ratelimit.yaml`

## How It Works (Global Per-Tool)

```
MCP Client
    | POST /mcp/multitool
    | Body: {"method":"tools/call","params":{"name":"echo",...}}
    v
AgentGateway Proxy
    | CEL evaluates descriptors:
    |   mcp_method = "tools/call"
    |   tool_name  = "echo"
    v
envoyproxy/ratelimit (gRPC)
    | Looks up: mcp_method=tools/call -> tool_name=echo -> 10/min
    | Redis counter: echo_count++ -> 4 of 10 -> OK
    v
MCP Server (tool executes)
```

For non-tool operations (initialize, tools/list):
```
CEL evaluates: mcp_method = "other", tool_name = "none"
Rate limiter: no matching rule for "other" -> pass through (not counted)
```

### CEL Expressions Explained

```cel
# Descriptor 1: Identify tools/call vs everything else
json(request.body).with(body,
  body.method == "tools/call" ? "tools/call" : "other"
)
# "tools/call" -> has matching rate limit rule (counted)
# "other"      -> no matching rule (not counted)

# Descriptor 2: Extract tool name for per-tool counters
json(request.body).with(body,
  body.method == "tools/call" ? string(body.params.name) : "none"
)
# "echo"                         -> counter bucket: echo
# "trigger-long-running-operation" -> counter bucket: trigger-long-running-operation
# "none"                         -> only sent with "other" (no rule matches anyway)
```

### Rate Limiter ConfigMap Tree

```yaml
domain: mcp-tools
descriptors:
  - key: mcp_method
    value: tools/call           # Only match tools/call (not initialize, tools/list)
    descriptors:
      - key: tool_name
        value: trigger-long-running-operation   # Expensive: 3/min
        rate_limit: { unit: minute, requests_per_unit: 3 }
      - key: tool_name
        value: sampleLLMCall                    # Expensive: 3/min
        rate_limit: { unit: minute, requests_per_unit: 3 }
      - key: tool_name                          # Everything else: 10/min
        rate_limit: { unit: minute, requests_per_unit: 10 }
```

### Why NOT Use the Enterprise Rate Limiter?

The Enterprise `rate-limiter-enterprise-agentgateway-*` services use `RateLimitConfig` CRDs which auto-prepend `"namespace.name"` as a `generic_key` first-level descriptor. The MCP CEL descriptors (`mcp_method`, `tool_name`) don't include this auto-prefix, so the descriptor tree never matches.

The standalone `envoyproxy/ratelimit` with a ConfigMap expects the exact descriptor keys the proxy sends — no auto-prefix transformation.

## Sizing MCP Rate Limits

Each MCP client session makes ~3-5 HTTP requests:

| Client action | HTTP requests |
|---------------|---------------|
| Connect       | `initialize` -> 1 POST |
| List tools    | `tools/list` -> 1 POST |
| Call a tool   | `tools/call` -> 1 POST |
| **Total**     | **~3-5 POSTs per tool call session** |

- **Local rate limiting:** A `requests: 5` per-second limit allows ~1 tool call session/sec
- **Global per-tool:** Only `tools/call` counts, so the limit maps 1:1 to tool invocations

## Files

| File | Description |
|------|-------------|
| `01-local-rate-limit.yaml` | Simple local rate limit (token bucket on MCP route) |
| `01-transform-extract-tool-name.yaml` | CEL transformation to extract tool name into `x-tool-name` header (for routing use cases) |
| `02-global-per-tool-ratelimit.yaml` | Full per-tool setup: Redis + ratelimit + ConfigMap + AgentgatewayPolicy |

## Validated

- **Version:** AgentGateway Enterprise 2.3.0-beta.4
- **Date:** 2026-03-21

## Test Commands

### Prerequisites

Set your gateway address:
```bash
export GW="<your-gateway-hostname>"
```

### Test Local Rate Limiting

```bash
# Apply local rate limit (3 req/min, no burst for easy testing)
kubectl apply -f 01-local-rate-limit.yaml

# Verify policy is accepted
kubectl get agentgatewaypolicy mcp-local-rate-limit -n agentgateway-system \
  -o jsonpath='{.status.ancestors[0].conditions}' | jq .

# Initialize MCP session
curl -s -D /tmp/mcp-init.txt "https://${GW}/mcp/multitool" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

SESSION_ID=$(grep -i "mcp-session-id" /tmp/mcp-init.txt | tr -d '\r' | awk '{print $2}')

# Send 5 tools/call requests (expect 429 after the limit is hit)
for i in $(seq 1 5); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${GW}/mcp/multitool" \
    --max-time 10 \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: ${SESSION_ID}" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":$((i+100)),\"method\":\"tools/call\",\"params\":{\"name\":\"echo\",\"arguments\":{\"message\":\"test-$i\"}}}")
  echo "Request $i: HTTP $HTTP_CODE"
done
# Expected: first 2 pass (initialize used 1 of 3 tokens), then 429
```

### Test Global Per-Tool Rate Limiting

```bash
# Deploy rate limit infrastructure + policy
kubectl apply -f 02-global-per-tool-ratelimit.yaml

# Wait for ratelimit pod
kubectl rollout status deployment/mcp-ratelimit -n agentgateway-system --timeout=60s
kubectl rollout status deployment/mcp-redis -n agentgateway-system --timeout=60s

# Verify policy is accepted
kubectl get agentgatewaypolicy mcp-per-tool-rate-limit -n agentgateway-system \
  -o jsonpath='{.status.ancestors[0].conditions}' | jq .

# Initialize MCP session (this does NOT count against tool limits)
curl -s -D /tmp/mcp-init.txt "https://${GW}/mcp/multitool" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

SESSION_ID=$(grep -i "mcp-session-id" /tmp/mcp-init.txt | tr -d '\r' | awk '{print $2}')

# Send 12 tools/call to "echo" (limit: 10/min for default tools)
for i in $(seq 1 12); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://${GW}/mcp/multitool" \
    --max-time 10 \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: ${SESSION_ID}" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":$((i+200)),\"method\":\"tools/call\",\"params\":{\"name\":\"echo\",\"arguments\":{\"message\":\"test-$i\"}}}")
  echo "Request $i: HTTP $HTTP_CODE"
done
# Expected: first 10 pass, then 429

# Check rate limiter logs for descriptor hits
kubectl logs -l app=mcp-ratelimit -n agentgateway-system --tail=20 | grep -i "over_limit\|OK"
```

### Verify Rate Limit Headers in Responses

**Local rate limiting:** Headers (`x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-reset`) only appear on **429 responses**, not on successful 200s.

**Global rate limiting:** Headers appear on **every response** (both 200 and 429).

```bash
# Send a request and check rate limit headers
curl -sv "https://${GW}/mcp/multitool" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: ${SESSION_ID}" \
  -d '{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"echo","arguments":{"message":"header-check"}}}' 2>&1 | grep -i "x-ratelimit\|x-envoy-ratelimited"
# Expected headers (on 429 for local, on every response for global):
#   x-ratelimit-limit: 3           (local) or  10, 10;w=60  (global)
#   x-ratelimit-remaining: 0       (local) or  9            (global)
#   x-ratelimit-reset: 45          (seconds until counter resets)
```

### Cleanup

```bash
# Remove test resources
kubectl delete agentgatewaypolicy mcp-local-rate-limit mcp-per-tool-rate-limit -n agentgateway-system
kubectl delete deployment mcp-ratelimit mcp-redis -n agentgateway-system
kubectl delete svc mcp-ratelimit mcp-redis -n agentgateway-system
kubectl delete cm mcp-ratelimit-config -n agentgateway-system
kubectl delete ratelimitconfig mcp-per-tool-limits -n agentgateway-system
kubectl delete httproute combined-multitool-route -n agentgateway-system
kubectl delete agentgatewaybackend combined-multitool-backend -n agentgateway-system
```

## Reference

- [AgentGateway MCP Rate Limiting Docs](https://agentgateway.dev/docs/kubernetes/main/mcp/rate-limit/)
