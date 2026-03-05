# Token Consumption Reporting Guidance — T-Mobile

> **Context**: Rajeev/Keith meeting (2026-03-03). Stream owner: Vijay.
> Keith recommended a kickoff call to review available data sources.
> This document prepares for that call.

## Requirement Summary

T-Mobile needs to track **LLM token usage per autonomous agent**:
- Agents identified by Entra ID service principal **client_id**
- Client_id maps to internal CMDB: org → VP → director hierarchy
- Reporting dashboard for token consumption by agent/org
- NOT per-user (human) — per-agent (autonomous)
- Small N of agents → Prometheus cardinality may be acceptable

## Data Source 1: Access Logs (→ Splunk)

### What's available

The `access-log-headers` EnterpriseAgentgatewayPolicy on `agentgateway-routing-demo` captures:

| Attribute | Expression | Content |
|-----------|-----------|---------|
| `request.all_headers` | `request.headers` | All request headers including x-client-id, Authorization (JWT) |
| `response.all_headers` | `response.headers` | All response headers |
| `extauthz.metadata` | `extauthz` | Metadata returned by ExtAuth server (can include parsed JWT claims) |

### Standard agentgateway access log fields

| Field | Example | Notes |
|-------|---------|-------|
| `http.path` | `/llm/v1/chat/completions` | API endpoint |
| `http.method` | `POST` | |
| `http.status` | `200` / `429` | Includes rate limit responses |
| `duration` | `1234ms` | Request duration |
| `trace.id` | `40a7d96a...` | Distributed trace ID |
| `route` | `agentgateway-system/llm-provider-route` | Which route served the request |

### Token usage in logs

Agentgateway logs token usage from the **LLM provider response**:
- `usage.prompt_tokens` — tokens in the request
- `usage.completion_tokens` — tokens in the response
- `usage.total_tokens` — sum
- These come from the OpenAI/Anthropic response body, parsed by agentgateway

### How to correlate with agent identity

1. ExtAuth validates JWT → extracts `client_id` claim → sets `x-client-id` header
2. Access log captures `request.all_headers` → contains `x-client-id`
3. In Splunk: join `x-client-id` + token usage fields per request
4. Aggregate by `x-client-id` → map to CMDB org via lookup table

### Pros/Cons for Splunk

| Pro | Con |
|-----|-----|
| Richest data — full request/response headers, JWT claims | Requires log pipeline to Splunk |
| No cardinality limits | Query latency (not real-time) |
| T-Mobile already uses Splunk | Dashboard build effort |
| Can correlate with other Splunk data sources | |

## Data Source 2: Prometheus Metrics (→ Grafana)

### Default metrics from agentgateway

| Metric | Labels | Notes |
|--------|--------|-------|
| `agentgateway_llm_request_total` | `provider`, `model`, `status` | Request counter |
| `agentgateway_llm_prompt_tokens_total` | `provider`, `model` | Input token counter |
| `agentgateway_llm_completion_tokens_total` | `provider`, `model` | Output token counter |
| `agentgateway_llm_request_duration_seconds` | `provider`, `model` | Latency histogram |

### Adding per-agent dimension

To get per-agent metrics in Prometheus, the `x-client-id` header value would need to
become a Prometheus label. Options:

1. **Custom metric labels via OTel** — configure OpenTelemetry collector to extract
   `x-client-id` from access logs and add as a label dimension
2. **Envoy stats tags** — configure custom stats tags on the agentgateway proxy to
   include `x-client-id` as a metric label (requires proxy config change)

### Cardinality assessment

- Small N of agents (~10-50 autonomous agents per Rajeev)
- Per Keith: "metrics at Prometheus space might be in bounds"
- Multiplication: agents × providers × models × status = ~50 × 2 × 3 × 3 = ~900 series
- This is well within Prometheus limits

### Pros/Cons for Prometheus/Grafana

| Pro | Con |
|-----|-----|
| Real-time dashboards | Cardinality risk if agent count grows |
| Alerting on token consumption | Requires custom label configuration |
| Standard Grafana dashboards | Less context than logs (no full headers) |
| PromQL for complex queries | |

## Recommendation

Per Keith's guidance from the meeting:

> "The log as a data source for creating dashboards will be the richest and most
> scalable approach... But it doesn't mean you have to be limited to that."

**Recommended approach**: Use **both** data sources:

1. **Splunk (primary)**: Full token reporting dashboards with per-agent breakdown,
   org-level rollups, trend analysis. Data from access logs.
2. **Prometheus/Grafana (supplementary)**: Real-time operational dashboards for
   rate limit hit rates, request volume, latency. Alerting on anomalies.

## Action Items for Kickoff Call

- [ ] Solo to demonstrate access log fields and how token usage appears
- [ ] Solo to show default Prometheus metrics for agentgateway LLM
- [ ] T-Mobile (Vijay) to confirm Splunk pipeline availability
- [ ] Discuss: does ExtAuth need to set additional headers for reporting?
- [ ] Discuss: per-agent Prometheus labels — is OTel or proxy config preferred?
- [ ] Agree on dashboard mockup format and delivery timeline
- [ ] Map client_id → CMDB org lookup approach (Splunk lookup table vs API)

## Rate Limit Metrics (Bonus)

Rate limiting generates its own metrics useful for reporting:

| Metric | Meaning |
|--------|---------|
| Rate limit 429 count per agent | How often each agent hits limits |
| Token consumption near threshold | Approaching rate limit |
| Global vs per-agent 429 ratio | Which limit type triggers more |

These can feed into both Splunk and Grafana dashboards.
