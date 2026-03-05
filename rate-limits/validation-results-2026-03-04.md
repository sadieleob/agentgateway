# Rate Limit Validation Results - Unified Cross-Provider + Per-Agent (2026-03-04)

> **Cluster**: `sortega-eks-demo` (EKS us-west-2)
> **Gateway**: `agentgateway-routing-demo` (enterprise-agentgateway v2.2.0-beta.5)
> **Date**: 2026-03-04
> **Route**: `llm-provider-route` (single `/llm/v1/chat/completions` → header-based routing to OpenAI or Anthropic)

## Architecture

```
Client → Gateway (agentgateway-routing-demo)
  → PreRouting ExtAuth (mock-extauth:9001)
    - Parses request body → extracts model name
    - Resolves provider (openai/anthropic) from model name
    - Sets headers: x-model-provider, x-model-name, x-client-id
  → Body Model Transform (EAGPol)
    - Merges ExtAuth-approved model into request body
    - Sets x-model-provider header for routing
  → Rate Limiting (AgentgatewayPolicy)
    - Global request counter: 3/min (all agents, all providers)
    - Per-agent request counter: 50/min per agent (keyed by x-client-id)
  → HTTPRoute header-based routing
    - x-model-provider=openai → openai-llm-backend
    - x-model-provider=anthropic → anthropic-llm-backend
```

## Configuration

### Rate Limit Resources Applied

| Resource | Type | Settings | Scope |
|----------|------|----------|-------|
| `RateLimitConfig/llm-request-rate-limit` | REQUEST | 3 req/min | Global (all agents, all providers) |
| `RateLimitConfig/llm-token-rate-limit` | TOKEN | 100 tokens/min | Global (all agents, all providers) |
| `RateLimitConfig/per-agent-request-rate-limit` | REQUEST | 50 req/min | Per-agent (keyed by x-client-id) |
| `RateLimitConfig/per-agent-token-rate-limit` | TOKEN | 10000 tokens/min | Per-agent (keyed by x-client-id) |
| `AgentgatewayPolicy/llm-rate-limit` | Policy | Unified (global + per-agent descriptors) | Targets `llm-provider-route` |
| `EnterpriseAgentgatewayPolicy/body-model-transform` | Policy | Body merge + header set via `extauthz[]` | Targets `llm-provider-route` |

### Policies Status

| Policy | Type | Status |
|--------|------|--------|
| `llm-rate-limit` | AgentgatewayPolicy | Accepted + Attached |
| `body-model-transform` | EnterpriseAgentgatewayPolicy | Accepted + Attached |
| `extauth-model-override` | EnterpriseAgentgatewayPolicy | Accepted + Attached |

## Test Results

### Test 1: Global Rate Limit (3 req/min)

| Request | Model | Provider | x-client-id | HTTP | Notes |
|---------|-------|----------|-------------|------|-------|
| 1 | gpt-4o-mini | openai | unknown (default) | 200 | |
| 2 | gpt-4o-mini | openai | unknown (default) | 200 | |
| 3 | gpt-4o-mini | openai | unknown (default) | 200 | |
| 4 | gpt-4o-mini | openai | unknown (default) | **429** | Global limit hit |
| 5 | gpt-4o-mini | openai | unknown (default) | **429** | Global limit enforced |

**Result**: PASS — Global limit enforced at exactly 3 req/min.

### Test 2: Per-Agent Isolation

| Request | Agent | Model | HTTP | Global Counter | Per-Agent Counter |
|---------|-------|-------|------|----------------|-------------------|
| 1 | agent-alpha | gpt-4o-mini | 200 | 1 | alpha=1 |
| 2 | agent-alpha | gpt-4o-mini | 200 | 2 | alpha=2 |
| 3 | agent-beta | gpt-4o-mini | 200 | 3 | beta=1 |
| 4 | agent-beta | gpt-4o-mini | **429** | 4 | beta=2 |

**Redis Keys**:
- `x-client-id^agent-alpha` — separate per-agent counter
- `x-client-id^agent-beta` — separate per-agent counter
- `llm-request-counter` — shared global counter

**Result**: PASS — Agents get separate per-agent buckets while sharing the global bucket.

### Test 3: Cross-Provider Unified Counter

| Request | Agent | Model | Provider | HTTP | Notes |
|---------|-------|-------|----------|------|-------|
| 1 | agent-gamma | gpt-4o-mini | openai | 200 | |
| 2 | agent-gamma | gpt-4o-mini | openai | 200 | |
| 3 | agent-gamma | claude-sonnet-4-20250514 | anthropic | 200* | *Timeout (backend slow), but counted |
| 4 | agent-gamma | claude-sonnet-4-20250514 | anthropic | **429** | Global limit hit |

**Redis Keys**:
- `x-client-id^agent-gamma` = 4 — single counter across both providers
- `llm-request-counter` = 4 — single global counter across both providers

**Result**: PASS — OpenAI and Anthropic requests share the same global and per-agent counters.

## Key Findings

### 1. `entRateLimit` with `rateLimitConfigRefs` Does NOT Enforce (Bug)

- `EnterpriseAgentgatewayPolicy` with `entRateLimit` + `rateLimitConfigRefs` does NOT work in agentgateway-enterprise 2.2.0-beta.5
- The gateway shows `remoteRateLimit` in config dump but never sends gRPC calls to the rate limiter
- **Workaround**: Use `AgentgatewayPolicy` with `rateLimit.global.backendRef` + explicit descriptors

### 2. Only ONE `rateLimit` Policy Per HTTPRoute

- Multiple `AgentgatewayPolicy` resources with `rateLimit` targeting the same HTTPRoute silently conflict
- Both show Accepted + Attached but rate limiting stops working entirely
- **Solution**: Merge all descriptor sets into a single `AgentgatewayPolicy`

### 3. Missing CEL Header Causes Entire Rate Limit Check to Fail Open

- If `request.headers["x-client-id"]` can't evaluate (header missing), ALL descriptor sets are skipped
- This includes the global counter — no rate limiting at all
- **Critical**: The PreRouting ExtAuth must ALWAYS set `x-client-id` (default to "unknown" when no agent identity is available)

### 4. `has()` CEL Function Causes Gateway Panic

- `has(request.headers["x-client-id"]) ? ... : "unknown"` crashes the Rust-based gateway with `core::result::unwrap_failed`
- The `has()` function is NOT supported in this CEL implementation
- **Workaround**: Ensure the header is always present (set by ExtAuth)

### 5. RateLimitConfig Auto-Prepends `namespace.name` Prefix

- The rate limiter auto-prepends `namespace.name` as a `generic_key` level in the descriptor tree
- If the RateLimitConfig descriptors also include a `generic_key` with the same value, a duplicate 3-level tree is created
- This causes a mismatch with the 2-entry policy descriptor → no counters created
- **Solution**: Only include non-prefix descriptor levels in the RateLimitConfig

### 6. `extauthz[]` Accessor Works in Body Merge

- `extauthz["x-model-provider"]` and `extauthz["x-model-name"]` in EnterpriseAgentgatewayPolicy transformation work
- Body merge: `toJson(json(request.body).merge({"model": extauthz["x-model-name"]}))` replaces model field
- Header set: `extauthz["x-model-provider"]` sets routing header from ExtAuth response

### 7. Cross-Subnet EKS Connectivity Issue

- Pods on different subnets (10.0.1.x vs 10.0.2.x) may not be able to reach each other
- Curl test pods must be scheduled on the same node as the gateway pod
- Use `nodeName` in pod spec to force scheduling

## Descriptor Tree Reference

Rate limiter config dump (`/rlconfig/`):
```
domain: solo.io
  - solo.io|generic_key^agentgateway-system.llm-request-rate-limit|generic_key^llm-request-counter: 3/MINUTE (REQUEST)
  - solo.io|generic_key^agentgateway-system.llm-token-rate-limit|generic_key^llm-token-counter: 100/MINUTE (TOKEN)
  - solo.io|generic_key^agentgateway-system.per-agent-request-rate-limit|x-client-id: 50/MINUTE (REQUEST)
  - solo.io|generic_key^agentgateway-system.per-agent-token-rate-limit|x-client-id: 10000/MINUTE (TOKEN)
```

## Files

| File | Purpose |
|------|---------|
| `00-redis.yaml` | Redis deployment (shared instance) + ext-cache services |
| `01-ratelimitconfig-request.yaml` | Global request rate limit (3 req/min) |
| `02-ratelimitconfig-token.yaml` | Global token rate limit (100 tokens/min) |
| `03-unified-ratelimit-policy.yaml` | AgentgatewayPolicy with merged global + per-agent descriptors |
| `04-anthropic-backend.yaml` | Anthropic backend only (secret, backend, HTTPRoute rules) |
| `05-per-agent-ratelimitconfig.yaml` | Per-agent request (50/min) + token (10k/min) rate limits |
| `06-per-agent-policy.yaml` | OBSOLETE — merged into `03-unified-ratelimit-policy.yaml` |
| `07-body-model-transform.yaml` | EAGPol body merge + header set via `extauthz[]` accessors |
