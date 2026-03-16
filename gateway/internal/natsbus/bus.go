// Package natsbus provides a thin wrapper around the NATS client for publishing
// and subscribing to QuantAgent market/signal topics.
//
// Topics convention:
//   market.{SYMBOL}.ticker  — real-time ticker (price, change, volume)
//   market.{SYMBOL}.kline   — completed candlestick OHLCV
//   signal.order            — incoming trade signal from AI strategy layer

package natsbus

import (
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/nats-io/nats.go"
)

// Bus wraps a NATS connection with convenience publish/subscribe methods.
type Bus struct {
	conn *nats.Conn
}

// NewBus creates a new Bus connected to the given NATS server URL.
// Reconnect logic is handled automatically by the NATS client.
func NewBus(url string) (*Bus, error) {
	opts := []nats.Option{
		nats.Name("quantagent-gateway"),
		nats.ReconnectWait(2 * time.Second),
		nats.MaxReconnects(-1), // unlimited
		nats.DisconnectErrHandler(func(nc *nats.Conn, err error) {
			log.Printf("[nats] Disconnected: %v", err)
		}),
		nats.ReconnectHandler(func(nc *nats.Conn) {
			log.Printf("[nats] Reconnected to %s", nc.ConnectedUrl())
		}),
	}

	conn, err := nats.Connect(url, opts...)
	if err != nil {
		return nil, fmt.Errorf("nats.Connect(%s): %w", url, err)
	}
	return &Bus{conn: conn}, nil
}

// Publish serializes v as JSON and publishes it to subject.
func (b *Bus) Publish(subject string, v any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("json marshal: %w", err)
	}
	return b.conn.Publish(subject, data)
}

// Subscribe registers a JSON message handler on subject.
// The handler receives the raw message bytes; callers decode as needed.
func (b *Bus) Subscribe(subject string, handler func(msg []byte)) (*nats.Subscription, error) {
	return b.conn.Subscribe(subject, func(m *nats.Msg) {
		handler(m.Data)
	})
}

// Close gracefully closes the NATS connection.
func (b *Bus) Close() {
	if b.conn != nil {
		b.conn.Drain() //nolint:errcheck
	}
}

// ── Topic helpers ─────────────────────────────────────────────────────────────

// TickerTopic returns the NATS subject for ticker updates of a symbol.
func TickerTopic(symbol string) string { return "market." + symbol + ".ticker" }

// KlineTopic returns the NATS subject for kline events of a symbol.
func KlineTopic(symbol string) string { return "market." + symbol + ".kline" }

// OrderSignalTopic is the subject where AI signals publish trade instructions.
const OrderSignalTopic = "signal.order"
