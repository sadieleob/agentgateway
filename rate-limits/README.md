# Rate Limiting Per Token & Per Client ID (from JWT) in AgentGateway Enterprise

AgentGateway Enterprise supports two key types of rate limiting, and you can combine them with JWT claims to achieve per-client-ID limits. Here's a complete guide.

## Overview

There are three rate limiting modes available in `RateLimitConfig`:

- **`type: REQUEST`** — counts each HTTP request
- **`type: TOKEN`** — counts LLM tokens used (prompt + completion)
- **CEL-based** — uses CEL expressions to extract dynamic values (including JWT claims) as rate limit keys

You can use CEL expressions like `jwt.client_id`, `jwt.sub`, `jwt.email`, etc. to extract claims from a validated JWT and use them as the rate limit descriptor key. This means each unique client identity gets its own rate limit bucket.

> Source: [Rate limiting docs](https://docs.solo.io/agentgateway/latest/llm/rate-limiting/), [CEL expressions reference](https://agentgateway.dev/docs/standalone/main/reference/cel/)

---

## Prerequisites

- Set up an agentgateway proxy
- Set up access to the OpenAI LLM provider
- Set up JWT authentication (see below)

---

## Step 1: Configure JWT Authentication

First, you need JWT validation so that the `jwt.*` CEL variables are populated. Create an `EnterpriseAgentgatewayPolicy` with JWT authentication:

```bash
kubectl apply -f - <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: jwt-auth-policy
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agentgateway-proxy
  traffic:
    jwtAuthentication:
      mode: Strict
      providers:
      - issuer: "https://your-idp.example.com/"
        jwks:
          remote:
            jwksPath: "/.well-known/jwks.json"
            cacheDuration: "5m"
            backendRef:
              group: ""
              kind: Service
              name: your-idp-service
              namespace: your-namespace
              port: 8080
EOF
```

> Source: [Set up JWT auth](https://docs.solo.io/agentgateway/latest/security/jwt/)

See [`08-jwt-auth-policy.yaml`](08-jwt-auth-policy.yaml) for a working example with Microsoft Entra ID.

---

## Step 2: Token-Based Rate Limit Per Client ID (from JWT)

To rate limit by LLM tokens per client ID extracted from a JWT claim, use a CEL expression with `type: TOKEN`:

```bash
kubectl apply -f- <<EOF
apiVersion: ratelimit.solo.io/v1alpha1
kind: RateLimitConfig
metadata:
  name: token-per-client-rate-limit
  namespace: agentgateway-system
spec:
  raw:
    descriptors:
    - key: "client_id"
      rateLimit:
        requestsPerUnit: 10000   # 10,000 tokens per hour per client
        unit: HOUR
    rateLimits:
    - actions:
      - cel:
          expression: 'jwt.client_id'    # Extract client_id claim from JWT
          key: "client_id"
      type: TOKEN                        # Count LLM tokens, not requests
EOF
```

> Source: The `type: TOKEN` field is documented at [Rate limiting > Token-based rate limit](https://docs.solo.io/agentgateway/latest/llm/rate-limiting/). The CEL `jwt.*` expression is documented in the [CEL expressions reference](https://agentgateway.dev/docs/standalone/main/reference/cel/) and demonstrated in [GitHub issue #850](https://github.com/agentgateway/agentgateway/issues/850).

See [`09-token-per-client-ratelimitconfig.yaml`](09-token-per-client-ratelimitconfig.yaml) for a working example using `jwt.appid` (Entra ID v1.0 claim).

---

## Step 3: Request-Based Rate Limit Per Client ID (from JWT)

To rate limit by number of requests per client ID, use a CEL expression with `type: REQUEST` (or omit `type` as `REQUEST` is the default):

```bash
kubectl apply -f- <<EOF
apiVersion: ratelimit.solo.io/v1alpha1
kind: RateLimitConfig
metadata:
  name: request-per-client-rate-limit
  namespace: agentgateway-system
spec:
  raw:
    descriptors:
    - key: "client_id"
      rateLimit:
        requestsPerUnit: 100    # 100 requests per minute per client
        unit: MINUTE
    rateLimits:
    - actions:
      - cel:
          expression: 'jwt.client_id'    # Extract client_id claim from JWT
          key: "client_id"
      type: REQUEST                      # Count requests (not tokens)
EOF
```

See [`01-ratelimitconfig-request.yaml`](01-ratelimitconfig-request.yaml) for a global request rate limit example, and [`05-per-agent-ratelimitconfig.yaml`](05-per-agent-ratelimitconfig.yaml) for per-agent request + token limits using `x-client-id` header.

---

## Step 4: Apply Rate Limits with EnterpriseAgentgatewayPolicy

Apply one or both rate limit configs via an `EnterpriseAgentgatewayPolicy`:

```bash
kubectl apply -f- <<EOF
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: per-client-rate-limits
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: openai
  traffic:
    entRateLimit:
      global:
        rateLimitConfigRefs:
        - name: token-per-client-rate-limit
        - name: request-per-client-rate-limit
EOF
```

> Source: [Rate limiting docs — EnterpriseAgentgatewayPolicy](https://docs.solo.io/agentgateway/latest/llm/rate-limiting/)

See [`03-unified-ratelimit-policy.yaml`](03-unified-ratelimit-policy.yaml) for a working example that combines global, per-agent, and per-client token rate limits using `AgentgatewayPolicy` with CEL descriptors.

---

## Files in This Directory

| File | Description |
|------|-------------|
| [`00-redis.yaml`](00-redis.yaml) | Shared Redis backend for rate limiter |
| [`01-ratelimitconfig-request.yaml`](01-ratelimitconfig-request.yaml) | Global request rate limit (all providers) |
| [`02-ratelimitconfig-token.yaml`](02-ratelimitconfig-token.yaml) | Global token rate limit (all providers) |
| [`03-unified-ratelimit-policy.yaml`](03-unified-ratelimit-policy.yaml) | Unified AgentgatewayPolicy combining all rate limit descriptors |
| [`04-anthropic-backend.yaml`](04-anthropic-backend.yaml) | Anthropic LLM backend |
| [`05-per-agent-ratelimitconfig.yaml`](05-per-agent-ratelimitconfig.yaml) | Per-agent request + token rate limits (keyed by x-client-id) |
| [`06-per-agent-policy.yaml`](06-per-agent-policy.yaml) | Per-agent AgentgatewayPolicy with CEL descriptors |
| [`07-body-model-transform.yaml`](07-body-model-transform.yaml) | Body-based model/provider routing transform |
| [`08-jwt-auth-policy.yaml`](08-jwt-auth-policy.yaml) | JWT authentication (Microsoft Entra ID) |
| [`09-token-per-client-ratelimitconfig.yaml`](09-token-per-client-ratelimitconfig.yaml) | Per-client token rate limit (keyed by jwt.appid) |
