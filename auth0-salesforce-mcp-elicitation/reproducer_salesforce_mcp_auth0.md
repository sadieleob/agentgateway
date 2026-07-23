# Reproducer: Salesforce MCP with Auth0 (Issuer Proxy + Elicitation)


## Prerequisites

- EKS cluster with Istio ambient mesh
- Auth0 tenant with:
  - Native (browser-based web app) application
  - Custom API with audience matching gateway hostname
- Salesforce org with:
  - External Client App (OAuth enabled)
  - Active MCP server (e.g. `sobject-all`)
- PostgreSQL for STS session storage
- TLS certificate for gateway hostname
- `$AGENTGATEWAY_LICENSE_KEY` env var set

## Environment

| Component | Value |
|---|---|
| Gateway hostname | `<GATEWAY_HOSTNAME>` |
| Auth0 domain | `<AUTH0_DOMAIN>` |
| Auth0 client ID | `<AUTH0_CLIENT_ID>` |
| Auth0 audience | `https://<GATEWAY_HOSTNAME>` |
| Salesforce org | `<SALESFORCE_ORG>` |
| Salesforce client ID | `<SALESFORCE_CLIENT_ID>` |
| Salesforce MCP server | `sobject-all` |

## Step 0: PostgreSQL (STS session storage)

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
  namespace: agentgateway-system
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: agentgateway-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16-alpine
        env:
        - name: POSTGRES_DB
          value: agentgateway
        - name: POSTGRES_USER
          value: agentgateway
        - name: POSTGRES_PASSWORD
          value: agentgateway
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        ports:
        - containerPort: 5432
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            memory: 512Mi
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: postgres-data
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: agentgateway-system
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
```

Wait for postgres to be ready before installing AGW:

```bash
kubectl create namespace agentgateway-system 2>/dev/null; kubectl apply -f postgres.yaml && kubectl -n agentgateway-system rollout status deployment/postgres --timeout=60s
```

## Step 1: Install CRDs and Helm Chart

```bash
export VERSION=2026.7.0

# Gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml

# AGW Enterprise CRDs
helm upgrade -i --create-namespace -n agentgateway-system \
  enterprise-agentgateway-crds \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway-crds \
  --version v${VERSION}

# AGW Enterprise with issuer proxy + token exchange
helm upgrade -i -n agentgateway-system \
  enterprise-agentgateway \
  oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts/enterprise-agentgateway \
  --version v${VERSION} \
  --set licensing.licenseKey=$AGENTGATEWAY_LICENSE_KEY \
  --set tokenExchange.enabled=true \
  --set tokenExchange.issuer=enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777 \
  --set tokenExchange.tokenExpiration=24h \
  --set tokenExchange.subjectValidator.validatorType=remote \
  --set tokenExchange.subjectValidator.remoteConfig.url=https://<AUTH0_DOMAIN>/.well-known/jwks.json \
  --set tokenExchange.database.type=postgres \
  --set tokenExchange.database.postgres.url=postgres://agentgateway:agentgateway@postgres.agentgateway-system.svc.cluster.local:5432/agentgateway?sslmode=disable \
  --set tokenExchange.storage.envelope.provider=k8s-secret \
  --set tokenExchange.storage.envelope.dekCache.maxEntries=1024 \
  --set tokenExchange.storage.envelope.dekCache.ttl=5m \
  --set tokenExchange.actorValidator.validatorType=k8s \
  --set tokenExchange.apiValidator.validatorType=k8s \
  --set-json "controller.extraEnv.KGW_OAUTH_ISSUER_CONFIG=$(cat <<'ENVEOF'
{"downstream_server":{"name":"auth0","client_id":"<AUTH0_CLIENT_ID>","client_secret":"<AUTH0_CLIENT_SECRET>","authorize_url":"https://<AUTH0_DOMAIN>/authorize?audience=https://<GATEWAY_HOSTNAME>","token_url":"https://<AUTH0_DOMAIN>/oauth/token","scopes":["openid","profile","email"],"user_id_claim":"sub"},"gateway_config":{"base_url":"https://<GATEWAY_HOSTNAME>/oauth-issuer"},"par_config":{"enabled":false}}
ENVEOF
)"
```

**IMPORTANT:** The `?audience=https://<GATEWAY_HOSTNAME>` in the `authorize_url` is the workaround for the opaque token issue. Without it, Auth0 returns opaque tokens and the STS rejects them with `invalid subject token`.

To reproduce the bug, remove `?audience=https://<GATEWAY_HOSTNAME>` from the `authorize_url`.

## Step 2: TLS Secret

```bash
kubectl -n agentgateway-system create secret tls gateway-tls --cert=tls.crt --key=tls.key
```

## Step 3: Gateway

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: agw-mcp
  namespace: agentgateway-system
spec:
  gatewayClassName: enterprise-agentgateway-mcp
  listeners:
  - allowedRoutes:
      namespaces:
        from: All
    name: http
    port: 8080
    protocol: HTTP
  - allowedRoutes:
      namespaces:
        from: All
    hostname: <GATEWAY_HOSTNAME>
    name: https
    port: 443
    protocol: HTTPS
    tls:
      certificateRefs:
      - name: gateway-tls
      mode: Terminate
```

## Step 4: Gateway Policy (CORS + retry + timeout)

```yaml
apiVersion: enterpriseagentgateway.solo.io/v1alpha1
kind: EnterpriseAgentgatewayPolicy
metadata:
  name: agw-mcp-policy
  namespace: agentgateway-system
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: agw-mcp
  traffic:
    cors:
      allowCredentials: true
      allowHeaders:
      - '*'
      allowMethods:
      - GET
      - POST
      - PUT
      - DELETE
      - PATCH
      - OPTIONS
      allowOrigins:
      - '*'
      exposeHeaders:
      - Mcp-Session-Id
      maxAge: 86400
    retry:
      attempts: 3
    timeouts:
      request: 120s
```

## Step 5: Auth0 JWKS Backend

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

## Step 6: Salesforce Token Exchange Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: salesforce-mcp-token-exchange
  namespace: agentgateway-system
type: Opaque
stringData:
  app_id: salesforce
  client_id: "<SALESFORCE_CLIENT_ID>"
  authorize_url: "https://<SALESFORCE_ORG>.develop.my.salesforce.com/services/oauth2/authorize"
  access_token_url: "https://<SALESFORCE_ORG>.develop.my.salesforce.com/services/oauth2/token"
  scopes: "mcp_api refresh_token openid"
  mcp_resource: "/mcp/salesforce"
```

## Step 7: Salesforce EAGBE

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

## Step 8: HTTPRoute

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

## Step 9: Backend Auth — JWT Validation (targets EAGBE)

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

## Step 10: Backend Auth — Token Exchange (targets EAGBE)

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

## Step 11: Backend TLS (targets HTTPRoute)

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

## Test

Connect MCP Inspector to `https://<GATEWAY_HOSTNAME>/mcp/salesforce` using StreamableHTTP transport.

Expected flow:
1. MCP Inspector discovers auth via `/.well-known/oauth-protected-resource/mcp/salesforce`
2. Redirects to Auth0 login (Google social login)
3. After Auth0, redirects to Salesforce consent
4. After Salesforce consent, MCP session established
5. `initialize` returns 200, `notifications/initialized` returns 202
6. `logging/setLevel` returns 500 (known Salesforce limitation — empty response body)
7. `GET /mcp/salesforce` returns 405 (Salesforce does not support SSE)

## Reproducing the Opaque Token Bug

To reproduce the original issue, remove `?audience=https://<GATEWAY_HOSTNAME>` from the `authorize_url` in the Helm values `KGW_OAUTH_ISSUER_CONFIG` and run `helm upgrade` again.

Without `audience`, Auth0 returns opaque tokens. The STS rejects them:

```
proxy::token_exchange  Token exchange failed: OAuthErrorResponse { error: "invalid_target",
error_description: Some("invalid subject token") }
```

With `mode: Strict` on `salesforce-mcp-authn`, this also causes an infinite auth loop (proxy rejects opaque token as invalid JWT → 401 → re-auth → same result).

## Auth0 Setup

| Field | Value |
|---|---|
| Tenant | `<AUTH0_DOMAIN>` |
| App type | Native (browser-based web app) |
| Client ID | `<AUTH0_CLIENT_ID>` |
| API audience | `https://<GATEWAY_HOSTNAME>` |
| Callback URL | `https://<GATEWAY_HOSTNAME>/oauth-issuer/callback/downstream` |

## Salesforce Setup

| Field | Value |
|---|---|
| Org | <SALESFORCE_ORG> |
| MCP server | sobject-all (Active) |
| Client ID | `<SALESFORCE_CLIENT_ID>` |
| Callback URL | `https://<GATEWAY_HOSTNAME>/oauth-issuer/callback/upstream` |
| Scopes | `mcp_api refresh_token openid` |
