# Azure-Hosted Databricks MCP — Entra ID Certificate Auth

## Overview

Azure-hosted Databricks workspace exposed as an MCP server via OpenAPI-to-MCP
translation. Azure Entra ID is the sole IdP for both the downstream JWT (MCP client →
gateway) and the upstream token (gateway → Databricks). AGW authenticates to Entra with
a **certificate** (`private_key_jwt` / PS256) on both legs — no `client_secret`.

Validated on: `<CLUSTER_NAME>` with AGW `<AGW_VERSION>`
(image: `us-central1-docker.pkg.dev/developers-369321/enterprise-agentgateway-public-nonprod/...`)

| | |
|---|---|
| **Workspace** | `<DATABRICKS_WORKSPACE_HOST>` |
| **Entra tenant** | `<ENTRA_TENANT_ID>` |
| **Entra app** | `<ENTRA_APP_CLIENT_ID>` |
| **MCP path** | `/databricks/azure/mcp` |
| **Gateway** | `agw-databricks-entra` → `<MCP_GATEWAY_HOSTNAME>` |
| **GatewayClass** | `enterprise-agentgateway-oas` |

## Architecture

```
MCP Client (MCP Inspector / AI agent)
    │
    ▼ (1) Discover: GET /.well-known/oauth-protected-resource/databricks/azure/mcp
    │     → authorization_servers: [https://<host>/databricks/azure/mcp]
    │
    ▼ (2) Discover: GET /.well-known/oauth-authorization-server/databricks/azure/mcp
    │     → authorization_endpoint, token_endpoint, registration_endpoint
    │
    ▼ (3) Register + PKCE flow → /oauth-issuer/authorize → redirect to Entra login
    │     (gateway authenticates to Entra with certificate, not client_secret)
    │
    ▼ (4) User logs in to Entra (tenant 5e7d...) → auth code returned
    │
    ▼ (5) Gateway exchanges code for two tokens:
    │     • Downstream: Entra access token (aud=bf87e20f...) → returned to MCP client
    │     • Upstream: Databricks-scoped Entra token (scope=2ff814a6.../.default) → banked
    │
    ▼ (6) MCP client sends Entra access token to /databricks/azure/mcp
    │
AgentGateway (authn policy validates: issuer=login.microsoftonline.com/5e7d.../v2.0)
    │
    ▼ (7) entTokenExchange.solo retrieves banked Databricks token from STS
    │
Azure Databricks (validates Entra token natively — AD-integrated workspace)
```

## Certificate Authentication

Both OAuth legs use the same cert-manager-issued RSA certificate (`entra-client-cert`):

- **Upstream leg** (`05-eagpol-exchange.yaml`): `entElicitation.brokered.chainedAuth.oauth.certificateKeyPairRef`
- **Downstream leg** (`10-secret-oauth-issuer-config.yaml`): `downstream_server.certificate_key_pair_ref`

The certificate public key must be registered on the Entra app registration before use.

### Upload cert to Entra after issuing:
```bash
kubectl -n agentgateway-system get secret entra-client-cert \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > entra-client.crt

az ad app credential reset \
  --id <ENTRA_APP_CLIENT_ID> \
  --cert "@entra-client.crt" \
  --append
```

### Verify cert is loaded by the controller:
```bash
kubectl -n agentgateway-system logs deploy/enterprise-agentgateway \
  | grep "loaded Entra client assertion certificate"
# Expected: not_after, secret_rotation_requires_controller_restart: true
```

## Entra App Prerequisites

App `<ENTRA_APP_CLIENT_ID>` in tenant `5e7d8166-...`:

1. **Expose an API**: Application ID URI = `api://bf87e20f-...`, scope `agentgateway`
2. **API Permission**: Azure Databricks → `user_impersonation` (delegated) + admin consent
3. **Certificate**: upload `entra-client.crt` (from step above) under Certificates & secrets
4. **Manifest**: set `requestedAccessTokenVersion: 2` — required for v2.0 tokens
   - Without this, Entra issues v1.0 tokens (`iss: sts.windows.net/...`) which fail
     the authn policy's issuer check (`login.microsoftonline.com/.../v2.0`)

## File Index

| File | Description |
|------|-------------|
| `00-gatewayclass-oas.yaml` | GatewayClass `enterprise-agentgateway-oas` |
| `00-agw-params.yaml` | EnterpriseAgentgatewayParameters (logging, LoadBalancer) |
| `00-entra-jwks-backend.yaml` | AgentgatewayBackend for `login.microsoftonline.com` JWKS |
| `00-gateway.yaml` | Gateway `agw-databricks-entra` with HTTP+HTTPS listeners |
| `01-eagbe.yaml` | EAGBE pointing to Azure Databricks workspace via OpenAPI |
| `02-httproute.yaml` | Routes `/databricks/azure/mcp` + `.well-known` paths |
| `03-eagpol-tls-cors.yaml` | TLS for upstream HTTPS + CORS headers |
| `04-eagpol-authn.yaml` | Entra JWT validation (v2.0 issuer/audience) |
| `05-eagpol-exchange.yaml` | `entElicitation.brokered` + `entTokenExchange.solo` with cert |
| `06-certificate-entra-client.yaml` | cert-manager Issuer + Certificate (RSA 2048, 90d) |
| `07-cm-openapi-schema.yaml` | Databricks REST API OpenAPI 3.0 subset (SQL + Unity Catalog) |
| `08-agb-issuer-proxy.yaml` | AgentgatewayBackend → controller STS port 7777 |
| `09-httproute-oauth-issuer.yaml` | Routes `/oauth-issuer/*` to the controller STS |
| `10-secret-oauth-issuer-config.yaml` | `KGW_OAUTH_ISSUER_CONFIG` with cert downstream credential |

## AGW Helm Install

```bash
export CTX=<CLUSTER_NAME>
REGISTRY="us-central1-docker.pkg.dev/developers-369321/enterprise-agentgateway-public-nonprod"
AGW_VERSION="<AGW_VERSION>"  # or newer release with entElicitation API

# Gateway API CRDs
kubectl apply --context $CTX \
  -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml

# cert-manager (required for 06-certificate-entra-client.yaml)
kubectl apply --context $CTX \
  -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml
kubectl --context $CTX -n cert-manager rollout status deploy/cert-manager-webhook --timeout=120s

# AGW CRDs
helm upgrade -i --create-namespace -n agentgateway-system --kube-context $CTX \
  --version $AGW_VERSION \
  enterprise-agentgateway-crds \
  oci://${REGISTRY}/charts/enterprise-agentgateway-crds

# Certificate + OAuth issuer secret must exist before the controller starts
kubectl apply --context $CTX -f 06-certificate-entra-client.yaml
kubectl --context $CTX -n agentgateway-system wait \
  --for=condition=Ready certificate/entra-client-cert --timeout=60s

# Upload cert to Entra app registration (see above) before proceeding

kubectl apply --context $CTX -f 10-secret-oauth-issuer-config.yaml

# AGW controller + proxy
helm upgrade -i -n agentgateway-system --kube-context $CTX \
  --version $AGW_VERSION \
  enterprise-agentgateway \
  oci://${REGISTRY}/charts/enterprise-agentgateway \
  --set-string licensing.licenseKey="${AGENTGATEWAY_LICENSE}" \
  --set-json 'controller.extraEnv.KGW_OAUTH_ISSUER_CONFIG={"valueFrom":{"secretKeyRef":{"name":"agentgateway-oauth-issuer-config","key":"KGW_OAUTH_ISSUER_CONFIG"}}}' \
  --set tokenExchange.enabled=true \
  --set tokenExchange.issuer="enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777" \
  --set tokenExchange.tokenExpiration=24h \
  --set tokenExchange.subjectValidator.validatorType=remote \
  --set tokenExchange.subjectValidator.remoteConfig.url="https://login.microsoftonline.com/<ENTRA_TENANT_ID>/discovery/v2.0/keys" \
  --set tokenExchange.actorValidator.validatorType=k8s \
  --set tokenExchange.apiValidator.validatorType=k8s \
  --set 'gatewayClassParametersRefs.enterprise-agentgateway-oas.group=enterpriseagentgateway.solo.io' \
  --set 'gatewayClassParametersRefs.enterprise-agentgateway-oas.kind=EnterpriseAgentgatewayParameters' \
  --set 'gatewayClassParametersRefs.enterprise-agentgateway-oas.name=agentgateway-oas-params' \
  --set 'gatewayClassParametersRefs.enterprise-agentgateway-oas.namespace=agentgateway-system'

kubectl --context $CTX -n agentgateway-system \
  rollout status deploy/enterprise-agentgateway --timeout=120s

# TLS secret (wildcard cert for gateway HTTPS listener)
kubectl --context $CTX create secret tls gateway-tls -n agentgateway-system \
  --cert=/path/to/wildcard.crt --key=/path/to/wildcard.key

# Apply resources (order matters)
kubectl apply --context $CTX -f 00-gatewayclass-oas.yaml
kubectl apply --context $CTX -f 00-agw-params.yaml
kubectl apply --context $CTX -f 00-entra-jwks-backend.yaml
kubectl apply --context $CTX -f 00-gateway.yaml
kubectl apply --context $CTX -f 07-cm-openapi-schema.yaml
kubectl apply --context $CTX -f 01-eagbe.yaml
kubectl apply --context $CTX -f 02-httproute.yaml
kubectl apply --context $CTX -f 03-eagpol-tls-cors.yaml
kubectl apply --context $CTX -f 04-eagpol-authn.yaml
kubectl apply --context $CTX -f 05-eagpol-exchange.yaml
kubectl apply --context $CTX -f 08-agb-issuer-proxy.yaml
kubectl apply --context $CTX -f 09-httproute-oauth-issuer.yaml
```

## Validation

```bash
# All policies accepted and attached
kubectl --context $CTX -n agentgateway-system get eagbe,eagpol,httproute | grep azure-databricks

# Certificate loaded by controller (check not_after matches Entra registration)
kubectl --context $CTX -n agentgateway-system logs deploy/enterprise-agentgateway \
  | grep "loaded Entra client assertion certificate"

# OAuth discovery
curl -sk https://<MCP_GATEWAY_HOSTNAME>/.well-known/oauth-protected-resource/databricks/azure/mcp | jq .
curl -sk https://<MCP_GATEWAY_HOSTNAME>/.well-known/oauth-authorization-server/databricks/azure/mcp | jq .

# Test with MCP Inspector
# URL: https://<MCP_GATEWAY_HOSTNAME>/databricks/azure/mcp
# Transport: Streamable HTTP
```

## Troubleshooting

### `Error(InvalidIssuer)` on MCP requests → infinite redirect loop
Token `ver` is `1.0` — `requestedAccessTokenVersion: 2` is missing or not propagated
in the Entra app manifest. Check in Azure Portal → App registrations →
`agw-databricks` → Manifest. Wait a few minutes after saving for propagation.

### `route not found` on `/oauth-issuer/register`
`09-httproute-oauth-issuer.yaml` not applied or `issuer-proxy-backend` AGB is missing.
The OAuth issuer STS runs on the controller (port 7777), not the proxy — it must be
explicitly routed.

### `AADSTS700027` on token exchange
No registered `keyCredential` matches the assertion thumbprint. Re-upload the cert:
```bash
kubectl -n agentgateway-system get secret entra-client-cert \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > entra-client.crt
az ad app credential reset --id <ENTRA_APP_CLIENT_ID> --cert "@entra-client.crt" --append
```

### `sign OAuth client assertion: ...` in controller logs
Local signer failure. Check: expired cert, key/cert mismatch, non-RSA key.
PS256 requires RSA — a Certificate with `privateKey.algorithm: ECDSA` fails at load time.

### `service not found` from proxy
OpenAPI schema configmap has a parse error. Check controller logs for
`failed to parse OpenAPI schema`. Ensure `07-cm-openapi-schema.yaml` contains
valid JSON under the `schema` key with no trailing YAML comments.

### Controller will not start
Read the error verbatim:
```bash
kubectl -n agentgateway-system logs deploy/enterprise-agentgateway \
  | grep -i "client assertion\|invalid configuration\|error starting"
```
Common causes: `client_secret` and `certificate_key_pair_ref` both present (mutually
exclusive), `certificate_key_pair_ref.namespace` omitted in `KGW_OAUTH_ISSUER_CONFIG`,
or Secret missing `tls.key` / `tls.crt`.
