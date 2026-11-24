package main

import (
	"fmt"
	"regexp"
	"strings"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// pairingLog: the client log of a device while it pairs. Like clientLog (WARN), plus the shape of the pairing
// stanzas WhatsApp sends (link code and passkey steps): tag and attribute names, with values and contents
// removed except a few protocol words. It tells why a pairing failed without logging a number or a key.
type pairingLog struct {
	waLog.Logger
	recv bool
}

func newPairingLog() waLog.Logger { return pairingLog{Logger: clientLog()} }

func (l pairingLog) Sub(module string) waLog.Logger {
	return pairingLog{Logger: l.Logger.Sub(module), recv: module == "Recv"}
}

var (
	pairingStanza = regexp.MustCompile(`link_code_companion_reg|passkey`)
	attrValue     = regexp.MustCompile(`(\w+)="([^"]*)"`)
	nodeContent   = regexp.MustCompile(`>[^<]+<`)
	keptAttrs     = map[string]bool{"type": true, "stage": true, "xmlns": true, "should_show_push_notification": true}
)

func (l pairingLog) Debugf(msg string, args ...any) {
	if !l.recv {
		return
	}
	line := fmt.Sprintf(msg, args...)
	if !pairingStanza.MatchString(line) {
		return
	}
	line = attrValue.ReplaceAllStringFunc(line, func(attr string) string {
		parts := attrValue.FindStringSubmatch(attr)
		if keptAttrs[parts[1]] {
			return attr
		}
		return fmt.Sprintf(`%s="(%d)"`, parts[1], len(parts[2]))
	})
	line = nodeContent.ReplaceAllString(line, "><")
	if len(line) > 1500 {
		line = line[:1500]
	}
	l.Logger.Warnf("pairing stanza: %s", strings.Join(strings.Fields(line), " "))
}
