package main

import (
	"context"
	"database/sql"
	"errors"
	"log"
	"net"
	"net/url"
	"sync"
	"time"

	"golang.org/x/net/proxy"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// A linked or pairing device of one Confío link. paired, dropping and cancel are guarded by bridge.mu.
type device struct {
	link    string
	grant   string
	country string // the number's country: its proxy route
	meter   meter  // bytes its connections carry (traffic.go)
	client  *whatsmeow.Client
	// Pairing only: the number typed in Confío, when it started, until when codes are asked again, how to stop.
	phone    string
	started  time.Time
	until    time.Time
	cancel   context.CancelFunc
	paired   bool
	dropping bool       // being removed: a PairSuccess landing now logs the device straight out
	refused  bool       // paired, but not to be kept (another number, or dropping): passes nothing on
	sendMu   sync.Mutex // one send at a time per person, at a person's pace
}

type bridge struct {
	db        *sql.DB
	container *sqlstore.Container
	token     string
	callback  string

	mu      sync.Mutex
	devices map[string]*device // by link
	pairing sync.Map           // link -> *sync.Mutex: one pair() per link at a time
	wake    chan struct{}
	http    httpDoer
	proxies proxies
}

func newBridge(db *sql.DB, container *sqlstore.Container, token, callback string) *bridge {
	return &bridge{db: db, container: container, token: token, callback: callback,
		devices: map[string]*device{}, wake: make(chan struct{}, 1), http: defaultHTTP()}
}

func (b *bridge) count() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.devices)
}

func (b *bridge) get(link string) *device {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.devices[link]
}

// route sends a device's connections through its country's proxy, if one is set (proxy.go), and counts their
// bytes either way. It also keeps the chat history WhatsApp offers a new device from being downloaded: only new
// messages are used.
func (b *bridge) route(d *device) error {
	d.client.ManualHistorySyncDownload = true
	var base proxy.ContextDialer = &net.Dialer{Timeout: 30 * time.Second, KeepAlive: 30 * time.Second}
	if address := b.proxies.For(d.country, d.link); address != "" {
		parsed, err := url.Parse(address)
		if err != nil {
			return errors.New("proxy for " + d.country + " not usable") // never the URL: it holds the password
		}
		dialer, err := proxy.FromURL(parsed, base.(*net.Dialer))
		if err != nil {
			return errors.New("proxy for " + d.country + " not usable")
		}
		contextDialer, ok := dialer.(proxy.ContextDialer)
		if !ok {
			return errors.New("proxy for " + d.country + " not usable")
		}
		base = contextDialer
	}
	d.client.SetSOCKSProxy(meteredDialer{base: base, meter: &d.meter})
	return nil
}

func clientLog() waLog.Logger { return waLog.Stdout("wa", "WARN", false) }

// restore connects every linked device again after a restart.
func (b *bridge) restore(ctx context.Context) error {
	rows, err := b.db.QueryContext(ctx, `SELECT link, grant_id, jid, country, route FROM bridge_link WHERE state = 'linked'`)
	if err != nil {
		return err
	}
	type row struct{ link, grant, jid, country, route string }
	var linked []row
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.link, &r.grant, &r.jid, &r.country, &r.route); err != nil {
			rows.Close()
			return err
		}
		linked = append(linked, r)
	}
	rows.Close()
	// Pairings do not survive a restart: their codes are gone. Django's sweep ends them.
	if _, err := b.db.ExecContext(ctx, `DELETE FROM bridge_link WHERE state = 'pairing'`); err != nil {
		return err
	}
	// Keys no linked row points at (a crash between a pairing and its row, or while refusing one): deleted.
	keep := map[string]bool{}
	for _, r := range linked {
		keep[r.jid] = true
	}
	if all, err := b.container.GetAllDevices(ctx); err == nil {
		for _, dev := range all {
			if dev.ID != nil && !keep[dev.ID.String()] {
				log.Printf("deleting keys of a device no link holds")
				if err := dev.Delete(ctx); err != nil {
					log.Printf("deleting orphaned keys failed: %v", err)
				}
			}
		}
	} else {
		log.Printf("orphaned keys not checked: %v", err)
	}
	for _, r := range linked {
		jid, err := types.ParseJID(r.jid)
		var dev *store.Device
		if err == nil {
			dev, err = b.container.GetDevice(ctx, jid)
		}
		if err != nil {
			// The database could not be read: never taken as "keys gone" (that would end a working link).
			log.Printf("link %s: restore failed, retried at the next start: %v", r.link, err)
			continue
		}
		if dev == nil {
			// The keys are gone: the link can never connect again. Django ends it.
			log.Printf("link %s: no device keys, ending", r.link)
			b.ended(ctx, r.link, r.grant, "logged_out")
			continue
		}
		if r.route != "" && b.proxies.Key(r.country) != r.route {
			// Linked through a proxy route that is gone or changed (an edited parameter): never moved to another
			// route or a direct connection without anyone noticing. It waits offline until the route is back.
			log.Printf("ALERT link %s: its proxy route %q no longer resolves; left offline", r.link, r.route)
			continue
		}
		d := &device{link: r.link, grant: r.grant, country: r.country, paired: true}
		d.client = whatsmeow.NewClient(dev, clientLog())
		if err := b.route(d); err != nil {
			log.Printf("link %s: %v", r.link, err)
			continue
		}
		d.client.AddEventHandler(func(evt any) { b.handle(d, evt) })
		b.mu.Lock()
		b.devices[r.link] = d
		b.mu.Unlock()
		go b.keepConnecting(ctx, d)
	}
	return nil
}

// keepConnecting: whatsmeow reconnects by itself only once a first connection was made.
func (b *bridge) keepConnecting(ctx context.Context, d *device) {
	wait := 5 * time.Second
	for {
		err := d.client.Connect()
		if err == nil || errors.Is(err, whatsmeow.ErrAlreadyConnected) {
			return
		}
		log.Printf("link %s: connect failed, again in %s: %v", d.link, wait, err)
		if !sleepCtx(ctx, wait) || b.get(d.link) != d {
			return
		}
		if wait < 5*time.Minute {
			wait *= 2
		}
	}
}

func sleepCtx(ctx context.Context, d time.Duration) bool {
	select {
	case <-ctx.Done():
		return false
	case <-time.After(d):
		return true
	}
}

func (b *bridge) closeAll() {
	b.mu.Lock()
	defer b.mu.Unlock()
	for _, d := range b.devices {
		if d.cancel != nil {
			d.cancel()
		}
		d.client.Disconnect()
	}
}

// handle: what WhatsApp tells a linked device. Never logs a number or a message.
func (b *bridge) handle(d *device, raw any) {
	ctx := context.Background()
	switch evt := raw.(type) {
	case *events.Message:
		b.mu.Lock()
		quiet := d.refused || d.dropping
		b.mu.Unlock()
		if quiet {
			return // a device on its way out (maybe a stranger's WhatsApp): nothing of it is kept
		}
		own := []string{d.client.Store.GetLID().User}
		if d.client.Store.ID != nil {
			own = append(own, d.client.Store.ID.User)
		}
		if data, ok := incoming(ctx, func(info types.MessageInfo) string { return nameOf(ctx, d.client, info) }, evt, own...); ok {
			b.enqueue(ctx, d.link, d.grant, "message", data)
		}
	case *events.LoggedOut:
		// Removed from Dispositivos vinculados on the phone, or WhatsApp ended the session.
		log.Printf("link %s: logged out by WhatsApp (on connect: %v)", d.link, evt.OnConnect)
		if err := b.drop(ctx, d, false); err != nil {
			log.Printf("link %s: %v", d.link, err)
		}
		b.ended(ctx, d.link, d.grant, "logged_out")
	case *events.TemporaryBan:
		log.Printf("link %s: WhatsApp temporary ban (%v)", d.link, evt.Code)
		b.enqueue(ctx, d.link, d.grant, "banned", map[string]any{"expires_in": int(evt.Expire.Seconds())})
	case *events.ClientOutdated:
		// whatsmeow must be updated: every link stops connecting until it is.
		log.Printf("ALERT link %s: WhatsApp says this client is outdated: update whatsmeow", d.link)
		b.enqueue(ctx, d.link, d.grant, "outdated", map[string]any{})
	case *events.StreamReplaced:
		log.Printf("link %s: stream replaced (another process with the same keys)", d.link)
	case *events.ConnectFailure:
		log.Printf("link %s: connect failure %v", d.link, evt.Reason)
	}
}

// ended: this pairing's link is over on WhatsApp's side; Django is told once. A newer pairing's row stays.
func (b *bridge) ended(ctx context.Context, link, grant, kind string) {
	if _, err := b.db.ExecContext(ctx, `DELETE FROM bridge_link WHERE link = $1 AND grant_id = $2`, link, grant); err != nil {
		log.Printf("link %s: forget row failed: %v", link, err)
	}
	b.enqueue(ctx, link, grant, kind, map[string]any{})
}

// take removes d from the devices held, under the lock, and marks it as going: a PairSuccess landing after
// this logs the device out instead of keeping it. Dropping twice is harmless (deleting keys is idempotent).
func (b *bridge) take(d *device) {
	b.mu.Lock()
	defer b.mu.Unlock()
	d.dropping = true
	if b.devices[d.link] == d {
		delete(b.devices, d.link)
	}
}

// drop disconnects a device and deletes its keys. logout: also leave the phone's list first.
// An error means the keys may still be there (the caller must not report it done).
func (b *bridge) drop(ctx context.Context, d *device, logout bool) error {
	b.take(d)
	b.mu.Lock()
	cancel, paired := d.cancel, d.paired
	d.cancel = nil
	b.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	// Its own time: a caller's cancelled request must never leave keys half deleted.
	work, done := context.WithTimeout(context.Background(), 30*time.Second)
	defer done()
	if logout && paired && d.client.Store.ID != nil && d.client.IsConnected() {
		if err := d.client.Logout(work); err == nil { // also deletes the keys
			return nil
		} else {
			log.Printf("link %s: logout failed, deleting keys only: %v", d.link, err)
		}
	}
	d.client.Disconnect()
	if d.client.Store.ID != nil {
		if err := d.client.Store.Delete(work); err != nil && !errors.Is(err, sql.ErrNoRows) {
			return errors.New("deleting keys failed: " + err.Error())
		}
	}
	return nil
}

// deleteKeys: a device's keys, by its full WhatsApp device id, when no client holds it.
func (b *bridge) deleteKeys(jid string) error {
	if jid == "" {
		return nil
	}
	parsed, err := types.ParseJID(jid)
	if err != nil {
		return nil
	}
	work, done := context.WithTimeout(context.Background(), 30*time.Second)
	defer done()
	dev, err := b.container.GetDevice(work, parsed)
	if err != nil {
		return err
	}
	if dev != nil {
		return dev.Delete(work)
	}
	return nil
}
