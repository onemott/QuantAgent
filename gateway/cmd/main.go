// QuantAgent Gateway — Go High-Speed Market Data & Order Execution Service
//
// Responsibilities:
//   - Connect directly to Binance WebSocket (Spot) for real-time ticker/kline streams
//   - Parse and normalize incoming market data
//   - Publish normalized data to NATS topics: market.{SYMBOL}.ticker / market.{SYMBOL}.kline
//   - Subscribe to NATS topic signal.order — receive trade signals from Python AI layer
//   - Execute orders via Binance REST API (Testnet/Live) with basic risk pre-flight check
//
// Run:
//   go run ./cmd/main.go
//
// Environment variables (see .env.gateway):
//   BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET (true/false)
//   NATS_URL (default: nats://localhost:4222)
//   SYMBOLS   (comma-separated, default: BTCUSDT,ETHUSDT,SOLUSDT)
//   LOG_LEVEL (debug/info/warn/error)

package main

import (
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/quantagent/gateway/internal/market"
	"github.com/quantagent/gateway/internal/natsbus"
	"github.com/quantagent/gateway/internal/order"
)

func main() {
	// ── Configuration from environment ──────────────────────────────────────
	natsURL := envOrDefault("NATS_URL", "nats://localhost:4223")
	symbolsRaw := envOrDefault("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT")
	symbols := strings.Split(symbolsRaw, ",")
	binanceTestnet := envOrDefault("BINANCE_TESTNET", "true") == "true"
	proxyURL := envOrDefault("BINANCE_PROXY", "")

	log.Printf("[gateway] Starting QuantAgent Gateway")
	log.Printf("[gateway] NATS: %s | Symbols: %v | Testnet: %v", natsURL, symbols, binanceTestnet)
	if proxyURL != "" {
		log.Printf("[gateway] Using Proxy: %s", proxyURL)
	}

	// ── NATS bus ─────────────────────────────────────────────────────────────
	bus, err := natsbus.NewBus(natsURL)
	if err != nil {
		log.Fatalf("[gateway] Failed to connect NATS: %v", err)
	}
	defer bus.Close()
	log.Printf("[gateway] NATS connected: %s", natsURL)

	// ── Market data stream ────────────────────────────────────────────────────
	stream := market.NewStream(symbols, bus, proxyURL)
	if err := stream.Start(); err != nil {
		log.Fatalf("[gateway] Failed to start market stream: %v", err)
	}
	log.Printf("[gateway] Market stream started for %d symbols", len(symbols))

	// ── Order executor ────────────────────────────────────────────────────────
	executor := order.NewExecutor(
		os.Getenv("BINANCE_API_KEY"),
		os.Getenv("BINANCE_SECRET_KEY"),
		binanceTestnet,
		bus,
		proxyURL,
	)
	if err := executor.StartListener(); err != nil {
		log.Printf("[gateway] Order executor warning: %v (order execution disabled)", err)
	} else {
		log.Printf("[gateway] Order executor listening on NATS topic: signal.order")
	}

	// ── Graceful shutdown ─────────────────────────────────────────────────────
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	sig := <-quit
	log.Printf("[gateway] Received signal %v — shutting down gracefully", sig)

	stream.Stop()
	log.Printf("[gateway] Gateway stopped.")
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
