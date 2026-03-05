package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"strings"

	core "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	auth "github.com/envoyproxy/go-control-plane/envoy/service/auth/v3"
	envoy_type "github.com/envoyproxy/go-control-plane/envoy/type/v3"
	"golang.org/x/net/context"
	"google.golang.org/genproto/googleapis/rpc/status"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/structpb"
)

const (
	defaultPort     = "9001"
	defaultProvider = "openai"
)

type authServer struct {
	auth.UnimplementedAuthorizationServer
}

// llmRequest is a minimal struct to extract the model from the request body.
type llmRequest struct {
	Model string `json:"model"`
}

func (s *authServer) Check(ctx context.Context, req *auth.CheckRequest) (*auth.CheckResponse, error) {
	httpReq := req.GetAttributes().GetRequest().GetHttp()
	body := httpReq.GetBody()
	log.Printf("[mock-extauth] Check called: method=%s path=%s body_len=%d", httpReq.GetMethod(), httpReq.GetPath(), len(body))

	// Extract model from request body
	var parsed llmRequest
	modelName := ""
	if body != "" {
		if err := json.Unmarshal([]byte(body), &parsed); err != nil {
			log.Printf("[mock-extauth] Failed to parse body: %v", err)
		} else {
			modelName = parsed.Model
		}
	}

	if modelName == "" {
		modelName = "unknown"
	}

	// Determine provider from model name:
	//   1. Explicit prefix: "anthropic/claude-3" -> provider=anthropic, model=claude-3
	//   2. Model name pattern: "claude-*" -> provider=anthropic
	//   3. Default: provider=openai
	provider := defaultProvider
	if idx := strings.Index(modelName, "/"); idx > 0 {
		provider = modelName[:idx]
		modelName = modelName[idx+1:]
	} else if strings.HasPrefix(modelName, "claude") {
		provider = "anthropic"
	}

	modelWithProvider := provider + "/" + modelName

	// Extract or default x-client-id (agent identity)
	// In production, this comes from Entra ID JWT validation.
	// For testing, pass it as a header or default to "unknown".
	clientID := httpReq.GetHeaders()["x-client-id"]
	if clientID == "" {
		clientID = "unknown"
	}

	log.Printf("[mock-extauth] Resolved: provider=%s model=%s combined=%s client_id=%s", provider, modelName, modelWithProvider, clientID)

	dynMetadata, err := structpb.NewStruct(map[string]interface{}{
		"x-model-provider":           provider,
		"x-model-name":               modelName,
		"x-model-name-with-provider": modelWithProvider,
	})
	if err != nil {
		log.Printf("[mock-extauth] Error building dynamic metadata: %v", err)
		return &auth.CheckResponse{
			Status:       &status.Status{Code: int32(0)},
			HttpResponse: &auth.CheckResponse_OkResponse{OkResponse: &auth.OkHttpResponse{}},
		}, nil
	}

	log.Printf("[mock-extauth] Returning OK with dynamic_metadata: %v, headers: x-model-provider=%s x-model-name=%s", dynMetadata, provider, modelName)

	return &auth.CheckResponse{
		Status: &status.Status{Code: int32(0)},
		HttpResponse: &auth.CheckResponse_OkResponse{
			OkResponse: &auth.OkHttpResponse{
				Headers: []*core.HeaderValueOption{
					{
						Header:       &core.HeaderValue{Key: "x-extauth-ran", Value: "true"},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
					{
						Header:       &core.HeaderValue{Key: "x-model-provider", Value: provider},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
					{
						Header:       &core.HeaderValue{Key: "x-model-name", Value: modelName},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
					{
						Header:       &core.HeaderValue{Key: "x-model-name-with-provider", Value: modelWithProvider},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
					{
						Header:       &core.HeaderValue{Key: "x-client-id", Value: clientID},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
				},
				ResponseHeadersToAdd: []*core.HeaderValueOption{
					{
						Header:       &core.HeaderValue{Key: "x-model-provider", Value: provider},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
					{
						Header:       &core.HeaderValue{Key: "x-model-name", Value: modelName},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
					{
						Header:       &core.HeaderValue{Key: "x-model-name-with-provider", Value: modelWithProvider},
						AppendAction: core.HeaderValueOption_OVERWRITE_IF_EXISTS_OR_ADD,
					},
				},
			},
		},
		DynamicMetadata: dynMetadata,
	}, nil
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = defaultPort
	}

	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen on port %s: %v", port, err)
	}

	grpcServer := grpc.NewServer()
	auth.RegisterAuthorizationServer(grpcServer, &authServer{})

	healthCheck := &envoy_type.HttpStatus{}
	_ = healthCheck

	log.Printf("[mock-extauth] gRPC ext auth server listening on :%s (body-aware, dynamic model resolution)", port)

	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}
