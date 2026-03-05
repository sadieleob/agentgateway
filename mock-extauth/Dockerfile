FROM golang:1.22 AS builder
WORKDIR /app
COPY go.mod ./
COPY main.go ./
RUN go mod tidy && go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o /mock-extauth .

FROM gcr.io/distroless/static:nonroot
COPY --from=builder /mock-extauth /mock-extauth
ENTRYPOINT ["/mock-extauth"]
