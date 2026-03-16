// Package order provides a Binance order executor.
// It subscribes to the NATS "signal.order" topic and executes
// market orders via Binance REST API (Testnet or Live).
//
// Signal message format (JSON):
//
//	{
//	  "symbol":    "BTCUSDT",
//	  "side":      "BUY",        // BUY | SELL
//	  "quantity":  0.001,
//	  "source":    "trend_agent" // optional: originating agent
//	}

package order

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/quantagent/gateway/internal/natsbus"
)

// OrderSignal is the trade instruction received from the AI layer via NATS.
type OrderSignal struct {
	Symbol   string  `json:"symbol"`
	Side     string  `json:"side"`     // BUY | SELL
	Quantity float64 `json:"quantity"`
	Source   string  `json:"source"`   // originating agent name
}

// OrderResult is the outcome of an order execution attempt.
type OrderResult struct {
	Symbol    string  `json:"symbol"`
	Side      string  `json:"side"`
	Quantity  float64 `json:"quantity"`
	Price     float64 `json:"price"`
	OrderID   int64   `json:"order_id"`
	Status    string  `json:"status"`
	Timestamp int64   `json:"timestamp"`
	Error     string  `json:"error,omitempty"`
}

const (
	binanceLiveBase    = "https://api.binance.com"
	binanceTestnetBase = "https://testnet.binance.vision"
)

// Executor subscribes to NATS order signals and executes them on Binance.
type Executor struct {
	apiKey    string
	secretKey string
	baseURL   string
	bus       *natsbus.Bus
	client    *http.Client
}

// NewExecutor creates a new order Executor.
// If testnet=true, orders are sent to Binance Testnet (safe for development).
func NewExecutor(apiKey, secretKey string, testnet bool, bus *natsbus.Bus, proxyURL string) *Executor {
	base := binanceLiveBase
	if testnet {
		base = binanceTestnetBase
	}
	
	var transport http.RoundTripper = http.DefaultTransport
	
	if proxyURL != "" {
		if u, err := url.Parse(proxyURL); err == nil {
			if t, ok := http.DefaultTransport.(*http.Transport); ok {
				newT := t.Clone()
				newT.Proxy = http.ProxyURL(u)
				transport = newT
			} else {
				transport = &http.Transport{
					Proxy: http.ProxyURL(u),
				}
			}
			log.Printf("[order] Using proxy: %s", proxyURL)
		} else {
			log.Printf("[order] Invalid proxy URL: %v", err)
		}
	}
	
	return &Executor{
		apiKey:    apiKey,
		secretKey: secretKey,
		baseURL:   base,
		bus:       bus,
		client:    &http.Client{
			Timeout:   10 * time.Second,
			Transport: transport,
		},
	}
}

// StartListener subscribes to NATS signal.order and processes each message.
// Returns an error only if the NATS subscription itself fails.
func (e *Executor) StartListener() error {
	_, err := e.bus.Subscribe(natsbus.OrderSignalTopic, func(msg []byte) {
		var sig OrderSignal
		if err := json.Unmarshal(msg, &sig); err != nil {
			log.Printf("[order] Failed to parse signal: %v", err)
			return
		}
		log.Printf("[order] Received signal: %s %s %.6f from %s",
			sig.Side, sig.Symbol, sig.Quantity, sig.Source)

		result := e.executeOrder(sig)
		if result.Error != "" {
			log.Printf("[order] Order failed: %s", result.Error)
		} else {
			log.Printf("[order] Order filled: %s %s %.6f @ %.2f (id=%d)",
				result.Side, result.Symbol, result.Quantity, result.Price, result.OrderID)
		}

		// Publish result back to NATS for monitoring
		_ = e.bus.Publish("order.result."+strings.ToLower(sig.Symbol), result)
	})
	return err
}

// executeOrder places a MARKET order on Binance.
func (e *Executor) executeOrder(sig OrderSignal) OrderResult {
	if e.apiKey == "" {
		return OrderResult{
			Symbol: sig.Symbol, Side: sig.Side, Quantity: sig.Quantity,
			Status: "SKIPPED", Error: "API key not configured",
			Timestamp: time.Now().UnixMilli(),
		}
	}

	params := url.Values{}
	params.Set("symbol", sig.Symbol)
	params.Set("side", strings.ToUpper(sig.Side))
	params.Set("type", "MARKET")
	params.Set("quantity", strconv.FormatFloat(sig.Quantity, 'f', 8, 64))
	params.Set("timestamp", strconv.FormatInt(time.Now().UnixMilli(), 10))

	// HMAC-SHA256 signature
	sig256 := e.sign(params.Encode())
	params.Set("signature", sig256)

	endpoint := e.baseURL + "/api/v3/order"
	req, err := http.NewRequest(http.MethodPost, endpoint, strings.NewReader(params.Encode()))
	if err != nil {
		return OrderResult{Symbol: sig.Symbol, Side: sig.Side, Error: err.Error(),
			Timestamp: time.Now().UnixMilli()}
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("X-MBX-APIKEY", e.apiKey)

	resp, err := e.client.Do(req)
	if err != nil {
		return OrderResult{Symbol: sig.Symbol, Side: sig.Side, Error: err.Error(),
			Timestamp: time.Now().UnixMilli()}
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return OrderResult{
			Symbol: sig.Symbol, Side: sig.Side,
			Error:  fmt.Sprintf("HTTP %d: %s", resp.StatusCode, string(body)),
			Timestamp: time.Now().UnixMilli(),
		}
	}

	// Parse Binance order response
	var binResp struct {
		OrderID         int64   `json:"orderId"`
		Symbol          string  `json:"symbol"`
		Side            string  `json:"side"`
		Status          string  `json:"status"`
		ExecutedQty     string  `json:"executedQty"`
		CummulativeQuoteQty string `json:"cummulativeQuoteQty"`
		Fills           []struct {
			Price string `json:"price"`
		} `json:"fills"`
	}
	if err := json.Unmarshal(body, &binResp); err != nil {
		return OrderResult{Symbol: sig.Symbol, Side: sig.Side, Error: "parse response: " + err.Error(),
			Timestamp: time.Now().UnixMilli()}
	}

	// Average fill price from fills
	var avgPrice float64
	if len(binResp.Fills) > 0 {
		fmt.Sscanf(binResp.Fills[0].Price, "%f", &avgPrice)
	}

	execQty, _ := strconv.ParseFloat(binResp.ExecutedQty, 64)
	return OrderResult{
		Symbol:    binResp.Symbol,
		Side:      binResp.Side,
		Quantity:  execQty,
		Price:     avgPrice,
		OrderID:   binResp.OrderID,
		Status:    binResp.Status,
		Timestamp: time.Now().UnixMilli(),
	}
}

// sign creates an HMAC-SHA256 signature for Binance API authentication.
func (e *Executor) sign(payload string) string {
	mac := hmac.New(sha256.New, []byte(e.secretKey))
	mac.Write([]byte(payload))
	return hex.EncodeToString(mac.Sum(nil))
}
