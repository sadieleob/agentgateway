# Passthrough

No passthrough setup has been verified end to end with an authenticated tool call yet, so none
are published here. Setups are added once a real MCP client completes the SaaS login and a tool
call succeeds through the gateway.

Findings so far (gateway behavior, verified 2026-10-21 on AGW 2026.10.0 with curl):

- The gateway forwards the client's `Authorization` header to the upstream MCP server unchanged
  when the backend has **no** `policies.auth`.
- With `policies.auth.passthrough: {}` **and** a validated JWT on the route, the gateway writes the
  validated JWT into `Authorization` (it overwrites the client's upstream token).
- Corporate identity at the gateway and the upstream token can be combined with **two tokens**:
  validate the IdP JWT from a custom header (`traffic.jwtAuthentication.location.header`) and leave
  the upstream token in `Authorization`.
- SaaS servers without dynamic client registration (Slack, GitHub) require every MCP client to be
  configured with that SaaS app's client ID (and usually secret), and each client's callback URL
  registered in the SaaS app.
