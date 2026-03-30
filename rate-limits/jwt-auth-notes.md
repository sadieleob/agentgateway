# JWT Authentication - AgentGateway Routing Demo

## Overview

JWT auth configured on `agentgateway-routing-demo` gateway using Microsoft Entra ID (tenant `REDACTED-TENANT-ID`) as the identity provider.

## Architecture

```
Client → agentgateway-routing-demo (Gateway)
           │
           ├─ Frontend phase: access-log-headers (access log attributes)
           ├─ PreRouting phase: extauth-model-override (body-based ext auth for model routing)
           └─ Traffic phase: access-log-headers (JWT authentication - Strict mode)
                                │
                                └─ JWKS fetched from entra-idp backend
                                   (login.microsoftonline.com:443)
```

## Why modify `access-log-headers` instead of creating a new policy?

Only one EnterpriseAgentgatewayPolicy per phase is allowed per gateway attachment point. The `extauth-model-override` policy already occupies the PreRouting traffic phase. Adding `traffic.jwtAuthentication` to `access-log-headers` places JWT auth in the default traffic phase, avoiding a phase conflict.

A single policy CAN span both `frontend` and `traffic` sections — they are independent phase groups.

## Key Configuration Details

| Field | Value |
|---|---|
| Policy name | `access-log-headers` |
| Target | Gateway `agentgateway-routing-demo` |
| Mode | `Strict` (all requests require valid JWT) |
| Issuer | `https://sts.windows.net/REDACTED-TENANT-ID/` (v1.0 — confirmed from token) |
| JWKS path | `REDACTED-TENANT-ID/discovery/v2.0/keys` |
| JWKS backend | `entra-idp` (AgentgatewayBackend, login.microsoftonline.com:443, TLS) |
| Audience | Not restricted (any `aud` accepted) |
| Cache duration | 5m |

## Issuer Gotcha (Microsoft Entra ID)

Microsoft Entra ID tokens can have different `iss` claim formats:

- **accessTokenAcceptedVersion=2**: `iss: https://login.microsoftonline.com/{tenant}/v2.0`
- **accessTokenAcceptedVersion=1 (default)**: `iss: https://sts.windows.net/{tenant}/`

The OIDC discovery endpoint (`v2.0/.well-known/openid-configuration`) advertises the v2.0 issuer,
but the actual tokens use v1.0 format when `accessTokenAcceptedVersion=1` (the default).
Always decode the token and check the `iss` claim to determine the correct issuer.

## Setup Steps

### Prerequisites

- AgentGateway Enterprise deployed with gateway `agentgateway-routing-demo`
- Existing `entra-idp` AgentgatewayBackend pointing to `login.microsoftonline.com:443` with TLS
- Microsoft Entra ID app registration with client credentials

### Step 1: Check the OIDC discovery endpoint

Retrieve the OIDC configuration for the tenant to identify the issuer and JWKS URI:

```bash
curl -s "https://login.microsoftonline.com/REDACTED-TENANT-ID/v2.0/.well-known/openid-configuration" | jq
```

Key fields:
- `issuer`: `https://login.microsoftonline.com/REDACTED-TENANT-ID/v2.0`
- `jwks_uri`: `https://login.microsoftonline.com/REDACTED-TENANT-ID/discovery/v2.0/keys`

**Important:** The discovery endpoint shows the v2.0 issuer, but the actual tokens may use the v1.0 format (`https://sts.windows.net/{tenant}/`). See Step 3.

### Step 2: Identify existing policies on the gateway

List policies attached to the gateway:

```bash
kubectl get eagpol -n agentgateway-system
```

For `agentgateway-routing-demo`, two policies existed:
- `access-log-headers` — `frontend.accessLog` (frontend phase)
- `extauth-model-override` — `traffic.extAuth` + `phase: PreRouting` (PreRouting phase)

Since only one policy per phase is allowed, JWT auth (`traffic.jwtAuthentication`) was added to
`access-log-headers` to place it in the default traffic phase (not PreRouting).

### Step 3: Get a token and verify the issuer claim

Get an access token from Entra ID using client_credentials flow:

```bash
ACCESS_TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/REDACTED-TENANT-ID/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=7facd971-ddc4-41b5-96b3-73e052aed5bd" \
  -d "client_secret=<YOUR_SECRET>" \
  -d "scope=api://36a0a774-43fd-4c85-b473-a2bbe46dfab2/.default" \
  | jq -r .access_token)
```

Decode the token to verify the issuer:

```bash
echo $ACCESS_TOKEN | jq -R 'split(".") | .[1] | @base64d | fromjson'
```

Example output (key fields):
```json
{
  "aud": "api://36a0a774-43fd-4c85-b473-a2bbe46dfab2",
  "iss": "https://sts.windows.net/REDACTED-TENANT-ID/",
  "ver": "1.0",
  "appid": "7facd971-ddc4-41b5-96b3-73e052aed5bd"
}
```

The `iss` claim is `https://sts.windows.net/{tenant}/` (v1.0), NOT the v2.0 format from the
discovery endpoint. The policy issuer must match this exactly.

### Step 4: Apply the JWT auth policy

The `access-log-headers` eagpol was modified to add `traffic.jwtAuthentication` with the
v1.0 issuer confirmed from the token:

```bash
kubectl apply -f 08-jwt-auth-policy.yaml
```

Or inline:

```bash
kubectl apply -f - <<'EOF'
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: access-log-headers
  namespace: agentgateway-system
spec:
  frontend:
    accessLog:
      attributes:
        add:
        - expression: request.headers
          name: request.all_headers
        - expression: response.headers
          name: response.all_headers
        - expression: extauthz
          name: extauthz.metadata
  traffic:
    jwtAuthentication:
      mode: Strict
      providers:
      - issuer: "https://sts.windows.net/REDACTED-TENANT-ID/"
        jwks:
          remote:
            jwksPath: "REDACTED-TENANT-ID/discovery/v2.0/keys"
            cacheDuration: "5m"
            backendRef:
              group: agentgateway.dev
              kind: AgentgatewayBackend
              name: entra-idp
              namespace: agentgateway-system
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agentgateway-routing-demo
EOF
```

### Step 5: Verify the policy is accepted

```bash
kubectl get eagpol access-log-headers -n agentgateway-system -o json | jq '.status'
```

Expected conditions:
```
Accepted: Valid - Policy accepted
Attached: Attached - Attached to all targets
```

### Step 6: Test without a token (expect 401)

```bash
curl -s "https://agentgateway.servebeer.com/test/200"
```

Expected response:
```
authentication failure: no bearer token found
```

HTTP status: `401 Unauthorized`

### Step 7: Test with a valid JWT (expect 200)

```bash
curl -sv "https://agentgateway.servebeer.com/test/200" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

### Step 8: Test LLM route with token

```bash
curl -s "https://agentgateway.servebeer.com/llm/v1/chat/completions" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}'
```

## Adding Audience Restriction

To restrict to specific audiences, add the `audiences` field to the provider:

```yaml
providers:
- issuer: "https://sts.windows.net/REDACTED-TENANT-ID/"
  audiences:
  - "api://36a0a774-43fd-4c85-b473-a2bbe46dfab2"
  jwks:
    remote:
      jwksPath: "REDACTED-TENANT-ID/discovery/v2.0/keys"
      cacheDuration: "5m"
      backendRef:
        group: agentgateway.dev
        kind: AgentgatewayBackend
        name: entra-idp
        namespace: agentgateway-system
```

## Related Files

- `08-jwt-auth-policy.yaml` - The eagpol manifest with JWT auth
- Existing `entra-idp` backend: `kubectl get agentgatewaybackend entra-idp -n agentgateway-system -o yaml`
- OIDC discovery: `https://login.microsoftonline.com/REDACTED-TENANT-ID/v2.0/.well-known/openid-configuration`

## Reference

- [AgentGateway JWT auth setup docs](https://docs.solo.io/agentgateway/2.1.x/security/jwt/setup/)
- [JWT auth concepts](https://docs.solo.io/agentgateway/2.1.x/security/jwt/about/)
- [MCP auth vs JWT auth comparison](https://docs.solo.io/agentgateway/2.1.x/mcp/mcp-access/)
