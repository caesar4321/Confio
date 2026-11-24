package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/lib/pq"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

type httpDoer interface {
	Do(*http.Request) (*http.Response, error)
}

func defaultHTTP() httpDoer { return &http.Client{Timeout: 20 * time.Second} }

func (b *bridge) enqueue(ctx context.Context, link, grant, kind string, data map[string]any) {
	body, _ := json.Marshal(data)
	if _, err := b.db.ExecContext(ctx, `INSERT INTO bridge_event (link, grant_id, kind, data) VALUES ($1, $2, $3, $4)`,
		link, grant, kind, body); err != nil {
		log.Printf("link %s: event %s not queued: %v", link, kind, err)
		return
	}
	select {
	case b.wake <- struct{}{}:
	default:
	}
}

type event struct {
	ID    int64           `json:"id"`
	Link  string          `json:"link"`
	Grant string          `json:"grant"`
	Kind  string          `json:"kind"`
	Data  json.RawMessage `json:"data"`
	At    time.Time       `json:"at"`
}

// deliver sends queued events to Django in order until it answers 200; each delivered batch is deleted.
func (b *bridge) deliver(ctx context.Context) {
	backoff := time.Second
	lastSweep := time.Time{}
	for {
		if time.Since(lastSweep) > time.Hour {
			b.forgetSent(ctx)
			lastSweep = time.Now()
		}
		batch, err := b.pending(ctx, 50)
		if err == nil && len(batch) > 0 {
			started := time.Now()
			err = b.post(ctx, batch)
			if err == nil {
				// Exactly the ids sent: one committed late with a lower id is still waiting, not deleted unseen.
				ids := make([]int64, len(batch))
				for i, e := range batch {
					ids[i] = e.ID
				}
				_, err = b.db.ExecContext(ctx, `DELETE FROM bridge_event WHERE id = ANY($1)`, pq.Array(ids))
				log.Printf("op=deliver events=%d ms=%d", len(batch), time.Since(started).Milliseconds())
				backoff = time.Second
				continue
			}
		}
		if err != nil {
			log.Printf("op=deliver failed: %v (again in %s)", err, backoff)
			if !wait(ctx, backoff) {
				return
			}
			if backoff < 60*time.Second {
				backoff *= 2
			}
			continue
		}
		select {
		case <-ctx.Done():
			return
		case <-b.wake:
		case <-time.After(30 * time.Second):
		}
	}
}

func wait(ctx context.Context, d time.Duration) bool {
	select {
	case <-ctx.Done():
		return false
	case <-time.After(d):
		return true
	}
}

func (b *bridge) pending(ctx context.Context, limit int) ([]event, error) {
	rows, err := b.db.QueryContext(ctx, `SELECT id, link, grant_id, kind, data, created_at FROM bridge_event
		ORDER BY id LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []event
	for rows.Next() {
		var e event
		var data []byte
		if err := rows.Scan(&e.ID, &e.Link, &e.Grant, &e.Kind, &data, &e.At); err != nil {
			return nil, err
		}
		e.Data = data
		out = append(out, e)
	}
	return out, rows.Err()
}

func (b *bridge) post(ctx context.Context, batch []event) error {
	body, _ := json.Marshal(map[string]any{"events": batch})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, b.callback, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+b.token)
	resp, err := b.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("django answered %d", resp.StatusCode)
	}
	return nil
}

// incoming: a new one-to-one message, as Django gets it, or false: from someone to the person, or from the person
// to someone (written on her phone: it tells Django she already answered). Groups, status updates, channels, her
// chat with herself (Confío's note) and anything without text are never passed on.
func incoming(ctx context.Context, nameFn func(types.MessageInfo) string, evt *events.Message, own ...string) (map[string]any, bool) {
	info := evt.Info
	if info.IsGroup || evt.IsEdit || evt.IsViewOnce || info.Chat.Server == types.BroadcastServer ||
		(info.Chat.Server != types.DefaultUserServer && info.Chat.Server != types.HiddenUserServer) {
		return nil, false
	}
	// Her chat with herself (her notes, Confío's note): never, whether WhatsApp names it by her number or her LID.
	if info.IsFromMe && info.Chat.User == info.Sender.User {
		return nil, false
	}
	for _, user := range own {
		if user != "" && info.Chat.User == user {
			return nil, false
		}
	}
	text := textOf(evt.Message)
	if strings.TrimSpace(text) == "" {
		return nil, false
	}
	name := nameFn(info)
	if looksPrivate(name + " " + text) {
		return nil, false // a login code or a password: never written anywhere, not even in this queue
	}
	if runes := []rune(text); len(runes) > 1000 {
		text = string(runes[:1000])
	}
	phone := ""
	if info.Chat.Server == types.DefaultUserServer {
		phone = info.Chat.User
	} else if info.SenderAlt.Server == types.DefaultUserServer {
		phone = info.SenderAlt.User
	}
	// One chat, one id: the phone-number form when WhatsApp gives it, so her messages and the contact's (which may
	// be addressed by LID on one side) are the same conversation.
	chat := info.Chat.ToNonAD()
	if chat.Server == types.HiddenUserServer {
		for _, alt := range []types.JID{info.SenderAlt, info.RecipientAlt} {
			if alt.Server == types.DefaultUserServer && (!info.IsFromMe || alt.User != info.Sender.User) {
				chat = alt.ToNonAD()
				break
			}
		}
	}
	return map[string]any{
		"chat": chat.String(), "name": name, "phone": phone, "text": text,
		"id": string(info.ID), "at": info.Timestamp.Unix(), "from_me": info.IsFromMe,
	}, true
}

func textOf(m *waE2E.Message) string {
	if m == nil {
		return ""
	}
	switch {
	case m.GetConversation() != "":
		return m.GetConversation()
	case m.GetExtendedTextMessage().GetText() != "":
		return m.GetExtendedTextMessage().GetText()
	case m.GetImageMessage().GetCaption() != "":
		return "[foto] " + m.GetImageMessage().GetCaption()
	case m.GetVideoMessage().GetCaption() != "":
		return "[video] " + m.GetVideoMessage().GetCaption()
	case m.GetDocumentMessage().GetCaption() != "":
		return "[documento] " + m.GetDocumentMessage().GetCaption()
	}
	return ""
}

// nameOf: the chat's name as the person saved it, else the sender's own WhatsApp name, else the number.
func nameOf(ctx context.Context, client *whatsmeow.Client, info types.MessageInfo) string {
	for _, jid := range []types.JID{info.Chat, info.SenderAlt} {
		if jid.IsEmpty() {
			continue
		}
		if contact, err := client.Store.Contacts.GetContact(ctx, jid.ToNonAD()); err == nil && contact.Found {
			for _, name := range []string{contact.FullName, contact.FirstName, contact.BusinessName, contact.PushName} {
				if name != "" {
					return name
				}
			}
		}
	}
	if info.PushName != "" && !info.IsFromMe { // on her own message the push name is hers, not the chat's
		return info.PushName
	}
	if info.Chat.Server == types.DefaultUserServer {
		return "+" + info.Chat.User
	}
	return "Contacto"
}

// The same test as Django's service.private: a code, a password or a bank token. Kept in step with it.
var (
	securityWords = regexp.MustCompile(`(?i)c[oó]digo|\bcode\b|c[oó]d\.|\botp\b|\bpin\b|verifica|contrase|password|senha|` +
		`\bclave\b|\btoken\b|din[aá]mica|acceso|one[- ]time|single[- ]use|no lo compartas|no la compartas|no compartas|` +
		`never share|nunca compartas|autentica|2fa|seguridad|sign ?in|log ?in|iniciar sesi|ingres|confirma`)
	codeDigits = regexp.MustCompile(`\d{4,8}|[A-Z0-9]{6,8}`)
	spacing    = regexp.MustCompile(`[\s\p{Z}\-.]`) // \s is ASCII-only in Go: Unicode spaces too
)

func looksPrivate(text string) bool {
	return securityWords.MatchString(text) && codeDigits.MatchString(spacing.ReplaceAllString(text, ""))
}
