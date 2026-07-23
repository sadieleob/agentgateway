# Auth0 + Salesforce MCP via AGW Enterprise — Setup Notes

**Cluster:** <CLUSTER_NAME>
**Version:** enterprise-agentgateway 2026.7.0
**Gateway:** agw-mcp (<GATEWAY_HOSTNAME>)
**Salesforce Org:** <SALESFORCE_ORG> (Developer Edition)
**Date:** 2026-07-22
**Status:** WORKING (with workaround)

---

## Auth Architecture

OAuth Issuer Proxy + Elicitation pattern with two-layer auth:

```
MCP Client
  │
  ▼
agw-mcp proxy (<GATEWAY_HOSTNAME>)
  │
  ├─ JWT validation (Auth0, mode: Permissive)
  │
  ├─ Token exchange ──► enterprise-agentgateway STS (:7777)
  │                        │
  │                        ├─ Downstream: Auth0 (/authorize + /token)
  │                        └─ Upstream: Salesforce OAuth (/authorize + /token)
  │
  └─ Forward to Salesforce MCP ──► api.salesforce.com:443
                                    /platform/mcp/v1/platform/sobject-all
```

---

## Auth0 Tenant

| Field | Value |
|---|---|
| Domain | `<AUTH0_DOMAIN>` |
| Issuer | `https://<AUTH0_DOMAIN>/` |
| JWKS URL | `https://<AUTH0_DOMAIN>/.well-known/jwks.json` |
| Token Endpoint | `https://<AUTH0_DOMAIN>/oauth/token` |
| Authorization Endpoint | `https://<AUTH0_DOMAIN>/authorize` |

## Auth0 Application (Native)

| Field | Value |
|---|---|
| Type | Native (browser-based web app) |
| Name | `agentgateway demo (Test Application)` |
| Client ID | `<AUTH0_CLIENT_ID>` |
| Client Secret | `<AUTH0_CLIENT_SECRET>` |
| Callback URL | `https://<GATEWAY_HOSTNAME>/oauth-issuer/callback/downstream` |

## Auth0 API

| Field | Value |
|---|---|
| Name | `AgentGateway` |
| Identifier (Audience) | `https://<GATEWAY_HOSTNAME>` |
| Signing Algorithm | RS256 |

## Salesforce Configuration

| Field | Value |
|---|---|
| Org | <SALESFORCE_ORG> |
| MCP server | sobject-all (Active, 11 tools, 2 prompts) |
| Upstream endpoint | `api.salesforce.com/platform/mcp/v1/platform/sobject-all` |
| Callback URL | `https://<GATEWAY_HOSTNAME>/oauth-issuer/callback/upstream` |
| Scopes | `mcp_api refresh_token openid` |
| client_id | `<SALESFORCE_CLIENT_ID>` |

---

## Cluster State (<CLUSTER_NAME>, as of 2026-07-23)

### Pods

| Pod | Role |
|---|---|
| `agw-mcp-979b689b7-stngx` | Proxy (Rust) |
| `enterprise-agentgateway-5b769757c7-6jjdg` | Enterprise controller + STS |

### Env Vars (enterprise-agentgateway deployment)

#### KGW_OAUTH_ISSUER_CONFIG (issuer proxy — builds /authorize URL)

```json
{
  "downstream_server": {
    "name": "auth0",
    "client_id": "<AUTH0_CLIENT_ID>",
    "client_secret": "<AUTH0_CLIENT_SECRET>",
    "authorize_url": "https://<AUTH0_DOMAIN>/authorize?audience=https://<GATEWAY_HOSTNAME>",
    "token_url": "https://<AUTH0_DOMAIN>/oauth/token",
    "scopes": ["openid", "profile", "email"],
    "user_id_claim": "sub"
  },
  "gateway_config": {
    "base_url": "https://<GATEWAY_HOSTNAME>/oauth-issuer"
  },
  "par_config": {
    "enabled": false
  }
}
```

**NOTE:** The `?audience=https://<GATEWAY_HOSTNAME>` in `authorize_url` is a **manual workaround** applied via `kubectl set env`. Without it, Auth0 returns opaque tokens instead of JWTs, and the STS `subjectValidator` rejects them. This will be overwritten on next `helm upgrade`. See [bug report](bug_sts_opaque_token_subject_validation.md) for details.

#### KGW_AGENTGATEWAY_TOKEN_EXCHANGE_CONFIG (STS — validates subject tokens)

```json
{
  "enabled": true,
  "issuer": "enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777",
  "subjectValidator": {
    "validatorType": "remote",
    "remoteConfig": {
      "url": "https://<AUTH0_DOMAIN>/.well-known/jwks.json"
    }
  },
  "database": {
    "type": "postgres",
    "postgres": {
      "url": "postgres://agentgateway:agentgateway@postgres.agentgateway-system.svc.cluster.local:5432/agentgateway?sslmode=disable"
    }
  },
  "tokenExpiration": "24h",
  "storage": {
    "envelope": {
      "provider": "k8s-secret",
      "dekCache": { "maxEntries": 1024, "ttl": "5m" }
    }
  },
  "actorValidator": { "validatorType": "k8s" },
  "apiValidator": { "validatorType": "k8s" }
}
```

### Custom Resources

#### EnterpriseAgentgatewayBackend

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayBackend
metadata:
  name: ent-salesforce-mcp-backend
  namespace: agentgateway-system
spec:
  entMcp:
    targets:
    - name: ent-salesforce-mcp
      static:
        host: api.salesforce.com
        path: /platform/mcp/v1/platform/sobject-all
        port: 443
        protocol: StreamableHTTP
```

#### EnterpriseAgentgatewayPolicy — JWT Auth (targets EAGBE)

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: salesforce-mcp-authn
  namespace: agentgateway-system
spec:
  backend:
    mcp:
      authentication:
        audiences:
        - https://<GATEWAY_HOSTNAME>
        issuer: https://<AUTH0_DOMAIN>/
        jwks:
          backendRef:
            group: agentgateway.dev
            kind: AgentgatewayBackend
            name: auth0-jwks
          cacheDuration: 5m
          jwksPath: /.well-known/jwks.json
        mode: Permissive
        resourceMetadata:
          agentgateway.dev/issuer-proxy: http://enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777/oauth-issuer
          authorizationServers:
          - https://<GATEWAY_HOSTNAME>/mcp/salesforce
          resource: https://<GATEWAY_HOSTNAME>/mcp/salesforce
          scopesSupported:
          - openid
          - profile
  targetRefs:
  - group: enterpriseagentgateway.solo.io
    kind: EnterpriseAgentgatewayBackend
    name: ent-salesforce-mcp-backend
```

#### EnterpriseAgentgatewayPolicy — Token Exchange (targets EAGBE)

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: salesforce-mcp-exchange
  namespace: agentgateway-system
spec:
  backend:
    tokenExchange:
      elicitation:
        secretName: salesforce-mcp-token-exchange
  targetRefs:
  - group: enterpriseagentgateway.solo.io
    kind: EnterpriseAgentgatewayBackend
    name: ent-salesforce-mcp-backend
```

#### EnterpriseAgentgatewayPolicy — TLS (targets HTTPRoute)

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: salesforce-mcp-tls
  namespace: agentgateway-system
spec:
  backend:
    tls: {}
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: salesforce-mcp
```

#### HTTPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: salesforce-mcp
  namespace: agentgateway-system
spec:
  parentRefs:
  - name: agw-mcp
  rules:
  - backendRefs:
    - group: enterpriseagentgateway.solo.io
      kind: EnterpriseAgentgatewayBackend
      name: ent-salesforce-mcp-backend
    matches:
    - path:
        type: PathPrefix
        value: /mcp/salesforce
    - path:
        type: PathPrefix
        value: /.well-known/oauth-protected-resource/mcp/salesforce
    - path:
        type: PathPrefix
        value: /.well-known/oauth-authorization-server/mcp/salesforce
```

#### Secret — Salesforce Token Exchange

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: salesforce-mcp-token-exchange
  namespace: agentgateway-system
stringData:
  app_id: salesforce
  client_id: "<SALESFORCE_CLIENT_ID>"
  authorize_url: "https://<SALESFORCE_ORG>.develop.my.salesforce.com/services/oauth2/authorize"
  access_token_url: "https://<SALESFORCE_ORG>.develop.my.salesforce.com/services/oauth2/token"
  scopes: "mcp_api refresh_token openid"
  mcp_resource: "/mcp/salesforce"
```

#### AgentgatewayBackend — Auth0 JWKS

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: auth0-jwks
  namespace: agentgateway-system
spec:
  policies:
    tls: {}
  static:
    host: <AUTH0_DOMAIN>
    port: 443
```

---

## Issues Encountered and Resolved

### Issue 1: Infinite auth loop — mode: Strict + opaque STS token (RESOLVED)

**Symptom:** MCP Inspector enters infinite loop. Both Auth0 and Salesforce OAuth complete successfully, but every `POST /mcp/salesforce` returns 401, triggering re-auth.

**Root cause:** `salesforce-mcp-authn` had `mode: Strict`. The STS issues opaque bearer tokens, not JWTs. The proxy's JWT parser fails with `Error(Base64(InvalidByte(107, 46)))` and rejects the request.

**Fix:** Changed `mode: Strict` to `mode: Permissive` on `salesforce-mcp-authn`.

### Issue 2: STS rejects Auth0 opaque token as subject_token (RESOLVED — workaround)

**Symptom:** After fixing Issue 1, MCP requests fail with HTTP 500:
```
proxy::token_exchange  Token exchange failed: OAuthErrorResponse { error: "invalid_target",
error_description: Some("invalid subject token") }
```

**Root cause:** Auth0 returns opaque tokens when `audience` is absent from `/authorize`. The issuer proxy's `buildAuthorizationURL()` does not include `audience`. The STS `subjectValidator` (type: `remote`) calls `validateTokenAgainstJWKS()` which requires a parseable JWT.

Entra ID always returns JWTs regardless, which is why the another customer config works without this workaround.

**Workaround:** Added `?audience=https://<GATEWAY_HOSTNAME>` to the `authorize_url` in `KGW_OAUTH_ISSUER_CONFIG` via `kubectl set env`. This forces Auth0 to return JWTs.

**Proper fix needed:** `OAuthServerConfig` struct needs an `Audience` field, `buildAuthorizationURL()` needs to set `params.Set("audience", ...)`, and the EAGPE CRD should expose this. See [bug report](bug_sts_opaque_token_subject_validation.md).

### Issue 3: `logging/setLevel` returns 500 — EOF (Salesforce limitation)

**Symptom:** `logging/setLevel` returns 500:
```
mcp: failed to send message: http upstream error: http request failed: EOF while parsing a value at line 1 column 0
```

**Root cause:** Salesforce's `sobject-all` MCP server returns an empty response body for `logging/setLevel`. The AGW proxy tries to parse it as JSON and fails. Same behavior seen on the another customer Salesforce setup.

**Impact:** Low. `logging/setLevel` is optional per the MCP spec. Core operations (`initialize`, `tools/list`, `tools/call`) work.

### Issue 4: GET /mcp/salesforce returns 405 (Salesforce limitation)

**Symptom:** `GET /mcp/salesforce` returns `405 Method Not Allowed` from upstream.

**Root cause:** Salesforce's MCP server does not support SSE streaming via GET. Only POST is supported for StreamableHTTP.

**Impact:** None for normal MCP usage.

---

## Verify Token

The Auth0 app is Native (browser-based web app), so tokens are obtained via the authorization code flow through the issuer proxy, not via client_credentials. To verify a token from an active session:

```bash
# Decode an Auth0 JWT from the browser session (copy from MCP Inspector Authorization header)
echo "<TOKEN>" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{iss, aud, sub, exp}'
```

Expected output (from post-fix logs):
```json
{
  "iss": "https://<AUTH0_DOMAIN>/",
  "aud": ["https://<GATEWAY_HOSTNAME>", "https://<AUTH0_DOMAIN>/userinfo"],
  "sub": "google-oauth2|<USER_ID>"
}
```

---

## Post-Fix Log Evidence (2026-07-23T00:08:51Z)

### Proxy (agw-mcp)

Auth0 JWT validated successfully:
```
http::jwt  authenticated request with JWT claims
  {"iss":"https://<AUTH0_DOMAIN>/",
   "aud":["https://<GATEWAY_HOSTNAME>","https://<AUTH0_DOMAIN>/userinfo"],
   "sub":"google-oauth2|<USER_ID>", ...}
```

STS token exchange succeeds:
```
upstream request  target=10.50.2.230:7777  http.path=/elicitations/oauth2/token  http.status=200  duration="3ms"
```

Salesforce upstream responds:
```
upstream request  target=api.salesforce.com:443  http.path=/platform/mcp/v1/platform/sobject-all  http.status=202  duration="469ms"
request  http.path=/mcp/salesforce  http.status=202  mcp.method.name=notifications/initialized
```

### STS (enterprise-agentgateway)

```
{"level":"info","msg":"served elicitation token","component":"sts/handler",
 "user_id":"google-oauth2|<USER_ID>",
 "resource":"agentgateway-system/ent-salesforce-mcp-backend","elicitation_id":1}
{"level":"info","msg":"request","method":"POST","path":"/elicitations/oauth2/token","status_code":200}
```
