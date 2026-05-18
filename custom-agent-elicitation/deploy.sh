#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/env.sh"

# Validate required variables
REQUIRED_VARS=(
  AGW_VERSION AGENTGATEWAY_LICENSE_KEY
  GATEWAY_HOSTNAME TLS_CERT TLS_KEY
  ENTRA_TENANT_ID ENTRA_CLIENT_ID ENTRA_CLIENT_SECRET
  ENTRA_AGENT_CLIENT_ID ENTRA_AGENT_CLIENT_SECRET
  BACKEND_HOST BACKEND_PATH BACKEND_ROUTE_PREFIX
  BACKEND_APP_ID BACKEND_BASE_URL BACKEND_MCP_RESOURCE BACKEND_SCOPES
)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: Required variable ${var} is not set. Edit env.sh first."
    exit 1
  fi
done

HELM_VERSION="v${AGW_VERSION#v}"

echo "============================================"
echo " Elicitation Re-Trigger Bug Reproducer"
echo " Cluster: ${CLUSTER_NAME}"
echo " AGW Version: ${AGW_VERSION}"
echo " Backend: ${BACKEND_HOST}${BACKEND_PATH}"
echo "============================================"

# Step 1: Create Kind cluster
echo ""
echo "==> Step 1: Creating Kind cluster '${CLUSTER_NAME}'..."
cat <<EOF | kind create cluster --name "${CLUSTER_NAME}" --image "${KIND_IMAGE}" --config -
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
EOF
echo "==> Cluster created. Context: kind-${CLUSTER_NAME}"

# Step 2: Start cloud-provider-kind (for LoadBalancer IP)
if ! pgrep -f cloud-provider-kind &>/dev/null; then
  echo ""
  echo "==> Step 2: Starting cloud-provider-kind in background..."
  cloud-provider-kind &>/dev/null &
  sleep 2
else
  echo ""
  echo "==> Step 2: cloud-provider-kind already running"
fi

# Step 3: Install Gateway API CRDs
echo ""
echo "==> Step 3: Installing Gateway API CRDs..."
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml

# Step 4: Deploy PostgreSQL
echo ""
echo "==> Step 4: Deploying PostgreSQL..."
kubectl create namespace "${PG_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
envsubst < "${SCRIPT_DIR}/manifests/postgres.yaml" | kubectl apply -f -
kubectl -n "${PG_NAMESPACE}" rollout status deploy/postgres --timeout=120s
echo "==> PostgreSQL ready"

# Step 5: Create AGW namespace + OAuth issuer config secret
echo ""
echo "==> Step 5: Creating OAuth issuer config secret..."
kubectl create namespace "${AGW_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

OAUTH_ISSUER_JSON="{\"gateway_config\":{\"base_url\":\"${OAUTH_ISSUER_BASE_URL}\"},\"downstream_server\":{\"name\":\"downstream\",\"client_id\":\"${ENTRA_CLIENT_ID}\",\"client_secret\":\"${ENTRA_CLIENT_SECRET}\",\"authorize_url\":\"${ENTRA_AUTHORIZE_URL}\",\"token_url\":\"${ENTRA_TOKEN_URL}\",\"scopes\":[\"${ENTRA_SCOPE}\"]}}"

kubectl -n "${AGW_NAMESPACE}" create secret generic agentgateway-oauth-issuer-config \
  --from-literal="KGW_OAUTH_ISSUER_CONFIG=${OAUTH_ISSUER_JSON}" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "==> OAuth issuer config secret created"

# Step 6: Install Enterprise AgentGateway
echo ""
echo "==> Step 6: Installing Enterprise AgentGateway ${HELM_VERSION}..."
helm upgrade -i --create-namespace -n "${AGW_NAMESPACE}" --version "${HELM_VERSION}" \
  enterprise-agentgateway-crds \
  "${AGW_HELM_REGISTRY}/enterprise-agentgateway-crds"

AGW_VALUES=$(mktemp)
envsubst < "${SCRIPT_DIR}/manifests/agw-values.yaml.tpl" > "${AGW_VALUES}"

helm upgrade -i -n "${AGW_NAMESPACE}" --version "${HELM_VERSION}" \
  enterprise-agentgateway \
  "${AGW_HELM_REGISTRY}/enterprise-agentgateway" \
  --set-string licensing.licenseKey="${AGENTGATEWAY_LICENSE_KEY}" \
  -f "${AGW_VALUES}"

rm -f "${AGW_VALUES}"
kubectl -n "${AGW_NAMESPACE}" rollout status deploy/enterprise-agentgateway --timeout=120s
echo "==> AGW installed"

# Step 7: Patch controller with KGW_OAUTH_ISSUER_CONFIG env var
echo ""
echo "==> Step 7: Patching controller with KGW_OAUTH_ISSUER_CONFIG env var..."
kubectl -n "${AGW_NAMESPACE}" patch deploy enterprise-agentgateway --type json \
  -p '[{"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KGW_OAUTH_ISSUER_CONFIG","valueFrom":{"secretKeyRef":{"name":"agentgateway-oauth-issuer-config","key":"KGW_OAUTH_ISSUER_CONFIG"}}}}]'
kubectl -n "${AGW_NAMESPACE}" rollout status deploy/enterprise-agentgateway --timeout=120s
echo "==> Controller patched"

# Step 8: Create TLS secret + apply K8s manifests
echo ""
echo "==> Step 8: Deploying gateway infrastructure..."
kubectl -n "${AGW_NAMESPACE}" create secret tls "${TLS_SECRET_NAME}" \
  --cert="${TLS_CERT}" --key="${TLS_KEY}" --dry-run=client -o yaml | kubectl apply -f -

for manifest in gatewayclass.yaml gateway.yaml backends.yaml routes.yaml token-exchange.yaml; do
  echo "  --> Applying ${manifest}"
  envsubst < "${SCRIPT_DIR}/manifests/${manifest}" | kubectl apply -f -
done

echo "==> Waiting for gateway to be programmed..."
kubectl -n "${AGW_NAMESPACE}" wait --for=condition=Programmed gateway/agentgateway --timeout=120s
kubectl -n "${AGW_NAMESPACE}" wait --for=condition=Ready pod -l gateway.networking.k8s.io/gateway-name=agentgateway --timeout=120s

echo "==> Waiting for LoadBalancer IP..."
until LB_IP=$(kubectl -n "${AGW_NAMESPACE}" get svc agentgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null) && [[ -n "${LB_IP}" ]]; do
  sleep 2
done
LB_PORT=$(kubectl -n "${AGW_NAMESPACE}" get svc agentgateway -o jsonpath='{.spec.ports[0].port}')
echo "==> Gateway LB: https://${LB_IP}:${LB_PORT}"

# Step 9: JWKS race condition workaround
echo ""
echo "==> Step 9: Waiting for JWKS ConfigMap (race condition workaround)..."
until kubectl -n "${AGW_NAMESPACE}" get cm --no-headers 2>/dev/null | grep -q jwks; do
  sleep 3
done
echo "==> JWKS ConfigMap found. Waiting 10s for population..."
sleep 10
echo "==> Restarting controller to re-translate backends..."
kubectl -n "${AGW_NAMESPACE}" rollout restart deploy/enterprise-agentgateway
kubectl -n "${AGW_NAMESPACE}" rollout status deploy/enterprise-agentgateway --timeout=120s
sleep 5
echo "==> Restarting proxy to pick up re-translated config..."
kubectl -n "${AGW_NAMESPACE}" rollout restart deploy/agentgateway
kubectl -n "${AGW_NAMESPACE}" rollout status deploy/agentgateway --timeout=120s

# Step 10: Verify
echo ""
echo "==> Step 10: Verifying deployment..."
echo ""
echo "--- Pods ---"
kubectl get pods -A | grep -E "(agentgateway|postgres)"
echo ""
echo "--- Gateway ---"
kubectl -n "${AGW_NAMESPACE}" get gateway
echo ""
echo "--- HTTPRoutes ---"
kubectl -n "${AGW_NAMESPACE}" get httproute
echo ""
echo "--- AgentgatewayBackends ---"
kubectl -n "${AGW_NAMESPACE}" get agentgatewaybackend
echo ""
echo "--- EnterpriseAgentgatewayPolicies ---"
kubectl -n "${AGW_NAMESPACE}" get enterpriseagentgatewaypolicy

echo ""
echo "============================================"
echo " Deployment complete!"
echo ""
echo " Gateway: https://${GATEWAY_HOSTNAME} (LB: ${LB_IP}:${LB_PORT})"
echo " MCP Route: ${BACKEND_ROUTE_PREFIX}"
echo " Token Expiry: ${TOKEN_EXPIRATION}"
echo ""
echo " Next: Run the agent to reproduce the bug:"
echo "   source env.sh"
echo "   python agent.py"
echo "============================================"
