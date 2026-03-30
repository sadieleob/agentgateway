# OpenAPI-to-MCP Architecture — demo-cluster-oas

**Date:** 2026-03-30
**Cluster:** demo-cluster-oas (EKS, us-west-2)
**Version:** Enterprise AgentGateway v2.3.0-beta.6
**Gateway:** `agentgateway` (single gateway, hostname `mcp.servebeer.com`)

---

## Overview

This cluster demonstrates the **OpenAPI-to-MCP** feature of Enterprise AgentGateway. REST APIs (Figma, GitLab, Databricks, ServiceNow, Petstore) are exposed as MCP servers through `EnterpriseAgentgatewayBackend` (EAGBE) resources. The proxy translates OpenAPI specs into MCP tool definitions and converts MCP tool calls into REST API requests.

Each service follows the same pattern: an EAGBE with an OpenAPI schema reference, an HTTPRoute for path-based routing, and EAGPols for TLS/CORS, JWT auth, and OAuth token exchange.

---

## Architecture Diagram

```text
                                    ┌──────────────────────────────┐
                                    │      Azure AD / Entra ID     │
                                    │      (JWKS endpoint)         │
                                    │      login.microsoftonline   │
                                    └──────────▲───────────────────┘
                                               │ JWKS fetch
                                               │ (via entra-jwks AGBE)
                                               │
┌──────────┐     ┌─────────────────────────────┼─────────────────────────────────────┐
│          │     │  Gateway: agentgateway       │                                    │
│  MCP     │     │  Host: mcp.servebeer.com     │                                    │
│  Client  ├────►│  NLB (port 443)              │                                    │
│          │     │                               │                                    │
│  (JWT)   │     │  HTTPRoutes (path-based):     │                                    │
└──────────┘     │                               │                                    │
                 │  /figma/openapi/mcp ─────────►│ ent-figma-openapi-backend ────────►│ api.figma.com
                 │                               │   (EAGBE, inline auth)             │
                 │  /gitlab/openapi/mcp ────────►│ ent-gitlab-openapi-backend ───────►│ gitlab.com/api/v4
                 │                               │   (EAGBE, inline auth)             │
                 │  /databricks/.../mcp ────────►│ ent-databricks-statements-...  ───►│ dbc-*.databricks.com
                 │                               │   (EAGBE, external auth)           │
                 │  /servicenow/.../mcp ────────►│ ent-servicenow-openapi-... ───────►│ dev364551.service-now.com
                 │                               │   (EAGBE, external auth)           │
                 │  /petstore/openapi/mcp ──────►│ ent-petstore-openapi-backend ─────►│ petstore3.swagger.io
                 │                               │   (EAGBE, no auth)                 │
                 │                               │                                    │
                 │  /.well-known/oauth-*  ──────►│ (served by proxy, per-backend)     │
                 │                               │                                    │
                 └───────────────────────────────┴────────────────────────────────────┘
```

---

## Key Concept: EnterpriseAgentgatewayBackend (EAGBE)

The EAGBE is the core resource. It defines:

1. **`spec.entMcp.targets[]`** — upstream REST API with OpenAPI schema reference
   - `protocol: OpenAPI` tells the proxy to convert REST<->MCP
   - `openAPI.schemaRef.name` points to a ConfigMap with the OpenAPI spec
2. **`spec.policies`** (optional, inline) — JWT auth, TLS
3. HTTPRoute `backendRef` uses `group: enterpriseagentgateway.solo.io` (not `agentgateway.dev`)

```text
  EAGBE                              ConfigMap (OpenAPI schema)
  ┌──────────────────────┐           ┌────────────────────────┐
  │ spec.entMcp:         │           │ data:                  │
  │   targets:           │           │   schema: |            │
  │   - name: my-api     │ ────────► │     {"openapi":"3.0",  │
  │     static:          │  schemaRef│      "paths":{...}}    │
  │       host: api.com  │           └────────────────────────┘
  │       port: 443      │
  │       protocol: OpenAPI          Proxy translates OpenAPI paths
  │                      │           into MCP tools at runtime
  └──────────────────────┘
```

---

## Two Auth Architecture Patterns

### Pattern A: Inline Auth (Figma, GitLab)

Auth is defined **inside** the EAGBE at `spec.policies.mcp.authentication`. Required when token exchange needs the proxy to resolve the elicitation URL from inline policies.

```text
  EAGBE (spec.policies.mcp.authentication)     EAGPol (token exchange)
  ┌────────────────────────────────┐            ┌──────────────────────┐
  │ JWT validation (inline)        │            │ tokenExchange:       │
  │   issuer, audiences, jwks      │◄───────────│   secretName: ...    │
  │   resourceMetadata (issuer-    │  targets   │ targetRefs:          │
  │     proxy URL for elicitation) │  EAGBE     │   - kind: EAGBE      │
  └────────────────────────────────┘            └──────────────────────┘

  EAGPol (TLS + CORS)
  ┌───────────────────────┐
  │ backend.tls: {}       │
  │ traffic.cors: ...     │
  │ targetRefs:           │
  │   - kind: HTTPRoute   │
  └───────────────────────┘
```

**Why inline?** The proxy uses `inlinePolicies.mcpAuthentication` to resolve the elicitation URL. If auth is external (EAGPol), the proxy falls back to `https://example.com/elicitation` and token exchange fails with MCP error -32001.

### Pattern B: External Auth (Databricks, ServiceNow)

Auth is defined in a **separate EAGPol** targeting the EAGBE. The EAGBE has no inline policies.

```text
  EAGBE (no inline policies)     EAGPol (JWT auth)         EAGPol (token exchange)
  ┌──────────────────┐           ┌──────────────────┐      ┌──────────────────────┐
  │ spec.entMcp only │◄──────────│ authentication:  │      │ tokenExchange:       │
  │ (clean)          │  targets  │   issuer, jwks   │◄─────│   secretName: ...    │
  └──────────────────┘  EAGBE    │   resourceMetadata│ targets EAGBE             │
                                 └──────────────────┘      └──────────────────────┘
```

**Note:** This pattern works for Databricks and ServiceNow but fails for Figma/GitLab. The difference may be related to how the token exchange flow resolves the elicitation URL for different OAuth providers.

---

## Request Flow (step by step)

1. **MCP Client** sends request to `mcp.servebeer.com/<service>/openapi/mcp`
2. **JWT Validation** — Entra ID JWT is validated (inline or via EAGPol) against JWKS from `login.microsoftonline.com`
3. **`.well-known` Discovery** — Client discovers auth requirements via:
   - `/.well-known/oauth-protected-resource/<path>`
   - `/.well-known/oauth-authorization-server/<path>`
4. **Token Exchange** — EAGPol exchanges the downstream JWT for an upstream OAuth token:
   - Secret contains `client_id`, `client_secret`, `authorize_url`, `access_token_url`
   - Token stored in PostgreSQL via the controller's STS endpoint
5. **OpenAPI-to-MCP Translation** — Proxy reads the ConfigMap OpenAPI schema, converts REST paths to MCP tools
6. **Upstream REST Call** — MCP tool call is translated to a REST API request with the exchanged OAuth token

```text
  Client                   AgentGateway Proxy            Controller STS         Upstream API
    │                            │                            │                     │
    │── MCP initialize ─────────►│                            │                     │
    │                            │── validate JWT ───────────►│ Entra ID            │
    │◄── .well-known metadata ──│                            │                     │
    │                            │                            │                     │
    │── (user authorizes via     │                            │                     │
    │    browser OAuth flow) ───►│── token exchange ─────────►│                     │
    │                            │   (client_id + secret +    │                     │
    │                            │    subject_token=JWT)      │                     │
    │                            │◄── access_token ──────────│                     │
    │                            │                            │                     │
    │── tools/list ─────────────►│                            │                     │
    │◄── [MCP tools from         │ (generated from OpenAPI    │                     │
    │     OpenAPI schema] ──────│   schema in ConfigMap)      │                     │
    │                            │                            │                     │
    │── tools/call (e.g.         │                            │                     │
    │   getMe) ─────────────────►│── GET /v1/me ─────────────────────────────────── │
    │                            │   + Authorization: Bearer  │                     │
    │                            │     <exchanged_token>      │                     │
    │◄── tool result ───────────│◄── JSON response ──────────────────────────────── │
```

---

## Services Configured

| Service | EAGBE | Auth Pattern | Upstream Host | Status |
| ------- | ----- | ------------ | ------------- | ------ |
| Figma | `ent-figma-openapi-backend` | Inline | api.figma.com | JWKS CM missing |
| GitLab | `ent-gitlab-openapi-backend` | Inline | gitlab.com/api/v4 | JWKS CM missing |
| Databricks | `ent-databricks-statements-openapi-backend` | External | dbc-c2685736-8254.cloud.databricks.com | Accepted |
| ServiceNow | `ent-servicenow-openapi-backend` | External | dev364551.service-now.com | Accepted |
| Petstore | `ent-petstore-openapi-backend` | None (public) | petstore3.swagger.io | Accepted |

**Known Issue:** Figma and GitLab EAGBEs show `accepted=False` because the JWKS ConfigMap (`enterprise-jwks-store-*`) is not populated. Fix: `kubectl rollout restart deploy/enterprise-agentgateway -n agentgateway-system`. This is a recurring issue after controller restarts or upgrades.

---

## CRD Patch Required (Issue #522)

The default EnterpriseAgentgatewayPolicy CRD CEL validation only allows targeting `Gateway`, `HTTPRoute`, and `AgentgatewayBackend` (OSS). To target an `EnterpriseAgentgatewayBackend`, the CRD must be patched to add it to the allowed `targetRefs` list.

Without this patch, token exchange EAGPols that target EAGBEs are rejected by validation.

---

## Shared Resources

| Resource | Kind | Purpose |
| -------- | ---- | ------- |
| `entra-jwks` | AgentgatewayBackend (OSS) | JWKS endpoint (`login.microsoftonline.com:443`). Shared by all backends with Entra ID auth |
| `enterprise-jwks-store-*` | ConfigMap | Controller-managed JWKS key cache. Auto-populated, but can disappear on restart |

---

## Notes

- Each service has its own OpenAPI schema ConfigMap (e.g., `figma-openapi-schema`, `databricks-statements-openapi-schema`)
- The `mcp_resource` field in token exchange Secrets must match the HTTPRoute path prefix exactly
- `*.well-known` paths are routed alongside each MCP path in the same HTTPRoute
- Some Databricks tools return `invalid utf-8 sequence` errors — this is a proxy bug in the OpenAPI-to-MCP response parser for binary/compressed content
- The Petstore backend has no auth (public API) and serves as a simple test endpoint
