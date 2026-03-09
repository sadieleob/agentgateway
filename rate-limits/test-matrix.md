# Rate Limiting Test Matrix — Agentgateway

> **Cluster**: `sortega-eks-demo` (EKS us-west-2)
> **Gateway**: `agentgateway-routing-demo` (enterprise-agentgateway-sadiel)
> **Route**: `llm-provider-route` (unified, body-based routing via PreRouting ExtAuth)
> **Host**: `agentgateway.servebeer.com`
> **Date**: 2026-03-04

## Architecture Under Test

```
Client (with Entra JWT)
  → NLB (port 443)
    → Gateway (agentgateway-routing-demo)
      → PreRouting ExtAuth (mock-extauth:9001)
        - Validates JWT, extracts client_id → sets x-client-id header
        - Reads body model field → sets x-model-provider header (openai|anthropic)
      → Rate Limiting (global + per-agent)
        - EnterpriseAgentgatewayPolicy (entRateLimit) → global counters
        - AgentgatewayPolicy (CEL descriptors) → per-agent counters
      → llm-provider-route (header matching)
        - x-model-provider=openai → openai-llm-backend
        - x-model-provider=anthropic → anthropic-llm-backend
```

## Test Scenarios

### Category 1: Global Rate Limiting (per-provider)

These use `genericKey` counters — all agents share the same bucket per provider.

| # | Scenario | API | Method | Expected | Status |
|---|----------|-----|--------|----------|--------|
| 1.1 | OpenAI request rate limit | `/llm/v1/chat/completions` | POST (non-streaming) | 429 after 3 req/min | |
| 1.2 | OpenAI request rate limit (streaming) | `/llm/v1/chat/completions` | POST (streaming) | 429 after 3 req/min | |
| 1.3 | OpenAI token rate limit | `/llm/v1/chat/completions` | POST | 429 after 100 tokens/min | |
| 1.4 | OpenAI Responses API rate limit | `/llm/v1/responses` | POST | 429 after 3 req/min | |
| 1.5 | Anthropic request rate limit | `/llm/v1/chat/completions` | POST (anthropic model) | 429 after 3 req/min | |
| 1.6 | Anthropic native API rate limit | `/llm/v1/messages` | POST | 429 after 3 req/min | |
| 1.7 | Counter isolation — OpenAI limit doesn't affect Anthropic | Both paths | POST | Independent 429 thresholds | |

### Category 2: Per-Agent Rate Limiting

These use `x-client-id` header as descriptor key — each agent has its own bucket.

| # | Scenario | Setup | Expected | Status |
|---|----------|-------|----------|--------|
| 2.1 | Agent A hits per-agent limit | x-client-id=agent-a, 50+ req/min | Agent A gets 429, Agent B unaffected | |
| 2.2 | Agent B unaffected by Agent A limit | x-client-id=agent-b after A is limited | Agent B succeeds (200) | |
| 2.3 | Per-agent token limit | x-client-id=agent-a, >10000 tokens/min | Agent A gets 429 for tokens | |
| 2.4 | Missing x-client-id header | No header set | Behavior depends on CEL eval — document result | |

### Category 3: Combined Global + Per-Agent

| # | Scenario | Setup | Expected | Status |
|---|----------|-------|----------|--------|
| 3.1 | Global limit triggers before per-agent | Global=3 req/min, per-agent=50 req/min | 429 at 3 req (global), not 50 | |
| 3.2 | Per-agent limit triggers before global | Per-agent=2 req/min (custom), global=50 | 429 at 2 req (per-agent) | |
| 3.3 | Different agents both contribute to global | agent-a: 2 req, agent-b: 2 req | Global should count 4 total | |

### Category 4: ExtAuth + Rate Limiting Integration

| # | Scenario | Setup | Expected | Status |
|---|----------|-------|----------|--------|
| 4.1 | Rate limiting works with PreRouting ExtAuth | Full flow: JWT → ExtAuth → RL → route | 429 after limit, body-based routing works | |
| 4.2 | Rate limit applies before LLM call | Send 4th request within 1 min | 429 returned immediately, no upstream call | |
| 4.3 | ExtAuth sets x-client-id correctly | Check access logs for x-client-id | Header present in rate limit descriptor | |
| 4.4 | Rate limit 429 body content | Exceed limit | Document: empty body vs error message | |

### Category 5: Infrastructure Resilience

| # | Scenario | Setup | Expected | Status |
|---|----------|-------|----------|--------|
| 5.1 | Redis down — failClosed behavior | Delete Redis pod | All requests return 500 (failClosed) | |
| 5.2 | Redis recovery | Recreate Redis pod, restart rate limiters | Rate limiting resumes, counters reset | |
| 5.3 | Rate limiter pod restart | Restart rate-limiter deployment | Counters preserved (Redis-backed) | |
| 5.4 | ext-cache service recreated by operator | Operator reconcile cycle | Verify services still point to Redis | |

### Category 6: Edge Cases

| # | Scenario | Setup | Expected | Status |
|---|----------|-------|----------|--------|
| 6.1 | Concurrent requests near limit | 3 parallel requests at once | Exactly 3 succeed, rest get 429 | |
| 6.2 | Counter reset after 1 minute | Wait 60s after 429 | Next request succeeds (200) | |
| 6.3 | Large streaming response token count | Stream response >100 tokens | Token counter reflects actual usage | |
| 6.4 | Rate limit headers in response | Check response headers | Document: x-ratelimit-* headers present? | |

## Test Commands

### Basic OpenAI request through ExtAuth flow
```bash
GATEWAY_HOST="agentgateway.servebeer.com"
GATEWAY_URL="https://${GATEWAY_HOST}"

# Non-streaming
curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/llm/v1/chat/completions" \
  -H "Host: ${GATEWAY_HOST}" \
  -H "Content-Type: application/json" \
  -H "x-client-id: agent-test-001" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

### Rate limit burst test
```bash
for i in {1..5}; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/llm/v1/chat/completions" \
    -H "Host: ${GATEWAY_HOST}" \
    -H "Content-Type: application/json" \
    -H "x-client-id: agent-test-001" \
    -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}')
  echo "Request $i: HTTP $STATUS"
done
```

### Per-agent isolation test
```bash
# Agent A — exhaust limit
for i in {1..4}; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/llm/v1/chat/completions" \
    -H "Host: ${GATEWAY_HOST}" \
    -H "Content-Type: application/json" \
    -H "x-client-id: agent-alpha" \
    -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}')
  echo "Agent-Alpha request $i: HTTP $STATUS"
done

# Agent B — should still work
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/llm/v1/chat/completions" \
  -H "Host: ${GATEWAY_HOST}" \
  -H "Content-Type: application/json" \
  -H "x-client-id: agent-beta" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}')
echo "Agent-Beta request: HTTP $STATUS (should be 200)"
```

## Validation Checklist (Pre Go-Live)

- [ ] Global request rate limiting enforced (both providers)
- [ ] Global token rate limiting enforced
- [ ] Per-agent request rate limiting enforced
- [ ] Per-agent token rate limiting enforced
- [ ] Combined global + per-agent — earliest limit wins
- [ ] Counter isolation between providers confirmed
- [ ] Counter isolation between agents confirmed
- [ ] ExtAuth + rate limiting chain works end-to-end
- [ ] Streaming and non-streaming both counted
- [ ] Redis failClosed behavior documented
- [ ] 429 response format documented (empty body vs error message)
- [ ] Production rate limit values configured (not test values)
- [ ] Rate limit values reviewed and approved by Arshif/Manoj
