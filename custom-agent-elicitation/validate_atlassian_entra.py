#!/usr/bin/env python3
"""Validate Entra bearer token against an Atlassian MCP server via AgentGateway.

Mirrors the customer's validate script but targets the Atlassian MCP backend.
Uses authorization_code + PKCE (InteractiveBrowserCredential-equivalent) to produce
a user-sub token, matching the agent token flow.

Flow:
    Phase 1 (fresh token):
        1. Mint Entra token via auth-code + PKCE.
        2. POST initialize.
        3. POST notifications/initialized.
        4. POST tools/list → print catalog.
        5. POST tools/call on first available tool → verify access.
    Wait for tokenExpiration (default 90s).
    Phase 2 (expired SaaS token):
        6. Mint fresh Entra token.
        7. Repeat steps 2-5.
        8. Observe: STS returns expired SaaS token → upstream error in content
           but isError: false → BUG.

Pre-requisite: DB must be seeded with a valid Atlassian SaaS token (via MCP
Inspector DCR flow or agent.py --auth-code elicitation).

Usage:
    source env.local.sh
    python validate_atlassian_entra.py
    python validate_atlassian_entra.py --wait 120
    python validate_atlassian_entra.py --skip-wait
    python validate_atlassian_entra.py --use-gateway-client
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "")
ENTRA_GATEWAY_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "")
ENTRA_GATEWAY_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "")
ENTRA_AGENT_CLIENT_ID = os.environ.get("ENTRA_AGENT_CLIENT_ID", "")
ENTRA_AGENT_CLIENT_SECRET = os.environ.get("ENTRA_AGENT_CLIENT_SECRET", "")

ENTRA_GATEWAY_AUDIENCE = f"api://{ENTRA_GATEWAY_CLIENT_ID}/.default"
ENTRA_TOKEN_URL = (
    f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token"
)

GATEWAY_HOSTNAME = os.environ.get("GATEWAY_HOSTNAME", "")
BACKEND_ROUTE_PREFIX = os.environ.get("BACKEND_ROUTE_PREFIX", "")
CA_CERT = os.environ.get("CA_CERT", "")

MCP_URL = f"https://{GATEWAY_HOSTNAME}{BACKEND_ROUTE_PREFIX}"


# ---------------------------------------------------------------------------
# JWT helper
# ---------------------------------------------------------------------------
def decode_jwt_claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload))


# ---------------------------------------------------------------------------
# PKCE auth-code flow (stdlib only, no azure.identity)
# ---------------------------------------------------------------------------
class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code = None
    auth_state = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        _OAuthCallbackHandler.auth_code = params.get("code", [None])[0]
        _OAuthCallbackHandler.auth_state = params.get("state", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authorization complete. You can close this tab.</h2></body></html>"
        )

    def log_message(self, format, *args):
        pass


def get_entra_token(use_gateway_client: bool = False) -> str:
    if use_gateway_client:
        client_id = ENTRA_GATEWAY_CLIENT_ID
        client_secret = ENTRA_GATEWAY_CLIENT_SECRET
        label = "gateway"
    else:
        client_id = ENTRA_AGENT_CLIENT_ID
        client_secret = ENTRA_AGENT_CLIENT_SECRET
        label = "agent"

    if not client_id:
        print(f"\n  ERROR: No client_id configured for {label}.")
        sys.exit(1)

    print(f"\n=== Acquiring Entra ID Token (authorization_code + PKCE) - {label} ===")
    print(f"  Tenant:    {ENTRA_TENANT_ID}")
    print(f"  Client ID: {client_id}")
    print(f"  Scope:     {ENTRA_GATEWAY_AUDIENCE} openid")

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)
    redirect_uri = "http://localhost:8912/callback"

    authorize_url = (
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/authorize?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": f"{ENTRA_GATEWAY_AUDIENCE} openid",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "state": state,
            }
        )
    )

    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.auth_state = None
    server = HTTPServer(("127.0.0.1", 8912), _OAuthCallbackHandler)

    print(f"  Opening browser for login...")
    print(f"  (If browser doesn't open, visit this URL manually:)")
    print(f"  {authorize_url}")
    webbrowser.open(authorize_url)

    print(f"  Waiting for callback on {redirect_uri} ...")
    while _OAuthCallbackHandler.auth_code is None:
        server.handle_request()
    server.server_close()

    code = _OAuthCallbackHandler.auth_code
    if _OAuthCallbackHandler.auth_state != state:
        print(f"  ERROR: State mismatch. Possible CSRF.")
        sys.exit(1)

    print(f"  Authorization code received. Exchanging for token...")
    token_data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "scope": f"{ENTRA_GATEWAY_AUDIENCE} openid",
    }
    if client_secret:
        token_data["client_secret"] = client_secret

    resp = httpx.post(ENTRA_TOKEN_URL, data=token_data, timeout=15)
    if resp.status_code != 200:
        print(f"  ERROR: Token exchange failed: {resp.status_code}")
        print(f"  {resp.text}")
        sys.exit(1)

    token = resp.json()["access_token"]
    claims = decode_jwt_claims(token)
    print(f"  Token acquired:")
    print(f"    aud: {claims.get('aud')}")
    print(f"    iss: {claims.get('iss')}")
    print(f"    sub: {claims.get('sub')}")
    print(f"    azp/appid: {claims.get('azp', claims.get('appid'))}")
    print(f"    name: {claims.get('name', 'n/a')}")
    exp = claims.get("exp", 0)
    ttl = exp - int(time.time())
    print(f"    exp: {exp} (TTL: {ttl}s)")
    return token


# ---------------------------------------------------------------------------
# SSE / JSON-RPC parsing
# ---------------------------------------------------------------------------
def parse_all_sse_events(text: str) -> list[dict]:
    results = []
    text = text.strip()
    if not text:
        return results
    if text.startswith("{"):
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            return results
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                results.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                pass
    return results


def parse_response(text: str) -> dict | None:
    evts = parse_all_sse_events(text)
    return evts[0] if evts else None


# ---------------------------------------------------------------------------
# MCP validation phase
# ---------------------------------------------------------------------------
def run_phase(phase_label: str, token: str, verify) -> bool:
    """Run initialize → tools/list → tools/call. Returns True if tools/call succeeded."""
    print(f"\n{'='*60}")
    print(f"  {phase_label}")
    print(f"{'='*60}")

    headers = {
        "Authorization": f"Bearer {token}",
        "x-auth-originator": token,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0, verify=verify) as client:
        # --- initialize ---
        print(f"\n--- Step 1: initialize ---")
        r = client.post(
            MCP_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "validate_atlassian_entra",
                        "version": "0.1.0",
                    },
                },
            },
            headers=headers,
        )
        print(f"    status={r.status_code}")

        if r.status_code != 200:
            snippet = r.text[:500].replace("\n", " ")
            print(f"    body  : {snippet}")
            print(f"\n==> initialize FAILED (HTTP {r.status_code})")
            return False

        init_resp = parse_response(r.text) or {}

        if "error" in init_resp:
            err = init_resp["error"]
            print(f"    JSON-RPC error: code={err.get('code')} msg={err.get('message')}")
            data = err.get("data", {})
            if isinstance(data, dict) and data.get("url"):
                print(f"    Elicitation URL: {data['url']}")
            print(f"\n==> initialize returned elicitation or error")
            return False

        server_caps = init_resp.get("result", {}).get("capabilities", {})
        print(f"    Server capabilities: {list(server_caps.keys())}")

        session_id = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
        print(f"    Mcp-Session-Id: {session_id}")
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        # --- notifications/initialized ---
        client.post(
            MCP_URL,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers=headers,
        )

        # --- tools/list ---
        print(f"\n--- Step 2: tools/list ---")
        r = client.post(
            MCP_URL,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers=headers,
        )
        print(f"    status={r.status_code}")
        resp = parse_response(r.text) or {}
        tools = resp.get("result", {}).get("tools", [])
        tool_names = [t.get("name") for t in tools]
        print(f"    Tool count: {len(tools)}")
        if tools:
            print(f"    Tools: {tool_names[:10]}{'...' if len(tool_names) > 10 else ''}")
        else:
            print(f"    body: {r.text[:300].replace(chr(10), ' ')}")
            print(f"\n==> No tools returned.")
            return False

        # --- tools/call (first available tool) ---
        call_tool = tool_names[0]
        print(f"\n--- Step 3: tools/call {call_tool} ---")
        r = client.post(
            MCP_URL,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": call_tool, "arguments": {}},
            },
            headers=headers,
        )
        print(f"    status={r.status_code}")
        resp = parse_response(r.text) or {}
        print(f"    Full response keys: {list(resp.keys())}")
        print(f"    Full response: {json.dumps(resp, indent=2)[:800]}")

        if "error" in resp:
            print(f"    JSON-RPC error: {resp['error']}")
            print(f"\n==> tools/call FAILED (JSON-RPC error)")
            return False

        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [])
        text_blob = next(
            (c.get("text", "") for c in content if c.get("type") == "text"), ""
        )

        print(f"\n    isError: {is_error}")
        print(f"    content text: {text_blob[:500]}")

        # Check if the content body contains an upstream token error
        token_error = False
        try:
            body = json.loads(text_blob) if text_blob else {}
            if isinstance(body, dict) and body.get("error") in (
                "invalid_token",
                "expired_token",
            ):
                token_error = True
                print(f"\n    !!! UPSTREAM TOKEN ERROR DETECTED !!!")
                print(f"    error: {body.get('error')}")
                print(f"    error_description: {body.get('error_description')}")
                if not is_error:
                    print(f"    !!! BUG: isError is false — error is masked !!!")
        except (json.JSONDecodeError, TypeError):
            pass

        if token_error:
            return False

        print(f"\n==> tools/call {call_tool} OK")
        return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Validate Entra token against Atlassian MCP via AgentGateway"
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=90,
        help="Seconds to wait for SaaS token expiry (default: 90)",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip the token expiry wait period",
    )
    parser.add_argument(
        "--use-gateway-client",
        action="store_true",
        help="Use the gateway's client_id instead of the agent's",
    )
    args = parser.parse_args()

    if not GATEWAY_HOSTNAME:
        print("ERROR: GATEWAY_HOSTNAME not set. Source env.local.sh first.")
        sys.exit(1)
    if not BACKEND_ROUTE_PREFIX:
        print("ERROR: BACKEND_ROUTE_PREFIX not set. Source env.local.sh first.")
        sys.exit(1)

    verify = CA_CERT if CA_CERT else True
    print(f"MCP endpoint : {MCP_URL}")
    print(f"TLS verify   : {verify}")

    # --- Phase 1: Fresh SaaS token ---
    print("\n" + "#" * 60)
    print("# PHASE 1: Fresh SaaS token (should succeed)")
    print("#" * 60)

    token1 = get_entra_token(args.use_gateway_client)
    ok = run_phase("Phase 1 — fresh SaaS token", token1, verify)

    if not ok:
        print("\n!!! Phase 1 failed — DB may not be seeded.")
        print("    Seed first: connect MCP Inspector to")
        print(f"    {MCP_URL}")
        print("    and complete the Atlassian OAuth consent.")
        sys.exit(1)

    if args.skip_wait:
        print("\n==> --skip-wait: skipping token expiry wait.")
        print("==> Phase 1 passed. Run again after tokenExpiration to test Phase 2.")
        sys.exit(0)

    # --- Wait for tokenExpiration ---
    print(f"\n{'='*60}")
    print(f"  Waiting {args.wait}s for SaaS token to expire (tokenExpiration: 1m)")
    print(f"{'='*60}")
    for remaining in range(args.wait, 0, -1):
        sys.stdout.write(f"\r  {remaining}s remaining... ")
        sys.stdout.flush()
        time.sleep(1)
    print("\r  Token should now be expired.             ")

    # --- Phase 2: Expired SaaS token ---
    print("\n" + "#" * 60)
    print("# PHASE 2: Expired SaaS token (should re-trigger elicitation)")
    print("#" * 60)

    token2 = get_entra_token(args.use_gateway_client)
    ok2 = run_phase("Phase 2 — expired SaaS token", token2, verify)

    if ok2:
        print("\n==> Phase 2 PASSED — no bug observed (SaaS token was refreshed).")
    else:
        print("\n" + "!" * 60)
        print("! BUG CONFIRMED: STS returned expired SaaS token.")
        print("! No re-elicitation was triggered.")
        print("!" * 60)
        print("\nExpected: STS detects expired token, creates new pending")
        print("          elicitation, returns consent URL to agent.")
        print("Actual:   STS found elicitation with status='completed',")
        print("          returned expired token without checking expires_at.")

    # --- DB state ---
    print("\n--- DB state (check manually) ---")
    print("  kubectl --context kind-elicitation-repro -n postgres \\")
    print('    exec deploy/postgres -- psql -U myuser -d mydb -c \\')
    print('    "SELECT id, user_id, resource, status, created_at FROM elicitations ORDER BY created_at DESC;"')


if __name__ == "__main__":
    main()
