package main

import (
	"context"
	"errors"
	"log"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types/events"
)

var (
	errAlreadyLinked = errors.New("already_linked")
	errPhoneInvalid  = errors.New("phone_invalid")
	errWhatsApp      = errors.New("whatsapp")
	errNotLinked     = errors.New("not_linked")
)

// What the person sees in Dispositivos vinculados: "Chrome". WhatsApp only accepts common browser names.
const displayName = "Chrome (Linux)"

// sameNumber: WhatsApp's spelling of a number may differ from the typed one (a 9 or a 1 after the country
// code); the last 8 digits may not.
func sameNumber(signed, typed string) bool {
	return len(signed) >= 8 && len(typed) >= 8 && signed[len(signed)-8:] == typed[len(typed)-8:]
}

// pair starts linking a new device for `link` with a code for `phone` (international digits) and returns the
// first code. Until `seconds` pass, a lapsed code is asked again (sent to Django as a "code" event). A paired
// device stays connected; one never paired is deleted and Django hears "pair_timeout".
func (b *bridge) pair(link, grant, phone, country string, seconds int) (string, error) {
	lock, _ := b.pairing.LoadOrStore(link, &sync.Mutex{})
	lock.(*sync.Mutex).Lock()
	defer lock.(*sync.Mutex).Unlock()

	if old := b.get(link); old != nil {
		b.mu.Lock()
		paired := old.paired
		if !paired {
			old.dropping = true // decided under the lock: a success landing now logs it out (handlePairing)
		}
		b.mu.Unlock()
		if paired {
			return "", errAlreadyLinked
		}
		if err := b.drop(context.Background(), old, false); err != nil {
			log.Printf("link %s: %v", link, err)
		}
	}
	if _, err := b.db.Exec(`INSERT INTO bridge_link (link, grant_id, state, country, route) VALUES ($1, $2, 'pairing', $3, $4)
		ON CONFLICT (link) DO UPDATE SET grant_id = $2, state = 'pairing', jid = '', country = $3, route = $4,
		updated_at = now()`, link, grant, country, b.proxies.Key(country)); err != nil {
		return "", err
	}
	d := &device{link: link, grant: grant, phone: phone, country: country, started: time.Now(),
		until: time.Now().Add(time.Duration(seconds) * time.Second)}
	d.client = whatsmeow.NewClient(b.container.NewDevice(), clientLog())
	// Paired from the same place it will live: the person's country, from the first socket on.
	if err := b.route(d); err != nil {
		log.Printf("link %s: %v", link, err)
		_, _ = b.db.Exec(`DELETE FROM bridge_link WHERE link = $1 AND grant_id = $2`, link, grant)
		return "", errWhatsApp
	}
	// whatsmeow reconnects by itself only a device with an id (a paired one): while pairing, askCode alone opens
	// the socket, and once paired the reconnects keep the link alive.
	ctx, cancel := context.WithDeadline(context.Background(), d.until)
	d.cancel = cancel
	d.client.AddEventHandler(func(evt any) { b.handlePairing(d, evt) })
	b.mu.Lock()
	b.devices[link] = d
	b.mu.Unlock()

	code, err := b.askCode(ctx, d, true)
	if err != nil {
		if dropErr := b.drop(context.Background(), d, false); dropErr != nil {
			log.Printf("link %s: %v", link, dropErr)
		}
		_, _ = b.db.Exec(`DELETE FROM bridge_link WHERE link = $1 AND grant_id = $2`, link, grant)
		return "", err
	}
	return code, nil
}

// askCode opens the login socket and asks WhatsApp for a code; when the socket's codes run out (about 160 s),
// watchCodes asks again while the pairing lasts.
func (b *bridge) askCode(ctx context.Context, d *device, push bool) (string, error) {
	var qr <-chan whatsmeow.QRChannelItem
	var err error
	for attempt := 0; attempt < 2; attempt++ {
		// whatsmeow sends its timeout before it disconnects: wait for the old socket to close.
		for wait := 0; wait < 40 && d.client.IsConnected(); wait++ {
			time.Sleep(250 * time.Millisecond)
		}
		if qr, err = d.client.GetQRChannel(ctx); err == nil {
			if err = d.client.Connect(); err == nil {
				break
			}
		}
		d.client.Disconnect()
	}
	if err != nil {
		log.Printf("link %s: login socket not opened: %v", d.link, err)
		return "", errWhatsApp
	}
	// The socket is ready once the first QR arrives (the QR itself is never used: code pairing only).
	select {
	case item, ok := <-qr:
		if !ok || item.Event != whatsmeow.QRChannelEventCode {
			return "", errWhatsApp
		}
	case <-time.After(20 * time.Second):
		return "", errWhatsApp
	case <-ctx.Done():
		return "", errWhatsApp
	}
	code, err := d.client.PairPhone(ctx, d.phone, push, whatsmeow.PairClientChrome, displayName)
	if err != nil {
		if errors.Is(err, whatsmeow.ErrPhoneNumberTooShort) || errors.Is(err, whatsmeow.ErrPhoneNumberIsNotInternational) {
			return "", errPhoneInvalid
		}
		log.Printf("link %s: pair code refused: %v", d.link, err)
		return "", errWhatsApp
	}
	go b.watchCodes(ctx, d, qr)
	return code, nil
}

func (b *bridge) watchCodes(ctx context.Context, d *device, qr <-chan whatsmeow.QRChannelItem) {
	for item := range qr {
		switch {
		case item == whatsmeow.QRChannelSuccess:
			return
		case item == whatsmeow.QRChannelTimeout:
			b.mu.Lock()
			current, paired := b.devices[d.link] == d && !d.dropping, d.paired
			b.mu.Unlock()
			if !current || paired || time.Now().After(d.until.Add(-20*time.Second)) {
				return // expirePairings ends it
			}
			// No second push to the phone: the person already has WhatsApp open on the code screen.
			code, err := b.askCode(ctx, d, false)
			if err != nil {
				log.Printf("link %s: asking a new code failed: %v", d.link, err)
				return
			}
			b.enqueue(context.Background(), d.link, d.grant, "code", map[string]any{"code": code})
			return // the new socket has its own watcher
		case item.Event == whatsmeow.QRChannelEventError:
			log.Printf("link %s: pairing error: %v", d.link, item.Error)
		}
	}
}

func (b *bridge) handlePairing(d *device, raw any) {
	ctx := context.Background()
	switch evt := raw.(type) {
	case *events.PairSuccess:
		mismatch := !sameNumber(evt.ID.User, d.phone)
		b.mu.Lock()
		going := d.dropping
		d.paired = true
		d.refused = going || mismatch // nothing is passed on or sent from it, from this instant
		cancel := d.cancel
		d.cancel = nil
		b.mu.Unlock()
		// The login channel closed with the success; only then is its context released.
		go func() {
			time.Sleep(10 * time.Second)
			if cancel != nil {
				cancel()
			}
		}()
		if !going {
			// Django checks the number again: with another number it shows "not your number"; a pairing being
			// dropped (replaced or expired) is told by its own end, never as linked.
			b.enqueue(ctx, d.link, d.grant, "paired", map[string]any{"phone": evt.ID.User})
		}
		if going || mismatch {
			// Replaced or expired meanwhile, or a number other than the typed one: off the phone at once,
			// without waiting for Django (fail closed).
			log.Printf("op=paired link=%s result=refused (dropping=%v)", d.link, going)
			go func() {
				// The device reconnects after the pairing (the 515 restart); logging out needs that socket.
				for wait := 0; wait < 80 && !d.client.IsLoggedIn(); wait++ {
					time.Sleep(250 * time.Millisecond)
				}
				if err := b.drop(context.Background(), d, true); err != nil {
					log.Printf("link %s: %v", d.link, err)
				}
				_, _ = b.db.Exec(`DELETE FROM bridge_link WHERE link = $1 AND grant_id = $2`, d.link, d.grant)
			}()
			return
		}
		// The full device id (with its :device part): it is how the keys are found again.
		if _, err := b.db.Exec(`UPDATE bridge_link SET state = 'linked', jid = $3, updated_at = now()
			WHERE link = $1 AND grant_id = $2`, d.link, d.grant, evt.ID.String()); err != nil {
			log.Printf("link %s: saving the link failed: %v", d.link, err)
		}
		log.Printf("op=paired link=%s after=%s", d.link, time.Since(d.started).Round(time.Second))
	case *events.PairError:
		log.Printf("link %s: pair error: %v", d.link, evt.Error)
		b.enqueue(ctx, d.link, d.grant, "pair_error", map[string]any{})
	default:
		b.handle(d, raw)
	}
}

// expirePairings ends pairings whose time is over without a link.
func (b *bridge) expirePairings(ctx context.Context) {
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		var over []*device
		b.mu.Lock()
		for _, d := range b.devices {
			// Decided and claimed under the lock: a success landing after this logs the device out.
			if !d.paired && !d.dropping && time.Now().After(d.until) {
				d.dropping = true
				over = append(over, d)
			}
		}
		b.mu.Unlock()
		for _, d := range over {
			if err := b.drop(ctx, d, false); err != nil {
				log.Printf("link %s: %v", d.link, err)
			}
			b.ended(ctx, d.link, d.grant, "pair_timeout")
		}
	}
}
