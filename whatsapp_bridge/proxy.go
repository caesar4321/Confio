package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strings"
)

// proxies: where each country's WhatsApp connects from, so a Bolivian phone's linked device is seen from Bolivia
// and not from a European datacenter (a ban signal). One URL template per ISO country, and optionally "*" for
// the rest, from the parameter store (/confio/whatsapp-bridge/proxies), e.g.
//
//	{"BO": "socks5://USER-country-bo-session-{session}:PASS@gate.example.com:7000"}
//
// {session} becomes a stable id per link, so a provider's sticky session keeps the person on one exit IP. A
// country with no entry (and no "*") connects directly from this host. A linked device never falls back to
// another route when its proxy fails: it waits and tries again (a different country would be its own signal).
type proxies map[string]string

func parseProxies(raw string) (proxies, error) {
	out := proxies{}
	if strings.TrimSpace(raw) == "" {
		return out, nil
	}
	var given map[string]string
	if err := json.Unmarshal([]byte(raw), &given); err != nil {
		return nil, errors.New("proxies parameter is not a {country: url} JSON object")
	}
	for key, template := range given {
		country := strings.ToUpper(strings.TrimSpace(key))
		if country != "*" && (len(country) != 2 || strings.Trim(country, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") != "") {
			return nil, fmt.Errorf("proxy key %q is not a two-letter country or *", key)
		}
		out[country] = template
		parsed, err := url.Parse(strings.ReplaceAll(template, "{session}", "x"))
		// SOCKS5 only: its dialer is what lets every byte be counted (traffic.go) whatever the route.
		if err != nil || parsed.Scheme != "socks5" || parsed.Host == "" {
			return nil, fmt.Errorf("proxy for %s is not a socks5:// URL", country)
		}
	}
	return out, nil
}

// sessionKey: a secret (the bridge token) so a provider cannot map a session id back to a link id.
var sessionKey = []byte("set-at-start")

// sessionID: stable for a link (so its exit IP stays).
func sessionID(link string) string {
	mac := hmac.New(sha256.New, sessionKey)
	mac.Write([]byte("confio-whatsapp-proxy:" + link))
	return hex.EncodeToString(mac.Sum(nil))[:16]
}

// Key is the route a country takes: its own entry, "*", or "" (direct).
func (p proxies) Key(country string) string {
	country = strings.ToUpper(country)
	if p[country] != "" {
		return country
	}
	if p["*"] != "" {
		return "*"
	}
	return ""
}

// For returns the proxy URL for a link in a country, or "" to connect directly.
func (p proxies) For(country, link string) string {
	key := p.Key(country)
	if key == "" {
		return ""
	}
	return strings.ReplaceAll(p[key], "{session}", sessionID(link))
}

// Countries: which have a route, for the startup log (never the URLs: they hold the provider's password).
func (p proxies) Countries() []string {
	out := make([]string, 0, len(p))
	for country := range p {
		out = append(out, country)
	}
	return out
}
