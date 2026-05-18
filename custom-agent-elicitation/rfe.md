---
title: "Re-elicitation only works via DCR/issuer-proxy as token exchange path skips expires_at check"
labels: kind/bug
---

### Customer Requirements

- When a custom agent uses the **token exchange path** (agent JWT → STS lookup) and the upstream SaaS token (tested with Atlassian) has expired, the gateway must re-trigger elicitation instead of returning the expired token. Currently, re-elicitation only works via the **DCR/issuer-proxy path** (VS Code / MCP Inspector)
- The STS token lookup (`POST /elicitations/oauth2/token`) must check `tokens.expires_at` before returning a stored token — if expired, reset `elicitations.status` from `completed` to `pending`
- When the upstream MCP server returns an error (e.g., `invalid_token`), the MCP response must set `isError: true` — currently errors are wrapped in `isError: false`, masking failures from the client
- Token refresh via `refresh_token` (if available) should be attempted before falling back to full re-elicitation

### References

- May 15 internal call: customer demonstrated the bug live — agent works after initial consent, fails silently after SaaS token expires, workaround is reconnecting via MCP Inspector (DCR flow) to refresh the token
- May 18 customer-provided reproducer: `validate_gitlab_entra.py` script showing `isError: false` with `{"error":"invalid_token","error_description":"Token is expired"}` in the content body
- May 18 reproduction on internal cluster (AGW v2026.5.0-beta.4): confirmed STS does not check `expires_at` — manually expired token in DB, STS still returned it, elicitation status stayed `completed`

### Related Issues

- Configurable TTL for consent/elicitation records (separate: consent records persist indefinitely, customer also wants configurable re-consent policy)

### Customer Priority and Relevant Dates

- **Critical** — blocks agent GA release (target was May 20, 2026)
- Every agent-to-SaaS-MCP connection breaks once the initial SaaS token expires
- Workaround (manual MCP Inspector reconnection) is not viable for production agents running autonomously

### Field Engineer Assessment

This is a bug, not a feature request. The STS has a code path that looks up stored tokens by `(user_id, resource)` but never checks `expires_at`. When the upstream SaaS token expires, the STS returns it anyway. The elicitation status never transitions from `completed` back to `pending`.

The DCR flow (VS Code / MCP Inspector) handles re-elicitation correctly, confirming the token exchange infrastructure works. The gap is specifically in the on-demand (agent token) path.

There is a secondary issue: when the expired token is forwarded to the upstream and rejected, AgentGateway wraps the error in a successful MCP envelope (`isError: false`, HTTP 200). The client cannot detect the failure at the MCP protocol layer.

<details>
<summary>Additional Context</summary>

### Root Cause

1. Proxy calls `POST /elicitations/oauth2/token` with the downstream JWT as `subject_token`
2. STS extracts `sub` (userId) from the JWT
3. STS queries: `SELECT * FROM elicitations WHERE user_id = $1 AND resource = $2`
4. If found with `status = 'completed'` → STS queries tokens by `elicitation_id`
5. **Bug:** STS returns the token WITHOUT checking `tokens.expires_at`
6. Proxy injects the (expired) token into the upstream `Authorization` header

### Expected Fix

The STS should:
- Check `tokens.expires_at` against `NOW()` before returning a stored token
- If expired: attempt refresh using `tokens.refresh_token` (if available)
- If refresh fails or no refresh token: reset `elicitations.status` to `pending` and return elicitation info

### Reproduction

A self-contained reproducer (Kind cluster + scripts) is available in the `reproducer/` directory:

1. Deploy Kind cluster with AGW + PostgreSQL + Atlassian MCP backend
2. Seed DB via MCP Inspector (DCR flow) — stores valid SaaS token
3. Run agent with auth-code + PKCE — STS returns stored token, tools/call succeeds
4. Manually expire the token in DB (`UPDATE tokens SET expires_at = NOW() - INTERVAL '1 minute'`)
5. Run agent again — STS returns expired token, no re-elicitation triggered
6. DB confirms: `elicitations.status` still `completed`, `tokens.expires_at` in the past

</details>
