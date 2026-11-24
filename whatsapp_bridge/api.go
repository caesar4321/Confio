package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"time"
)

// routes: Django's calls, over the Unix socket. Each logs its operation and duration, never a number or text.
func (b *bridge) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		reply(w, http.StatusOK, map[string]any{"ok": true, "devices": b.count()})
	})
	mux.HandleFunc("POST /pair", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Link    string `json:"link"`
			Grant   string `json:"grant"`
			Phone   string `json:"phone"`
			Country string `json:"country"` // ISO, for the proxy route
			Seconds int    `json:"seconds"`
		}
		if !decode(w, r, &req) || req.Link == "" || req.Grant == "" {
			return
		}
		if req.Seconds <= 0 || req.Seconds > 900 {
			req.Seconds = 600
		}
		started := time.Now()
		code, err := b.pair(req.Link, req.Grant, strings.TrimLeft(req.Phone, "+"), strings.ToUpper(req.Country), req.Seconds)
		log.Printf("op=pair link=%s country=%s proxied=%v ms=%d result=%s", req.Link, req.Country,
			b.proxies.For(req.Country, req.Link) != "", time.Since(started).Milliseconds(), outcome(err))
		if err != nil {
			reply(w, http.StatusConflict, map[string]any{"error": err.Error()})
			return
		}
		reply(w, http.StatusOK, map[string]any{"code": code})
	})
	mux.HandleFunc("POST /send", func(w http.ResponseWriter, r *http.Request) {
		var req sendRequest
		if !decode(w, r, &req) {
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 100*time.Second)
		defer cancel()
		reply(w, http.StatusOK, b.send(ctx, req))
	})
	mux.HandleFunc("POST /logout", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Link  string `json:"link"`
			Grant string `json:"grant"` // only that pairing's device; empty: whatever the link holds (unlink)
		}
		if !decode(w, r, &req) || req.Link == "" {
			return
		}
		started := time.Now()
		err := b.logout(req.Link, req.Grant)
		log.Printf("op=logout link=%s ms=%d result=%s", req.Link, time.Since(started).Milliseconds(), outcome(err))
		if err != nil {
			reply(w, http.StatusInternalServerError, map[string]any{"error": "whatsapp"}) // Django tries again
			return
		}
		reply(w, http.StatusOK, map[string]any{"ok": true})
	})
	mux.HandleFunc("GET /link", func(w http.ResponseWriter, r *http.Request) {
		d := b.get(r.URL.Query().Get("link"))
		if d == nil {
			reply(w, http.StatusOK, map[string]any{"state": "none"})
			return
		}
		b.mu.Lock()
		paired := d.paired
		b.mu.Unlock()
		state := "pairing"
		if paired {
			state = "linked"
		}
		reply(w, http.StatusOK, map[string]any{"state": state, "grant": d.grant, "connected": d.client.IsConnected()})
	})
	return mux
}

// logout: off the person's phone (Dispositivos vinculados) and its keys deleted; a link not connected now
// still has its keys deleted, and the phone drops the device on its own later. With a grant, only that
// pairing's device and rows: a late logout for an earlier pairing never touches a newer one. An error means the
// keys may still be there.
func (b *bridge) logout(link, grant string) error {
	work, done := context.WithTimeout(context.Background(), 30*time.Second)
	defer done()
	if d := b.get(link); d != nil && (grant == "" || d.grant == grant) {
		if err := b.drop(work, d, true); err != nil {
			return err
		}
	}
	rows, err := b.db.QueryContext(work, `SELECT jid FROM bridge_link WHERE link = $1 AND ($2 = '' OR grant_id = $2)`,
		link, grant)
	if err != nil {
		return err
	}
	var jids []string
	for rows.Next() {
		var jid string
		if err := rows.Scan(&jid); err == nil {
			jids = append(jids, jid)
		}
	}
	rows.Close()
	for _, jid := range jids {
		if err := b.deleteKeys(jid); err != nil {
			return err
		}
	}
	if _, err := b.db.ExecContext(work, `DELETE FROM bridge_link WHERE link = $1 AND ($2 = '' OR grant_id = $2)`,
		link, grant); err != nil {
		return err
	}
	// Nothing of it is delivered later.
	_, err = b.db.ExecContext(work, `DELETE FROM bridge_event WHERE link = $1 AND ($2 = '' OR grant_id = $2)`, link, grant)
	return err
}

func outcome(err error) string {
	if err == nil {
		return "ok"
	}
	return err.Error()
}

func decode(w http.ResponseWriter, r *http.Request, into any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 64<<10)
	if err := json.NewDecoder(r.Body).Decode(into); err != nil {
		reply(w, http.StatusBadRequest, map[string]any{"error": "bad_request"})
		return false
	}
	return true
}

func reply(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
