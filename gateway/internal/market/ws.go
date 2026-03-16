// Package market provides a Binance WebSocket market data stream.
// It connects to Binance's combined stream endpoint and publishes
// normalized ticker and kline events to NATS.
//
// Binance combined stream:
//   wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker/...

package market

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/quantagent/gateway/internal/natsbus"
)

// TickerMsg is the normalized ticker payload published to NATS.
type TickerMsg struct {
	Symbol         string  `json:"symbol"`
	Price          float64 `json:"price"`
	Change24h      float64 `json:"change_24h"`
	ChangePct      float64 `json:"change_pct"`
	Volume         float64 `json:"volume"`
	High24h        float64 `json:"high_24h"`
	Low24h         float64 `json:"low_24h"`
	Timestamp      int64   `json:"timestamp"` // Unix ms
}

// KlineMsg is the normalized candlestick payload published to NATS.
type KlineMsg struct {
	Symbol    string  `json:"symbol"`
	Interval  string  `json:"interval"`
	OpenTime  int64   `json:"open_time"`
	CloseTime int64   `json:"close_time"`
	Open      float64 `json:"open"`
	High      float64 `json:"high"`
	Low       float64 `json:"low"`
	Close     float64 `json:"close"`
	Volume    float64 `json:"volume"`
	Closed    bool    `json:"closed"` // true = candle is finalized
}

// binanceTickerEvent is the raw JSON from Binance 24hr ticker stream.
type binanceTickerEvent struct {
	EventType string `json:"e"`
	Symbol    string `json:"s"`
	LastPrice string `json:"c"`
	PriceChange string `json:"p"`
	PriceChangePct string `json:"P"`
	Volume    string `json:"q"` // Quote asset volume
	High      string `json:"h"`
	Low       string `json:"l"`
	EventTime int64  `json:"E"`
}

// binanceCombinedMsg wraps a combined stream message.
type binanceCombinedMsg struct {
	Stream string          `json:"stream"`
	Data   json.RawMessage `json:"data"`
}

// Stream manages the Binance WebSocket connection and NATS publishing.
type Stream struct {
	symbols []string
	bus     *natsbus.Bus
	conn    *websocket.Conn
	mu      sync.Mutex
	stopCh  chan struct{}
	proxyURL string
}

// NewStream creates a new market Stream for the given symbols.
func NewStream(symbols []string, bus *natsbus.Bus, proxyURL string) *Stream {
	return &Stream{
		symbols: symbols,
		bus:     bus,
		stopCh:  make(chan struct{}),
		proxyURL: proxyURL,
	}
}

// Start connects to Binance and begins publishing. Reconnects automatically on failure.
func (s *Stream) Start() error {
	go s.runLoop()
	return nil
}

// Stop signals the stream to shut down.
func (s *Stream) Stop() {
	close(s.stopCh)
	s.mu.Lock()
	if s.conn != nil {
		s.conn.Close()
	}
	s.mu.Unlock()
}

func (s *Stream) runLoop() {
	for {
		select {
		case <-s.stopCh:
			return
		default:
		}

		if err := s.connect(); err != nil {
			log.Printf("[market] WebSocket connect failed: %v — retrying in 5s", err)
			select {
			case <-s.stopCh:
				return
			case <-time.After(5 * time.Second):
			}
		}
	}
}

func (s *Stream) connect() error {
	// Build combined stream URL: btcusdt@ticker/ethusdt@ticker/...
	streams := make([]string, 0, len(s.symbols)*2)
	for _, sym := range s.symbols {
		streams = append(streams, strings.ToLower(sym)+"@ticker")
		streams = append(streams, strings.ToLower(sym)+"@kline_1m")
	}
	combined := strings.Join(streams, "/")

	u := url.URL{
		Scheme:   "wss",
		Host:     "stream.binance.com:9443",
		Path:     "/stream",
		RawQuery: "streams=" + combined,
	}

	dialer := websocket.DefaultDialer
	if s.proxyURL != "" {
		proxy, err := url.Parse(s.proxyURL)
		if err != nil {
			return fmt.Errorf("parse proxy url: %w", err)
		}
		dialer = &websocket.Dialer{
			Proxy:            http.ProxyURL(proxy),
			HandshakeTimeout: 45 * time.Second,
		}
		log.Printf("[market] Using proxy: %s", s.proxyURL)
	}

	conn, _, err := dialer.Dial(u.String(), nil)
	if err != nil {
		return fmt.Errorf("dial %s: %w", u.String(), err)
	}

	s.mu.Lock()
	s.conn = conn
	s.mu.Unlock()

	log.Printf("[market] WebSocket connected: %d symbols", len(s.symbols))

	for {
		select {
		case <-s.stopCh:
			conn.Close()
			return nil
		default:
		}

		_, msg, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}

		s.handleMessage(msg)
	}
}

func (s *Stream) handleMessage(raw []byte) {
	var combined binanceCombinedMsg
	if err := json.Unmarshal(raw, &combined); err != nil {
		return
	}

	// Determine stream type from stream name (e.g. "btcusdt@ticker")
	if strings.HasSuffix(combined.Stream, "@ticker") {
		s.handleTicker(combined.Data)
	} else if strings.Contains(combined.Stream, "@kline_") {
		s.handleKline(combined.Data)
	}
}

func (s *Stream) handleTicker(data json.RawMessage) {
	var raw binanceTickerEvent
	if err := json.Unmarshal(data, &raw); err != nil {
		return
	}

	ticker := TickerMsg{
		Symbol:    raw.Symbol,
		Price:     parseFloat(raw.LastPrice),
		Change24h: parseFloat(raw.PriceChange),
		ChangePct: parseFloat(raw.PriceChangePct),
		Volume:    parseFloat(raw.Volume),
		High24h:   parseFloat(raw.High),
		Low24h:    parseFloat(raw.Low),
		Timestamp: raw.EventTime,
	}

	topic := natsbus.TickerTopic(raw.Symbol)
	if err := s.bus.Publish(topic, ticker); err != nil {
		log.Printf("[market] NATS publish %s failed: %v", topic, err)
	}
}

func (s *Stream) handleKline(data json.RawMessage) {
	// Kline event structure (abbreviated)
	var raw struct {
		Symbol string `json:"s"`
		Kline  struct {
			Interval  string `json:"i"`
			OpenTime  int64  `json:"t"`
			CloseTime int64  `json:"T"`
			Open      string `json:"o"`
			High      string `json:"h"`
			Low       string `json:"l"`
			Close     string `json:"c"`
			Volume    string `json:"v"`
			Closed    bool   `json:"x"`
		} `json:"k"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return
	}

	kline := KlineMsg{
		Symbol:    raw.Symbol,
		Interval:  raw.Kline.Interval,
		OpenTime:  raw.Kline.OpenTime,
		CloseTime: raw.Kline.CloseTime,
		Open:      parseFloat(raw.Kline.Open),
		High:      parseFloat(raw.Kline.High),
		Low:       parseFloat(raw.Kline.Low),
		Close:     parseFloat(raw.Kline.Close),
		Volume:    parseFloat(raw.Kline.Volume),
		Closed:    raw.Kline.Closed,
	}

	topic := natsbus.KlineTopic(raw.Symbol)
	if err := s.bus.Publish(topic, kline); err != nil {
		log.Printf("[market] NATS publish kline %s failed: %v", topic, err)
	}
}

func parseFloat(s string) float64 {
	var f float64
	fmt.Sscanf(s, "%f", &f)
	return f
}
