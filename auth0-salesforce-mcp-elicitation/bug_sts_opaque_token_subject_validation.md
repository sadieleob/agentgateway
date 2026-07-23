# RFE: Auth0 Returns Opaque Tokens Because Issuer Proxy Does Not Pass `audience` to `/authorize`

**Cluster:** <CLUSTER_NAME>
**Version:** enterprise-agentgateway 2026.7.0
**Date:** 2026-07-22
**Type:** RFE (Request for Enhancement)
**Status:** WORKAROUND APPLIED

## Summary

The issuer proxy's `buildAuthorizationURL()` does not include an `audience` parameter when redirecting users to the downstream IdP's `/authorize` endpoint. IdPs like Auth0 require `audience` to return JWT access tokens; without it, they return opaque tokens. The STS `subjectValidator` then rejects the opaque token because `validateTokenAgainstJWKS()` requires a parseable JWT.

## Workaround

Embedded `?audience=https://<GATEWAY_HOSTNAME>` in the downstream `authorize_url` within `KGW_OAUTH_ISSUER_CONFIG` env var. This forces Auth0 to return JWTs instead of opaque tokens.

This can also be set persistently via Helm by including `?audience=...` in the `authorize_url` within the `KGW_OAUTH_ISSUER_CONFIG` JSON value.

## What Should Change

Expose an `audience` option in Helm values or the EAGPE CRD that gets appended to the downstream `/authorize` URL, so IdPs like Auth0 that require `audience` to return JWTs can be configured declaratively.

## Background

### What Happens Without the Workaround

When using the issuer proxy + elicitation pattern with **Auth0** as the downstream IdP and **Salesforce** as the upstream MCP server, the full OAuth flow completes successfully (Auth0 login + Salesforce consent), but every subsequent MCP request fails with HTTP 500.

The issuer proxy passes through Auth0's access token to the MCP client. Auth0 returns an **opaque** access token because the issuer proxy does not include an `audience` parameter in the `/authorize` request to Auth0. Without `audience`, Auth0 returns opaque tokens; with `audience`, Auth0 returns JWTs.

When the proxy later sends that opaque token back to the STS as a `subject_token` for exchange at `/elicitations/oauth2/token`, the STS rejects it because the `subjectValidator` (type: `remote`, pointing at Auth0 JWKS) calls `validateTokenAgainstJWKS()` which requires a parseable JWT.

With `mode: Strict` on the backend auth policy, there is also an infinite auth loop because the proxy tries to validate the opaque token as a JWT and fails. Workaround: `mode: Permissive` stops the loop but exposes the `invalid subject token` error.

### Code References

`buildAuthorizationURL()` in `ent-controller/internal/issuer/oauth_helpers.go` constructs the downstream `/authorize` URL with: `client_id`, `redirect_uri`, `response_type`, `state`, `scope`, `code_challenge`. **It does not pass `audience`.**

Auth0 behavior:
- **With `audience`** → returns a JWT access token
- **Without `audience`** → returns an opaque access token

Entra ID always returns JWTs regardless of whether `audience` is in the authorize request, which is why the another customer config works with `mode: Strict`.

The `OAuthServerConfig` struct in `ent-controller/internal/issuer/config.go` has no `Audience` field, so there is no way to configure this today.

### Why It Works with Entra ID but Not Auth0

Both IdPs go through the same issuer proxy code path (`buildAuthorizationURL` → downstream `/authorize` → code exchange → pass through downstream token). Neither gets an `audience` param in `/authorize`. The difference is how each IdP handles this:

- **Entra ID** always returns JWTs for access tokens (regardless of `audience` in `/authorize`). The JWT passes `subjectValidator` JWKS validation.
- **Auth0** returns opaque tokens when `audience` is absent from `/authorize`. The opaque token fails `jwt.ParseSigned()` in `validateTokenAgainstJWKS()`.

## Logs (pre-workaround)

### agw-mcp proxy (pod: agw-mcp-979b689b7-stngx)

```
2026-07-22T23:39:04.811292Z  debug  http::jwt  Received token with invalid header.  connection.id=138 request.id=9773 error=Error(Base64(InvalidByte(107, 46)))
2026-07-22T23:39:04.811297Z  debug  http::jwt  token verification failed (the token header is malformed: Error(Base64(InvalidByte(107, 46)))), continue due to permissive mode  connection.id=138 request.id=9773
2026-07-22T23:39:04.811462Z  debug  proxy::token_exchange  exchanging token  connection.id=138 request.id=9773 backend=agentgateway-system/ent-salesforce-mcp-backend
2026-07-22T23:39:04.811467Z  debug  proxy::token_exchange  exchanging token for upstream service  connection.id=138 request.id=9773 upstream_service_name=agentgateway-system/ent-salesforce-mcp-backend token_exchange_config.sts_uri=http://enterprise-agentgateway.agentgateway-system.svc.cluster.local:7777/elicitations/oauth2/token
2026-07-22T23:39:04.813569Z  error  proxy::token_exchange  Token exchange failed: OAuthErrorResponse { error: "invalid_target", error_description: Some("invalid subject token"), error_uri: None, elicitation_info: None }  connection.id=138 request.id=9773
2026-07-22T23:39:04.813746Z  info  request connection.id=138 request.id=9773 gateway=agentgateway-system/agw-mcp listener=https route=agentgateway-system/salesforce-mcp src.addr=10.50.101.215:41662 http.method=POST http.host=<GATEWAY_HOSTNAME> http.path=/mcp/salesforce http.version=HTTP/1.1 http.status=500 protocol=mcp mcp.method.name=initialize mcp.session.id=826eca94-7bf4-4825-a6c9-adc6dd662571 error="mcp: failed to send message: http upstream error: http request failed: invalid request" reason=MCP duration=2ms
```

### enterprise-agentgateway STS (pod: enterprise-agentgateway-59d569d94f-nmsv7)

The STS successfully completes the dual OAuth flow (Auth0 downstream + Salesforce upstream) and issues an opaque Bearer token:

```
{"time":"2026-07-22T23:39:02.845482701Z","level":"info","msg":"starting dual OAuth flow","component":"tokenexchange","has_redirect_uri":true,"client_id":"<AUTH0_CLIENT_ID>","has_pkce":true}
{"time":"2026-07-22T23:39:02.845503535Z","level":"info","msg":"resource requires upstream OAuth due to explicit MCP mapping","component":"tokenexchange","resource":"/mcp/salesforce","has_auth_resource":true,"has_explicit_upstream_mcp_config":true,"has_fallback_oauth_config":false}
{"time":"2026-07-22T23:39:02.855268421Z","level":"info","msg":"dual OAuth flow initiated","component":"tokenexchange","state":"21nD_53P","has_auth_url":true}
{"time":"2026-07-22T23:39:02.855338559Z","level":"info","msg":"request","component":"request","method":"GET","path":"/oauth-issuer/authorize","status_code":302,"latency":9911658,"client_ip":"10.50.3.216"}
{"time":"2026-07-22T23:39:03.641691813Z","level":"info","msg":"downstream callback processed, redirecting to upstream","component":"tokenexchange","old_state":"21nD_53P","new_state":"V3VLdTWS","user_id":"google-oauth2|<USER_ID>","has_upstream_url":true}
{"time":"2026-07-22T23:39:03.641779565Z","level":"info","msg":"request","component":"request","method":"GET","path":"/oauth-issuer/callback/downstream","status_code":307,"latency":331757241,"client_ip":"10.50.3.216"}
{"time":"2026-07-22T23:39:04.551941782Z","level":"info","msg":"code exchange succeeded","component":"tokenexchange/secret","elicitation_id":1,"user_id":"","resource":"agentgateway-system/ent-salesforce-mcp-backend","has_access_token":true,"has_refresh_token":true}
{"time":"2026-07-22T23:39:04.559099659Z","level":"info","msg":"upstream callback processed with client redirect","component":"tokenexchange","state":"V3VLdTWS","user_id":"google-oauth2|<USER_ID>","client_id":"<AUTH0_CLIENT_ID>","has_auth_code":true}
{"time":"2026-07-22T23:39:04.747622412Z","level":"info","msg":"token exchange request","component":"tokenexchange","code":"VkIGyH2R","client_id":"<AUTH0_CLIENT_ID>","has_code_verifier":true,"has_redirect_uri":true}
{"time":"2026-07-22T23:39:04.752914325Z","level":"info","msg":"state deleted after successful code exchange","component":"tokenexchange","state":"V3VLdTWS","user_id":"google-oauth2|<USER_ID>"}
{"time":"2026-07-22T23:39:04.75294237Z","level":"info","msg":"authorization code exchange successful","component":"tokenexchange","code":"VkIGyH2R","client_id":"<AUTH0_CLIENT_ID>","state":"V3VLdTWS","user_id":"google-oauth2|<USER_ID>","has_access_token":true,"has_refresh_token":false}
{"time":"2026-07-22T23:39:04.752953276Z","level":"info","msg":"token exchange successful","component":"tokenexchange","code":"VkIGyH2R","client_id":"<AUTH0_CLIENT_ID>","has_access_token":true,"has_refresh_token":false,"token_type":"Bearer"}
{"time":"2026-07-22T23:39:04.753005664Z","level":"info","msg":"request","component":"request","method":"POST","path":"/oauth-issuer/token","status_code":200,"latency":5417502,"client_ip":"10.50.3.216"}
```

Then the proxy calls `/elicitations/oauth2/token` with the opaque token as subject_token and gets **400**:

```
{"time":"2026-07-22T23:39:04.813044902Z","level":"info","msg":"request","component":"request","method":"POST","path":"/elicitations/oauth2/token","status_code":400,"latency":289473,"client_ip":"10.50.3.216"}
```

## Prior Issue Search

No exact match found in agentgateway-enterprise.

| Issue | Relation |
|---|---|
| #802 (closed) | "Token exchange requires Opaque input" -- another customer needs opaque-to-JWT exchange at the gateway level. Related concept (opaque tokens in exchange flow) but different scope (client-sent opaque vs STS-issued opaque) |
