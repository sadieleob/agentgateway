# Elicitation Re-Trigger Bug Reproducer

Reproduces a bug where Enterprise AgentGateway does **not** re-trigger OAuth elicitation (SaaS consent) when the upstream token expires for the **agent token flow**.

The DCR flow (VS Code / MCP Inspector) handles this correctly. The agent token flow does not.

## The Bug

```text
Agent (custom)                  AgentGateway (STS)                  SaaS MCP Server
  |                                |                                  |
  |-- Entra JWT (auth-code) ------>|                                  |
  |                                |-- STS: no token -> elicitation   |
  |<-- elicitation URL ------------|                                  |
  |   (user completes consent      |                                  |
  |    via MCP Inspector DCR)      |                                  |
  |-- retry ---------------------->|-- STS: token found -> forward -->|
  |<-- tools/list OK --------------|<-- response --------------------|
  |                                |                                  |
  | ... SaaS token expires ...     |                                  |
  |                                |                                  |
  |-- Entra JWT (fresh) ---------->|-- STS: token EXPIRED             |
  |                                |-- BUG: returns expired token     |
  |<-- upstream error (masked) ----|   (no re-elicitation triggered)  |
  |   isError: false, HTTP 200     |   status stays 'completed'      |
```

**Expected**: STS detects the expired token, resets elicitation to `pending`, returns the consent URL.

**Actual**: STS finds the elicitation record with `status = 'completed'`, returns the expired token without checking `expires_at`. The upstream error is wrapped in `isError: false`.

## Confirmed Flow

The customer confirmed their agent flow:

1. **Seed the DB**: Connect via MCP Inspector (DCR flow) to the MCP backend — this completes the full OAuth consent chain and stores a valid SaaS token in the STS database, keyed by `(user_id/sub, resource/host)`.

2. **Agent calls gateway**: The custom agent mints an Entra ID token using `InteractiveBrowserCredential` (authorization_code + PKCE). The token has a user `sub` (not service principal). The agent sends MCP requests to the gateway with this token.

3. **STS matches user**: The STS extracts `sub` from the agent's JWT, finds the stored SaaS token under the same `(sub, resource)` key (seeded by the DCR flow), and forwards it to the upstream MCP server.

4. **Token expires -> bug**: After the SaaS token expires, the STS finds the `completed` elicitation, returns the expired token without checking `expires_at`. No re-elicitation is triggered. The upstream returns an error (e.g., `"error":"invalid_token"`) which is wrapped in a successful MCP envelope (`isError: false`, HTTP 200).

### Two Bugs

| # | Bug | Impact |
|---|-----|--------|
| 1 | STS does not check `expires_at` on stored tokens | Expired tokens are forwarded to upstream, causing silent failures |
| 2 | AgentGateway wraps upstream errors in `isError: false` | Client cannot detect the failure at the MCP protocol layer |

### Customer Evidence

```python
# tools/call response after SaaS token expired:
{'jsonrpc': '2.0', 'id': 3, 'result': {
    'content': [{'type': 'text', 'text': '{"error":"invalid_token",
        "error_description":"Token is expired. You can either do
        re-authorization or token refresh."}'}],
    'isError': False     # <-- BUG: should be True
}}
```

### Our Reproduction (Atlassian MCP)

```text
Phase 1 (fresh token):
  - Seeded DB via MCP Inspector DCR on the gateway
  - Agent (auth-code + PKCE) -> initialize OK -> tools/list OK -> tools/call OK
  - atlassianUserInfo returned successfully

Phase 2 (expired token):
  - Manually set tokens.expires_at to past in DB (simulates real expiry)
  - Agent (fresh Entra JWT) -> initialize OK -> tools/list OK -> tools/call OK
  - STS returned the expired token without checking expires_at
  - Elicitation status stayed 'completed' (never reset to 'pending')

DB evidence:
  - tokens.expires_at: in the PAST
  - elicitations.status: 'completed' (never reset)
  - elicitations.updated_at: unchanged
```

## Prerequisites

- [Kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker)
- [cloud-provider-kind](https://github.com/kubernetes-sigs/cloud-provider-kind) (for LoadBalancer IP assignment)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Helm](https://helm.sh/docs/intro/install/) v3
- Python 3.10+ with `httpx` (`pip install httpx`)
- An Azure AD (Entra ID) tenant with admin access
- A TLS certificate for the gateway hostname
- An Enterprise AgentGateway license key
- MCP Inspector (for seeding the DB via DCR flow)

## Entra ID Setup

You need **two** app registrations in your Azure AD tenant:

### 1. Gateway App Registration

This is the identity that the gateway uses for the DCR/issuer-proxy flow.

1. Go to Azure Portal > App registrations > New registration
2. Name: any name (e.g., `agw-gateway`)
3. Supported account types: Single tenant
4. Register
5. Note the **Application (client) ID** -> this is `ENTRA_CLIENT_ID`
6. Go to **Certificates & secrets** > New client secret -> note the secret value -> this is `ENTRA_CLIENT_SECRET`
7. Go to **Expose an API** > Set Application ID URI to `api://<client-id>`
8. Add a scope: `agentgateway` (admin consent required)

### 2. Agent App Registration

This is the identity that the custom agent uses (separate from the gateway).

1. Go to Azure Portal > App registrations > New registration
2. Name: any name (e.g., `agw-custom-agent`)
3. Supported account types: Single tenant
4. Register
5. Note the **Application (client) ID** -> this is `ENTRA_AGENT_CLIENT_ID`
6. Go to **Certificates & secrets** > New client secret -> note the secret value -> this is `ENTRA_AGENT_CLIENT_SECRET`
7. Go to **API permissions** > Add a permission > My APIs > select the gateway app > select `agentgateway` scope > Add
8. Click **Grant admin consent** for the tenant
9. Go to **Authentication** > Add platform > **Web** > Redirect URI: `http://localhost:8912/callback`
   - Do NOT check "Access tokens" or "ID tokens" (those enable implicit grant)

The agent app needs permission to request tokens with the gateway's audience (`api://<gateway-client-id>/.default`).

## Configuration

Copy `env.sh` to `env.local.sh` and fill in all required variables:

```bash
# Required - Enterprise AgentGateway
export AGW_VERSION="2026.5.0-beta.4"         # or your version
export AGENTGATEWAY_LICENSE_KEY="your-license-key"

# Required - Gateway TLS
export GATEWAY_HOSTNAME="mcp.example.com"    # Your gateway hostname
export TLS_CERT="/path/to/cert.pem"
export TLS_KEY="/path/to/key.pem"

# Required - Entra ID (Gateway App)
export ENTRA_TENANT_ID="your-tenant-id"
export ENTRA_CLIENT_ID="gateway-app-client-id"
export ENTRA_CLIENT_SECRET="gateway-app-secret"

# Required - Entra ID (Agent App)
export ENTRA_AGENT_CLIENT_ID="agent-app-client-id"
export ENTRA_AGENT_CLIENT_SECRET="agent-app-secret"

# Required - MCP Backend (e.g. Atlassian)
export BACKEND_HOST="mcp.atlassian.com"
export BACKEND_PORT="443"
export BACKEND_PATH="/v1/mcp"
export BACKEND_ROUTE_PREFIX="/mcp/atlassian"
export BACKEND_APP_ID="atlassian"
export BACKEND_BASE_URL="https://mcp.atlassian.com"
export BACKEND_MCP_RESOURCE="/mcp/atlassian"
export BACKEND_SCOPES="read:jira-work"
```

**Note:** `env.local.sh` contains secrets and should NOT be committed to version control.

## Deploy

```bash
source env.local.sh
./deploy.sh
```

This creates a Kind cluster with:

- PostgreSQL (token exchange storage)
- Enterprise AgentGateway with token exchange enabled
- A gateway with HTTPS listener
- MCP backend routing with JWT authentication
- OAuth issuer-proxy for the DCR flow

## Reproduce the Bug

### Step 1: Seed the DB via MCP Inspector (DCR Flow)

Connect MCP Inspector to the gateway's MCP endpoint:

```text
URL: https://<GATEWAY_HOSTNAME><BACKEND_ROUTE_PREFIX>
```

Complete the Entra ID login and SaaS OAuth consent when prompted. This stores a valid SaaS token in the STS database.

Verify the DB was seeded:

```bash
kubectl -n postgres exec deploy/postgres -- psql -U myuser -d mydb -c \
  "SELECT e.status, t.expires_at FROM elicitations e JOIN tokens t ON t.elicitation_id = e.id ORDER BY e.created_at DESC LIMIT 1;"
```

Expected: `status = 'completed'`, `expires_at` in the future.

### Step 2: Run the Agent (Phase 1 — Fresh Token)

```bash
source env.local.sh
python agent.py --auth-code --skip-wait
```

The agent will:

1. Open a browser for Entra ID login (authorization_code + PKCE)
2. Send MCP `initialize` + `tools/list` + `tools/call` to the gateway
3. STS finds the valid token (seeded by MCP Inspector) -> forwards to upstream -> succeeds

### Step 3: Simulate Token Expiry

Manually expire the token in the DB:

```bash
kubectl -n postgres exec deploy/postgres -- psql -U myuser -d mydb -c \
  "UPDATE tokens SET expires_at = NOW() - INTERVAL '1 minute' WHERE id = (SELECT MAX(id) FROM tokens);"
```

### Step 4: Run the Agent Again (Phase 2 — Expired Token)

```bash
source env.local.sh
python agent.py --auth-code --skip-wait
```

**Expected (if bug fixed)**: STS detects the expired token, resets elicitation to `pending`, returns consent URL.

**Actual (bug present)**: STS returns the expired token. If the upstream rejects it, the error is wrapped in `isError: false`. The elicitation status remains `completed`.

### Step 5: Verify DB State

```bash
kubectl -n postgres exec deploy/postgres -- psql -U myuser -d mydb -c \
  "SELECT e.status, t.expires_at, t.expires_at < NOW() as is_expired FROM elicitations e JOIN tokens t ON t.elicitation_id = e.id ORDER BY e.created_at DESC LIMIT 1;"
```

Confirms: `status` is still `completed`, `is_expired` is `true`.

### Step 6: Compare with DCR Flow

Reconnect MCP Inspector to the same endpoint. The DCR flow re-triggers elicitation correctly, acquiring a fresh SaaS token.

### Alternative: validate_atlassian_entra.py

A simpler validation script that runs both phases in one invocation:

```bash
source env.local.sh
python validate_atlassian_entra.py
```

## CLI Options

### agent.py

```text
python agent.py [OPTIONS]

--auth-code           Use authorization_code + PKCE (interactive browser login)
--wait N              Seconds to wait for token expiry (default: 90)
--skip-wait           Skip the expiry wait period
--interactive         Pause between phases for manual inspection
--token-only          Just acquire and print the Entra token
--gateway URL         Override the gateway base URL
--use-gateway-client  Use the gateway's client_id instead of the agent's
```

### validate_atlassian_entra.py

```text
python validate_atlassian_entra.py [OPTIONS]

--wait N              Seconds to wait for token expiry (default: 90)
--skip-wait           Skip the expiry wait period
--use-gateway-client  Use the gateway's client_id instead of the agent's
```

## Cleanup

```bash
source env.local.sh
./cleanup.sh
```
