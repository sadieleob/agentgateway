# Tracking Token Consumption in Agentgateway

Relevant docs:
https://docs.solo.io/agentgateway/2.1.x/llm/observability/
https://agentgateway.dev/docs/standalone/main/reference/cel/

---

## What's available out of the box

### Prometheus metric

There's a histogram called `agentgateway_gen_ai_client_token_usage` exposed on port 15020 of each agentgateway pod (under `/metrics`). It follows the OpenTelemetry GenAI semantic conventions.

To take a look at it:

```bash
kubectl port-forward deployment/agentgateway-proxy -n agentgateway-system 15020
curl http://localhost:15020/metrics | grep agentgateway_gen_ai_client_token_usage
```

The metric ships with these labels: `gen_ai_token_type` (input/output), `gen_ai_operation_name` (e.g. chat), `gen_ai_system` (openai, anthropic, etc.), `gen_ai_request_model`, `gen_ai_response_model`, `gateway`, `listener`, `route`, `route_rule`, and `bind`.

Some useful PromQL:

```promql
# input tokens per model over the last hour
sum by (gen_ai_request_model) (increase(agentgateway_gen_ai_client_token_usage_sum{gen_ai_token_type="input"}[1h]))

# output tokens broken down by provider
sum by (gen_ai_system) (increase(agentgateway_gen_ai_client_token_usage_sum{gen_ai_token_type="output"}[1h]))

# how many requests per model
sum by (gen_ai_request_model) (increase(agentgateway_gen_ai_client_token_usage_count{gen_ai_token_type="input"}[1h]))
```

The catch: this metric doesn't carry any agent identity info (no JWT claims). It's good for aggregate dashboards (tokens per model, per provider, per route) but you can't do per-agent chargeback with it alone. For that, you need to look at the access logs.

### Stdout access logs

Every LLM request produces a structured log line to stdout. You get it with the usual:

```
kubectl logs deployment/agentgateway-proxy -n agentgateway-system
```

Here's what a typical entry looks like:

```
2025-12-12T21:56:02.809082Z  info  request
  gateway=agentgateway-system/agentgateway-proxy
  listener=http
  route=agentgateway-system/openai
  route_rule=openai
  endpoint=api.openai.com:443
  src.addr=127.0.0.1:60862
  http.method=POST
  http.host=localhost
  http.path=/openai
  http.version=HTTP/1.1
  http.status=200
  protocol=llm
  gen_ai.operation.name=chat
  gen_ai.provider.name=openai
  gen_ai.request.model=gpt-3.5-turbo
  gen_ai.response.model=gpt-3.5-turbo-0125
  gen_ai.usage.input_tokens=68
  gen_ai.usage.output_tokens=298
  duration=2488ms
```

The token-related fields you get by default are `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, plus the model/provider info and duration. What you don't get out of the box: JWT claims (who made the request), reasoning tokens, cached tokens, or a total token count. To add those, you need custom access logging with CEL (covered below).

### CEL variables you can use

The full reference is at https://agentgateway.dev/docs/standalone/main/reference/cel/. Here are the ones that matter for token tracking:

**LLM-specific** (only populated when the backend type is `ai`):

The core token counts come from `llm.inputTokens`, `llm.outputTokens`, and `llm.totalTokens`. For models with a reasoning step (o1/o3/gpt-5), there's `llm.reasoningTokens`. Cache-related variables include `llm.cachedInputTokens` (tokens served from cache, which means cost savings) and `llm.cacheCreationInputTokens` (tokens written to cache, Anthropic-specific). There's also `llm.countTokens` which comes from a token-counting endpoint and isn't billed.

For model and provider info you have `llm.requestModel`, `llm.responseModel`, `llm.provider`, and `llm.streaming`. You can also pull the full request/response body with `llm.prompt` and `llm.completion`, but be careful with those in production since they carry a performance hit. Request parameters are available under `llm.params.*` which covers temperature, top_p, max_tokens, frequency_penalty, presence_penalty, and seed.

**JWT** (only present when JWT auth is enabled):

`jwt.sub` gives you the subject claim, which for Entra will be the client_id. You also get `jwt.iss`, `jwt.aud`, and `jwt.azp` for issuer, audience, and authorized party. Any custom claims from the token are accessible via `jwt.<custom>`.

**Other useful ones:** `request.headers`, `source.address`, `source.port`, `response.code`, `backend.name`.

One thing to watch out for: `llm.*` variables are only available in Logging, Tracing, and Metrics policies (i.e., after the LLM response comes back). They're not available in Transformation, Rate Limit, or Authorization policies.

---

## Setting up custom access logging for per-agent tracking

This is the main piece. The idea is to enrich the access logs with JWT claims so you can correlate token usage to specific agents.

### Kubernetes (EnterpriseAgentgatewayPolicy)

> **Note:** The CRD uses `spec.frontend.accessLog.attributes.add` (an array of
> `{name, expression}` objects), not `spec.config.logging.fields.add`.
> Integer CEL values must be wrapped with `string()` and a `default()` fallback.
> The `has(llm)` filter is **not supported** — it causes a CEL compile panic
> that crashes the proxy (`cel/mod.rs:229`). Omit the filter; non-LLM requests
> simply won't populate the `llm.*` fields (they'll show `"n/a"` / `"0"`).

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: token-consumption-logging
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: ai-gateway
  frontend:
    accessLog:
      attributes:
        add:
          # Agent identity — from Entra service principal JWT
          - name: agent.client_id
            expression: 'default(jwt.sub, "unknown")'
          - name: agent.app_name
            expression: 'default(jwt.azp, "unknown")'

          # Token consumption
          - name: tokens.input
            expression: 'default(string(llm.inputTokens), "n/a")'
          - name: tokens.output
            expression: 'default(string(llm.outputTokens), "n/a")'
          - name: tokens.total
            expression: 'default(string(llm.totalTokens), "n/a")'
          - name: tokens.reasoning
            expression: 'default(string(llm.reasoningTokens), "0")'
          - name: tokens.cached_input
            expression: 'default(string(llm.cachedInputTokens), "0")'
          - name: tokens.cache_creation
            expression: 'default(string(llm.cacheCreationInputTokens), "0")'

          # Model and provider
          - name: model.requested
            expression: 'default(llm.requestModel, "n/a")'
          - name: model.actual
            expression: 'default(llm.responseModel, "n/a")'
          - name: model.provider
            expression: 'default(llm.provider, "n/a")'
          - name: model.streaming
            expression: 'default(string(llm.streaming), "n/a")'

          # Request metadata
          - name: request.route
            expression: 'request.path'
          - name: request.source_ip
            expression: 'source.address'
          - name: request.status
            expression: 'string(response.code)'
```

### Adding agent identity to Prometheus metrics

You can also inject JWT claims into the Prometheus metric as custom labels:

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: token-consumption-metrics
  namespace: agentgateway-system
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: ai-gateway
  frontend:
    metrics:
      attributes:
        add:
          - name: agent_client_id
            expression: 'default(jwt.sub, "anonymous")'
          - name: agent_app_name
            expression: 'default(jwt.azp, "unknown")'
```

This slaps `agent_client_id` and `agent_app_name` onto `agentgateway_gen_ai_client_token_usage`, so you can group by agent in Grafana. Fair warning though, if you have a lot of unique client IDs, the label cardinality will blow up your Prometheus storage and slow down queries. Keith specifically called this out in the meeting and recommended sticking with logs for high-cardinality per-agent tracking.

---

## Known limitations (checked against v2.3.0-beta.1, Mar 6 2026)

**Fixed in 2.3.0-beta.1:**

JWT claims were null when using `mcpAuthentication` in logging and metrics ([#255](https://github.com/solo-io/agentgateway-enterprise/issues/255)). This was fixed in OSS PR [#975](https://github.com/agentgateway/agentgateway/pull/975) (merged Feb 16) and synced to the enterprise repo on Feb 24. `jwt.*` variables now work in logging and metrics fields regardless of whether you use `jwtAuthentication` or `mcpAuthentication`.

JWT claims were not available in transformation policies ([#140](https://github.com/solo-io/agentgateway-enterprise/issues/140)). The root cause was a CEL materialization bug where the JWT attribute wasn't registered when transformations ran. Fixed in OSS PR [#1057](https://github.com/agentgateway/agentgateway/pull/1057) (merged Feb 25). Confirmed working in v2.2.0-rc.1 by the issue author (rvennam) on Mar 9. The issue is still open on GitHub but verified as resolved.

Reasoning and cache token CEL variables (`llm.reasoningTokens`, `llm.cachedInputTokens`, `llm.cacheCreationInputTokens`) were not being populated ([#957](https://github.com/agentgateway/agentgateway/issues/957)). This was merged Feb 15 and is included in 2.3.0-beta.1. These variables should now get filled in from the provider response.

**Still open:**

Cache tokens are still missing from the Prometheus histogram metric and traces ([#257](https://github.com/solo-io/agentgateway-enterprise/issues/257)). The CEL variables are now populated (see #957 fix above), so you can get cache token data in access logs, but it's not reported in `agentgateway_gen_ai_client_token_usage` yet. There's an upstream PR [#1144](https://github.com/agentgateway/agentgateway/pull/1144) that adds `input_cache_read` and `input_cache_write` token types to the metric. It's approved with all CI checks passing, so this should land soon.

Token tracking over WebSocket is partially addressed. The original gloo-gateway issue ([#1051](https://github.com/solo-io/gloo-gateway/issues/1051)) was closed and moved to [#299](https://github.com/solo-io/agentgateway-enterprise/issues/299) in the agentgateway-enterprise repo. An upstream fix (PR [#1140](https://github.com/agentgateway/agentgateway/pull/1140), "llm: fix setting LLM info for realtime") was merged Mar 5 which adds LLM metadata plumbing for WebSocket sessions, but the enterprise issue remains open. Full token usage parsing from WebSocket frames for the OpenAI Realtime API is not fully delivered yet.

