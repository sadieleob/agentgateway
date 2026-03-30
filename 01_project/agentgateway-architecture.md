# AgentGateway Architecture — sortega-eks-demo

**Date:** 2026-03-30
**Cluster:** sortega-eks-demo-oas (EKS, us-west-2)
**Version:** Enterprise AgentGateway v2.3.0-beta.6

---

## Overview

This cluster runs two separate AgentGateway instances, each handling a different traffic type:

| Gateway | Traffic Type | Hostname | External Address |
|---------|-------------|----------|-----------------|
| `agentgateway-routing-demo` | LLM | `agentgateway.servebeer.com` | AWS NLB |
| `agentgateway-mcp-combined` | MCP | `mcp.servebeer.com` | AWS ALB |

---

## 1. LLM Traffic — `agentgateway-routing-demo`

### Architecture Diagram

```
                                        ┌─────────────────────────┐
                                        │   mock-extauth (gRPC)   │
                                        │   Port 9001             │
                                        │                         │
                                        │  - Reads request body   │
                                        │  - Extracts model name  │
                                        │  - Returns headers:     │
                                        │    x-model-provider     │
                                        │    x-model-name         │
                                        └────────▲───┬────────────┘
                                                 │   │
                                          req    │   │  response headers
                                          body   │   │  (x-model-provider,
                                                 │   │   x-model-name)
                                                 │   │
┌──────────┐    ┌────────────────────────────┐   │   │    ┌──────────────────────────────────────┐
│          │    │  Gateway:                  │   │   │    │  HTTPRoute: llm-provider-route       │
│  Client  ├───►│  agentgateway-routing-demo ├───┘   └───►│  Host: agentgateway.servebeer.com    │
│          │    │                            │            │                                      │
│          │    │  Host: agentgateway.       │            │  EAGPol: unified-model-transform     │
│          │    │    servebeer.com           │            │  (sets x-model-provider header from  │
│          │    │  NLB (port 443)            │            │   extauthz, overrides model in body) │
│          │    │                            │            │                                      │
│          │    │  EAGPol:                   │            │  Routing rules (header-based):       │
│          │    │    extauth-model-override  │            │                                      │
│          │    │  Phase: PreRouting         │            │  ┌──────────────────────────────────┐ │
│          │    │  (forwards body to         │            │  │x-model-provider: openai          │ │
│          │    │   mock-extauth)            │            │  │+ /llm path                       │ │
└──────────┘    └────────────────────────────┘            │  │  → openai-via-azure-appgw ───────┼─┼──► Azure App GW
                                                         │  │    (iamready.servebeer.com)      │ │    (iamready.servebeer.com)
                                                         │  └──────────────────────────────────┘ │       │
                                                         │  ┌──────────────────────────────────┐ │       ▼
                                                         │  │x-model-provider: anthropic       │ │    OpenAI API
                                                         │  │+ /llm path                       │ │
                                                         │  │  → anthropic-llm-backend ────────┼─┼──► api.anthropic.com
                                                         │  └──────────────────────────────────┘ │
                                                         │  ┌──────────────────────────────────┐ │
                                                         │  │x-model-provider: gemini          │ │
                                                         │  │+ /llm path                       │ │
                                                         │  │  → gemini-llm-backend ───────────┼─┼──► Gemini API
                                                         │  └──────────────────────────────────┘ │
                                                         │  ┌──────────────────────────────────┐ │
                                                         │  │/llm/v1/realtime (WebSocket)      │ │
                                                         │  │  → openai-llm-backend ───────────┼─┼──► OpenAI directly
                                                         │  └──────────────────────────────────┘ │
                                                         │  ┌──────────────────────────────────┐ │
                                                         │  │/llm/v1/responses/ (retrieval)    │ │
                                                         │  │  → openai-passthrough ───────────┼─┼──► OpenAI directly
                                                         │  └──────────────────────────────────┘ │
                                                         └──────────────────────────────────────┘
```

### Request Flow (step by step)

1. **Client** sends an LLM request to `agentgateway.servebeer.com/llm/...` (e.g., `/llm/v1/chat/completions`)
2. **PreRouting phase** — `extauth-model-override` EAGPol intercepts the request:
   - Forwards the request body (up to 8KB) to `mock-extauth` service via gRPC
   - `mock-extauth` parses the body, extracts the model name, and returns `x-model-provider` and `x-model-name` as response headers
3. **Transformation phase** — `unified-model-transform` EAGPol applies to `llm-provider-route`:
   - Sets the `x-model-provider` header from the extauthz response (`extauthz["x-model-provider"]`)
   - Overrides the `model` field in the request body with `extauthz["x-model-name"]`
   - Adjusts `:path` if `model=` query param is present
4. **Routing** — `llm-provider-route` HTTPRoute matches on the `x-model-provider` header:
   - `openai` → `openai-via-azure-appgw` backend (Azure Application Gateway at `iamready.servebeer.com`)
   - `anthropic` → `anthropic-llm-backend`
   - `gemini` → `gemini-llm-backend`
5. **Upstream** — For OpenAI traffic, the Azure Application Gateway (`iamready.servebeer.com`) forwards to the actual OpenAI API

### Key Resources (LLM)

| Resource | Kind | Purpose |
|----------|------|---------|
| `extauth-model-override` | EAGPol | PreRouting extauth → mock-extauth (body inspection) |
| `unified-model-transform` | EAGPol | Post-extauth transformation (header + body override) |
| `openai-via-azure-appgw` | AgentgatewayBackend | OpenAI via Azure App GW (`iamready.servebeer.com:443`) |
| `openai-llm-backend` | AgentgatewayBackend | OpenAI direct (gpt-4o-mini, for WebSocket/realtime) |
| `anthropic-llm-backend` | AgentgatewayBackend | Anthropic direct |
| `gemini-llm-backend` | AgentgatewayBackend | Gemini direct |
| `openai-passthrough` | AgentgatewayBackend | OpenAI direct (response retrieval) |
| `mock-extauth` | Service/Deployment | gRPC extauth server (reads body, returns model headers) |

### Why the Mock ExtAuth Pattern?

The mock-extauth service enables **body-based routing** — something HTTPRoute header matching alone cannot do. The client sends the model name inside the JSON body (e.g., `"model": "gpt-4o"`). The extauth service inspects the body, determines the provider (OpenAI, Anthropic, Gemini), and returns headers that the HTTPRoute can then match on. This decouples the client from knowing which provider to target — the gateway resolves it from the request payload.

---

## 2. MCP Traffic — `agentgateway-mcp-combined`

### Architecture Diagram

```
                                                    ┌─────────────────────┐
                                                    │  Entra ID (Azure AD)│
                                                    │  JWKS Endpoint      │
                                                    │  (JWT validation)   │
                                                    └────────▲────────────┘
                                                             │
                                                             │ JWKS fetch
┌──────────┐    ┌──────────────────────────────┐             │
│          │    │  Gateway:                    │    ┌────────┴────────────────────────────────────────┐
│  MCP     ├───►│  agentgateway-mcp-combined   ├───►│  HTTPRoutes (path-based routing)                │
│  Client  │    │                              │    │                                                │
│          │    │  Host: mcp.servebeer.com     │    │  /mcp/atlassian   → combined-atlassian-backend  │──► Atlassian APIs
│  (JWT)   │    │  ALB (port 443)              │    │  /mcp/databricks  → combined-databricks-backend │──► Databricks APIs
│          │    │                              │    │  /mcp/gitlab      → combined-gitlab-backend     │──► GitLab APIs
│          │    │                              │    │  /mcp/multitool   → combined-multitool-backend  │──► Echo/Test tools
│          │    │                              │    │  /oauth-issuer    → issuer-proxy-backend        │──► Token exchange
└──────────┘    └──────────────────────────────┘    │                                                │
                                                    └────────────────────────────────────────────────┘

         Auth Layer (per-backend EAGPols):

         ┌─────────────────────────────────────────────────────────────────────────┐
         │  Downstream (JWT):  Client → AgentGateway (validated via Entra ID)     │
         │  Upstream (OAuth):  AgentGateway → Backend (per-service token exchange) │
         │                                                                         │
         │  combined-atlassian-exchange  → targets combined-atlassian-backend       │
         │  combined-databricks-exchange → targets combined-databricks-backend      │
         │  combined-gitlab-exchange     → targets combined-gitlab-backend          │
         │  combined-multitool-header-authz → targets combined-multitool-backend    │
         └─────────────────────────────────────────────────────────────────────────┘
```

### Request Flow (step by step)

1. **MCP Client** sends a request to `mcp.servebeer.com/<path>` with a JWT token (issued by Azure AD / Entra ID)
2. **JWT Validation** — EAGPol validates the token against Entra ID JWKS endpoint (via `entra-jwks` AgentgatewayBackend pointing to `login.microsoftonline.com`)
3. **Path Routing** — HTTPRoutes match on the path prefix to select the correct backend:
   - `/mcp/atlassian` → Atlassian (Jira/Confluence)
   - `/mcp/databricks` → Databricks workspace
   - `/mcp/gitlab` → GitLab
   - `/mcp/multitool` → Echo/test tool server
4. **Token Exchange** — Per-backend EAGPol performs OAuth token exchange:
   - The downstream JWT is exchanged for an upstream-specific OAuth token
   - Each backend has its own OAuth app credentials (stored in Secrets)
5. **Upstream** — Request is forwarded to the actual backend service with the exchanged token

### Two-Layer Auth Model

```
  Client                  AgentGateway                 Backend (e.g. Databricks)
    │                          │                              │
    │── JWT (Entra ID) ───────►│                              │
    │                          │── validate JWT (JWKS) ──────►│ Entra ID
    │                          │◄── OK ──────────────────────│
    │                          │                              │
    │                          │── OAuth token exchange ─────►│ Backend IdP
    │                          │   (client_id + client_secret │
    │                          │    + subject_token=JWT)       │
    │                          │◄── access_token ────────────│
    │                          │                              │
    │                          │── API call + access_token ──►│ Backend API
    │                          │◄── response ────────────────│
    │◄── response ────────────│                              │
```

### Key Resources (MCP)

| Resource | Kind | Purpose |
|----------|------|---------|
| `combined-atlassian-backend` | AgentgatewayBackend | Atlassian MCP server |
| `combined-databricks-backend` | AgentgatewayBackend | Databricks MCP server |
| `combined-gitlab-backend` | AgentgatewayBackend | GitLab MCP server |
| `combined-multitool-backend` | AgentgatewayBackend | Echo/test MCP server |
| `issuer-proxy-backend` | AgentgatewayBackend | OAuth issuer proxy for token exchange callbacks |
| `entra-jwks` | AgentgatewayBackend | Azure AD JWKS endpoint (shared, `login.microsoftonline.com`) |
| `combined-*-exchange` | EAGPol | Per-backend OAuth token exchange policies |

---

## Combined View

```
                              sortega-eks-demo-oas (EKS)
                              ──────────────────────────

  ┌──────────────────────────────────────────────────────────────────────────┐
  │                        agentgateway-system namespace                    │
  │                                                                        │
  │  ┌─────────────────────────────┐    ┌────────────────────────────────┐  │
  │  │ agentgateway-routing-demo   │    │ agentgateway-mcp-combined     │  │
  │  │ (LLM Gateway)               │    │ (MCP Gateway)                 │  │
  │  │                             │    │                                │  │
  │  │ Host: agentgateway.         │    │ Host: mcp.servebeer.com       │  │
  │  │   servebeer.com             │    │ ALB (external)                │  │
  │  │ NLB (external)              │    │                                │  │
  │  │                             │    │ Routes:                        │  │
  │  │ Flow:                       │    │  /mcp/atlassian  → Atlassian  │  │
  │  │  1. ExtAuth (body inspect)  │    │  /mcp/databricks → Databricks │  │
  │  │  2. Transform (headers)     │    │  /mcp/gitlab     → GitLab     │  │
  │  │  3. Route by x-model-       │    │  /mcp/multitool  → Echo       │  │
  │  │     provider header         │    │                                │  │
  │  │                             │    │ Auth: JWT (Entra ID)           │  │
  │  │ Backends:                   │    │     + OAuth token exchange     │  │
  │  │  openai → Azure App GW     │    │       (per backend)            │  │
  │  │  anthropic → Anthropic API  │    │                                │  │
  │  │  gemini → Gemini API        │    │                                │  │
  │  │                             │    │                                │  │
  │  │  ┌───────────────────┐      │    │                                │  │
  │  │  │ mock-extauth      │      │    │                                │  │
  │  │  │ (gRPC, port 9001) │      │    │                                │  │
  │  │  │ body → headers    │      │    │                                │  │
  │  │  └───────────────────┘      │    │                                │  │
  │  └─────────────────────────────┘    └────────────────────────────────┘  │
  │                                                                        │
  │  Shared: entra-jwks (AgentgatewayBackend → login.microsoftonline.com)  │
  └──────────────────────────────────────────────────────────────────────────┘
```

---

## Notes

- The `mock-extauth` container image is `sadielio/mcp-mock-extauth:v0.0.3` with `MODEL_OVERRIDE=gpt-4o-mini`
- `openai-via-azure-appgw` points to `iamready.servebeer.com` (Azure Application Gateway) with TLS `insecureSkipVerify: All`
- `gemini-llm-backend` is currently **not found** (status shows `BackendNotFound` on the HTTPRoute)
- The `canary-mcp-route` on `agentgateway-routing-demo` provides a 90/10 weighted split with cookie-based session persistence (separate from the LLM provider routing)
- MCP `.well-known` discovery paths are routed alongside each MCP backend path
