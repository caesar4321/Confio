package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"log"
	"strings"
	"time"
	"unicode/utf8"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"google.golang.org/protobuf/proto"
)

var errNotOnWhatsApp = errors.New("number_not_on_whatsapp")

type sendRequest struct {
	Link  string `json:"link"`
	Grant string `json:"grant"`
	ID    string `json:"id"`   // Django's id for this message: sent once, whatever the retries
	To    string `json:"to"`   // a chat id from a message ("…@s.whatsapp.net", "…@lid") or international digits
	Self  bool   `json:"self"` // the person's own chat ("Mensaje para ti")
	Text  string `json:"text"`
}

type sendResult struct {
	// sent: WhatsApp's server took it. not_sent: nothing left, it may be tried again.
	// unknown: it may have left; never sent again under this id.
	Status    string `json:"status"`
	MessageID string `json:"message_id,omitempty"`
	Error     string `json:"error,omitempty"`
}

// messageID: the same Django id always gives the same WhatsApp id (WhatsApp's own format: 3EB0 + 18 hex).
func messageID(id string) types.MessageID {
	sum := sha256.Sum256([]byte("confio-whatsapp-send:" + id))
	return types.MessageID("3EB0" + strings.ToUpper(hex.EncodeToString(sum[:]))[:18])
}

// typingFor: a person's pace, as long as the text would take to type, a little, within limits.
func typingFor(text string) time.Duration {
	seconds := 1.5 + float64(utf8.RuneCountInString(text))/25.0
	if seconds > 8 {
		seconds = 8
	}
	return time.Duration(seconds * float64(time.Second))
}

var sleep = time.Sleep

func (b *bridge) send(ctx context.Context, req sendRequest) sendResult {
	d := b.get(req.Link)
	if d == nil || d.grant != req.Grant {
		return sendResult{Status: "not_sent", Error: errNotLinked.Error()}
	}
	b.mu.Lock()
	paired := d.paired && !d.refused && !d.dropping
	b.mu.Unlock()
	if !paired || strings.TrimSpace(req.Text) == "" || req.ID == "" {
		return sendResult{Status: "not_sent", Error: errNotLinked.Error()}
	}
	d.sendMu.Lock()
	defer d.sendMu.Unlock()

	// Claimed before anything leaves: a second request with this id answers from the row, never sends.
	claimed, err := b.db.ExecContext(ctx, `INSERT INTO bridge_sent (id, link, state) VALUES ($1, $2, 'sending')
		ON CONFLICT (id) DO NOTHING`, req.ID, req.Link)
	if err != nil {
		return sendResult{Status: "not_sent", Error: "whatsapp"}
	}
	if n, _ := claimed.RowsAffected(); n == 0 {
		var state, sentID string
		if err := b.db.QueryRowContext(ctx, `SELECT state, message_id FROM bridge_sent WHERE id = $1`, req.ID).Scan(
			&state, &sentID); err != nil && !errors.Is(err, sql.ErrNoRows) {
			return sendResult{Status: "unknown"}
		}
		if state == "sent" {
			return sendResult{Status: "sent", MessageID: sentID}
		}
		return sendResult{Status: "unknown"} // another request with this id was sending: never twice
	}
	release := func(code string) sendResult {
		// Nothing left: the id may be used again.
		_, _ = b.db.ExecContext(context.Background(), `DELETE FROM bridge_sent WHERE id = $1 AND state = 'sending'`, req.ID)
		return sendResult{Status: "not_sent", Error: code}
	}

	// Right after a restart the device may still be connecting.
	for wait := 0; wait < 20 && !(d.client.IsConnected() && d.client.IsLoggedIn()); wait++ {
		sleep(500 * time.Millisecond)
	}
	if !d.client.IsConnected() || !d.client.IsLoggedIn() {
		return release("whatsapp")
	}
	to, err := b.recipient(ctx, d.client, req)
	if err != nil {
		return release(err.Error())
	}
	started := time.Now()
	_ = d.client.SendChatPresence(ctx, to, types.ChatPresenceComposing, types.ChatPresenceMediaText)
	sleep(typingFor(req.Text))
	_ = d.client.SendChatPresence(ctx, to, types.ChatPresencePaused, types.ChatPresenceMediaText)
	if !d.client.IsConnected() {
		return release("whatsapp")
	}
	// From here it may leave: a failure is "unknown", kept so this id is never sent again.
	_, _ = b.db.ExecContext(ctx, `UPDATE bridge_sent SET state = 'entering' WHERE id = $1`, req.ID)
	resp, err := d.client.SendMessage(ctx, to, &waE2E.Message{Conversation: proto.String(req.Text)},
		whatsmeow.SendRequestExtra{ID: messageID(req.ID)})
	if err != nil {
		_, _ = b.db.ExecContext(context.Background(), `UPDATE bridge_sent SET state = 'unknown' WHERE id = $1`, req.ID)
		log.Printf("op=send link=%s ms=%d result=unknown err=%T", req.Link, time.Since(started).Milliseconds(), err)
		return sendResult{Status: "unknown"}
	}
	_, _ = b.db.ExecContext(context.Background(), `UPDATE bridge_sent SET state = 'sent', message_id = $2 WHERE id = $1`,
		req.ID, string(resp.ID))
	log.Printf("op=send link=%s ms=%d result=sent", req.Link, time.Since(started).Milliseconds())
	return sendResult{Status: "sent", MessageID: string(resp.ID)}
}

func (b *bridge) recipient(ctx context.Context, client *whatsmeow.Client, req sendRequest) (types.JID, error) {
	if req.Self {
		if client.Store.ID == nil {
			return types.EmptyJID, errNotLinked
		}
		return client.Store.ID.ToNonAD(), nil
	}
	if strings.Contains(req.To, "@") {
		jid, err := types.ParseJID(req.To)
		if err != nil || (jid.Server != types.DefaultUserServer && jid.Server != types.HiddenUserServer) {
			return types.EmptyJID, errWhatsApp // only one-to-one chats
		}
		return jid.ToNonAD(), nil
	}
	digits := strings.TrimLeft(req.To, "+")
	if len(digits) < 8 || strings.Trim(digits, "0123456789") != "" {
		return types.EmptyJID, errPhoneInvalid
	}
	found, err := client.IsOnWhatsApp(ctx, []string{"+" + digits})
	if err != nil {
		return types.EmptyJID, errWhatsApp
	}
	for _, item := range found {
		if item.IsIn {
			return item.JID, nil
		}
	}
	return types.EmptyJID, errNotOnWhatsApp
}

// forgetSent: ids older than a week (Django forgets its drafts long before).
func (b *bridge) forgetSent(ctx context.Context) {
	_, _ = b.db.ExecContext(ctx, `DELETE FROM bridge_sent WHERE created_at < now() - interval '7 days'`)
}
