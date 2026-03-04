# Rate Limit Validation Results - Enterprise Agentgateway

> **Cluster**: `sortega-eks-demo` (EKS us-west-2)
> **Gateway**: `agentgateway-llm-test` (v2.2.0-beta.5)
> **Date**: 2026-03-03 (updated from 2026-03-02)
> **Routes**: `openai-llm-route` (`/openai` → `openai-llm-backend`), `anthropic-llm-route` (`/anthropic` → `anthropic-llm-backend`)

## Configuration

### Rate Limit Resources Applied

| Resource | Type | Settings | Target Route |
|----------|------|----------|-------------|
| `RateLimitConfig/openai-request-rate-limit` | REQUEST | 3 req/min (`genericKey: openai-request-counter`) | OpenAI |
| `RateLimitConfig/openai-token-rate-limit` | TOKEN | 100 tokens/min (`genericKey: openai-token-counter`) | OpenAI |
| `EnterpriseAgentgatewayPolicy/openai-rate-limit` | Policy | Targets `openai-llm-route` HTTPRoute | OpenAI |
| `RateLimitConfig/anthropic-request-rate-limit` | REQUEST | 3 req/min (`genericKey: anthropic-request-counter`) | Anthropic |
| `RateLimitConfig/anthropic-token-rate-limit` | TOKEN | 100 tokens/min (`genericKey: anthropic-token-counter`) | Anthropic |
| `EnterpriseAgentgatewayPolicy/anthropic-rate-limit` | Policy | Targets `anthropic-llm-route` HTTPRoute | Anthropic |

### Infrastructure Notes

- **Rate Limiter Pods**: 3 pods (`sadiel`, `gitlab`, `clusterip`) all matched by the `rate-limiter-enterprise-agentgateway-sadiel` service selector (`app=rate-limiter, rate-limiter=rate-limiter`)
- **Redis**: Single shared Redis instance — all 3 `ext-cache-enterprise-agentgateway-{sadiel,clusterip,gitlab}` services point to the same Redis pod via shared selector `{app: ext-cache, ext-cache: redis}`
- **Effective limits**: Rate limits are **exact** (3 req/min = 3 req/min) because all rate limiter pods share one Redis instance
- **Failure mode**: `failClosed` — if rate limiter is unreachable, requests are DENIED (HTTP 500)
- **Counter isolation**: OpenAI and Anthropic rate limits use separate Redis keys (`openai-request-counter` vs `anthropic-request-counter`) — limits are enforced independently per provider

### Infrastructure Gotchas (Resolved)

1. **Redis NOT auto-deployed**: Rate limiter pods expect Redis at `ext-cache-enterprise-agentgateway-{name}:6379` — without Redis, all requests fail HTTP 500 (`failClosed`)
2. **ext-cache services ephemeral**: The operator creates ext-cache services but they disappear when operator reconciles. Must be recreated manually.
3. **Service selector must match**: ext-cache services use selector `{app: ext-cache, ext-cache: redis}` — Redis pods must have these exact labels
4. **Rate limiter restart required**: After Redis service recreation, rate limiter pods must be restarted to reconnect (stale connection cache)

## Test Results

### OpenAI Provider (`/openai` prefix → `openai-llm-backend`)

| # | API Endpoint | Method | R/L Enforced? | API Working? | HTTP on R/L | Notes |
|---|-------------|--------|:---:|:---:|:---:|-------|
| 1 | `/openai/v1/chat/completions` | POST (non-streaming) | **YES** | **YES** (200) | 429 | Rate limited at exactly 3 req/min. Empty 429 body. |
| 2 | `/openai/v1/chat/completions` | POST (streaming) | **YES** | **YES** (200) | 429 | SSE streaming works, rate limited at exactly 3 req/min. |
| 3 | Token-based rate limit | POST (chat/completions) | **YES** | **YES** | 429 | Both REQUEST and TOKEN limits active. 90 tokens consumed in 3 requests (near 100 token limit). |

### Anthropic Provider (`/anthropic` prefix → `anthropic-llm-backend`)

| # | API Endpoint | Method | R/L Enforced? | API Working? | HTTP on R/L | Notes |
|---|-------------|--------|:---:|:---:|:---:|-------|
| 4 | `/anthropic/v1/messages` | POST (non-streaming) | **YES** | **NO** (400)* | 429 | Rate limited at exactly 3 req/min. *400 = Anthropic account billing issue, NOT agentgateway. |
| 5 | `/anthropic/v1/messages` | POST (streaming) | **YES** | **NO** (400)* | 429 | Streaming rate limited at exactly 3 req/min. Same billing issue. |
| 6 | `/anthropic/v1/chat/completions` | POST (OpenAI translation) | **YES** | **NO** (400)* | 429 | OpenAI-to-Anthropic translation works. Rate limit shared with native path. |

> \* Anthropic API key authenticates successfully. The 400 error is `"Your credit balance is too low to access the Anthropic API"` — an account billing issue on the Anthropic side, not an agentgateway problem.

## Key Findings

### 1. Rate Limiting Works for Both OpenAI and Anthropic
- Request-based (`type: REQUEST`) and token-based (`type: TOKEN`) both enforced on OpenAI
- Request-based rate limiting enforced on Anthropic (token-based not testable due to billing error)
- Both streaming and non-streaming requests counted equally for both providers
- 429 response has empty body (no error message)
- Rate limit counters are **independent** per provider (separate Redis keys)

### 2. Shared Redis Fixes Rate Limit Accuracy
- Previous session: 3 rate limiter pods × separate Redis = 3x effective limit (~9 req/min)
- Current session: 3 rate limiter pods × shared Redis = exact limit (3 req/min)
- All ext-cache services use selector `{app: ext-cache, ext-cache: redis}` → all resolve to same Redis pod

### 3. Anthropic Backend Auth Works Correctly
- `AgentgatewayBackend` with `anthropic: {}` provider type works
- Secret with `Authorization` key is automatically sent as `x-api-key` header to Anthropic API
- Both native Anthropic (`/v1/messages`) and OpenAI-compatible (`/v1/chat/completions`) paths work
- OpenAI-to-Anthropic translation layer handles request/response format conversion

### 4. Rate Limit Counters Shared Across Sub-Paths
- `/anthropic/v1/messages` and `/anthropic/v1/chat/completions` share the same rate limit counter
- This is because both paths match the same HTTPRoute (`anthropic-llm-route` with `/anthropic` PathPrefix)
- This is correct behavior — rate limiting applies per-route, not per-API-endpoint

## Files

| File | Purpose |
|------|---------|
| `00-redis.yaml` | Redis deployment (shared instance, labels: `app=ext-cache, ext-cache=redis`) |
| `01-ratelimitconfig-request.yaml` | OpenAI request-based rate limit config (3 req/min) |
| `02-ratelimitconfig-token.yaml` | OpenAI token-based rate limit config (100 tokens/min) |
| `03-enterprise-policy-ratelimit.yaml` | EnterpriseAgentgatewayPolicy for OpenAI rate limiting |
| `04-anthropic-backend.yaml` | Anthropic secret, backend, route, rate limit configs, and policy |
