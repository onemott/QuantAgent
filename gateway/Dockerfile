FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o gateway ./cmd/main.go

FROM alpine:3.19
RUN apk add --no-cache ca-certificates tzdata
WORKDIR /app
COPY --from=builder /app/gateway .

ENV NATS_URL=nats://nats:4222
ENV SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT
ENV BINANCE_TESTNET=true

EXPOSE 8888
CMD ["./gateway"]
