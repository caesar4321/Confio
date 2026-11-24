package main

import (
	"context"
	"log"
	"net"
	"sync/atomic"
	"time"

	"golang.org/x/net/proxy"
)

// meter counts the bytes one device's connections carry (WhatsApp's socket, through its proxy or not): what a
// proxy provider bills by the GB. Logged hourly per device, never with anything but the link id.
type meter struct {
	in, out atomic.Int64
}

type meteredDialer struct {
	base  proxy.ContextDialer
	meter *meter
}

func (m meteredDialer) Dial(network, addr string) (net.Conn, error) {
	return m.DialContext(context.Background(), network, addr)
}

func (m meteredDialer) DialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	conn, err := m.base.DialContext(ctx, network, addr)
	if err != nil {
		return nil, err
	}
	return &meteredConn{Conn: conn, meter: m.meter}, nil
}

type meteredConn struct {
	net.Conn
	meter *meter
}

func (c *meteredConn) Read(p []byte) (int, error) {
	n, err := c.Conn.Read(p)
	c.meter.in.Add(int64(n))
	return n, err
}

func (c *meteredConn) Write(p []byte) (int, error) {
	n, err := c.Conn.Write(p)
	c.meter.out.Add(int64(n))
	return n, err
}

// reportTraffic logs each device's bytes of the last hour, and the total, then starts counting again.
func (b *bridge) reportTraffic(ctx context.Context) {
	ticker := time.NewTicker(time.Hour)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		b.mu.Lock()
		devices := make([]*device, 0, len(b.devices))
		for _, d := range b.devices {
			devices = append(devices, d)
		}
		b.mu.Unlock()
		var total int64
		for _, d := range devices {
			in, out := d.meter.in.Swap(0), d.meter.out.Swap(0)
			total += in + out
			log.Printf("op=traffic link=%s country=%s proxied=%v in_kb=%d out_kb=%d", d.link, d.country,
				b.proxies.For(d.country, d.link) != "", in/1024, out/1024)
		}
		log.Printf("op=traffic_total devices=%d kb=%d", len(devices), total/1024)
	}
}
