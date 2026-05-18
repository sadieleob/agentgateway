#!/usr/bin/env bash
# Configuration for the elicitation re-trigger bug reproducer.
# Fill in ALL variables below before running deploy.sh.

# --- Kind Cluster ---
export CLUSTER_NAME="${CLUSTER_NAME:-elicitation-repro}"
export KIND_IMAGE="${KIND_IMAGE:-kindest/node:v1.31.4@sha256:2cb39f7295fe7eafee0842b1052a599a4fb0f8bcf3f83d96c7f4864c357c6c30}"

# --- Enterprise AgentGateway ---
export AGW_VERSION="${AGW_VERSION:-}"                  # e.g. 2.3.3
export AGW_NAMESPACE="${AGW_NAMESPACE:-agentgateway-system}"
export AGW_HELM_REGISTRY="${AGW_HELM_REGISTRY:-oci://us-docker.pkg.dev/solo-public/enterprise-agentgateway/charts}"
export AGENTGATEWAY_LICENSE_KEY="${AGENTGATEWAY_LICENSE_KEY:-}"  # Required

# --- Gateway TLS ---
export GATEWAY_HOSTNAME="${GATEWAY_HOSTNAME:-}"        # e.g. mcp.example.com
export TLS_CERT="${TLS_CERT:-}"                        # Path to TLS certificate file
export TLS_KEY="${TLS_KEY:-}"                          # Path to TLS private key file
export TLS_SECRET_NAME="${TLS_SECRET_NAME:-gateway-tls}"

# --- Entra ID / Azure AD (Gateway App Registration) ---
export ENTRA_TENANT_ID="${ENTRA_TENANT_ID:-}"          # Azure AD tenant ID
export ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID:-}"          # Gateway app registration client ID
export ENTRA_CLIENT_SECRET="${ENTRA_CLIENT_SECRET:-}"  # Gateway app registration client secret
export ENTRA_AUDIENCE="api://${ENTRA_CLIENT_ID}"
export ENTRA_SCOPE="${ENTRA_AUDIENCE}/agentgateway"
export ENTRA_ISSUER="https://sts.windows.net/${ENTRA_TENANT_ID}/"
export ENTRA_JWKS_PATH="${ENTRA_TENANT_ID}/discovery/v2.0/keys"
export ENTRA_AUTHORIZE_URL="https://login.microsoftonline.com/${ENTRA_TENANT_ID}/oauth2/v2.0/authorize"
export ENTRA_TOKEN_URL="https://login.microsoftonline.com/${ENTRA_TENANT_ID}/oauth2/v2.0/token"

# --- Entra ID (Agent App Registration — separate identity for custom agents) ---
export ENTRA_AGENT_CLIENT_ID="${ENTRA_AGENT_CLIENT_ID:-}"          # Agent app client ID
export ENTRA_AGENT_CLIENT_SECRET="${ENTRA_AGENT_CLIENT_SECRET:-}"  # Agent app client secret

# --- MCP Backend (the upstream SaaS MCP server to proxy to) ---
export BACKEND_NAME="${BACKEND_NAME:-mcp-backend}"
export BACKEND_HOST="${BACKEND_HOST:-}"                # e.g. mcp.atlassian.com
export BACKEND_PORT="${BACKEND_PORT:-443}"
export BACKEND_PATH="${BACKEND_PATH:-}"                # e.g. /v1/mcp
export BACKEND_ROUTE_PREFIX="${BACKEND_ROUTE_PREFIX:-}" # e.g. /mcp/atlassian
export BACKEND_APP_ID="${BACKEND_APP_ID:-}"             # e.g. atlassian
export BACKEND_BASE_URL="${BACKEND_BASE_URL:-}"         # e.g. https://mcp.atlassian.com
export BACKEND_MCP_RESOURCE="${BACKEND_MCP_RESOURCE:-}" # e.g. /mcp/atlassian (same as route prefix)
export BACKEND_SCOPES="${BACKEND_SCOPES:-}"             # e.g. read:jira-work

# --- PostgreSQL (token exchange storage) ---
export PG_NAMESPACE="${PG_NAMESPACE:-postgres}"
export PG_USER="${PG_USER:-myuser}"
export PG_PASSWORD="${PG_PASSWORD:-mypassword}"
export PG_DB="${PG_DB:-mydb}"
export PG_URL="postgres://${PG_USER}:${PG_PASSWORD}@postgres.${PG_NAMESPACE}.svc.cluster.local:5432/${PG_DB}?sslmode=disable"

# --- Token Exchange ---
export TOKEN_EXPIRATION="${TOKEN_EXPIRATION:-1m}"

# --- Agent script extras ---
export CA_CERT="${CA_CERT:-}"                            # Optional: path to CA cert for TLS verification

# --- Derived (do not edit) ---
export RESOURCE_BASE_URL="https://${GATEWAY_HOSTNAME}"
export OAUTH_ISSUER_BASE_URL="https://${GATEWAY_HOSTNAME}/oauth-issuer"
