package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waAdv"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

func message(info types.MessageInfo, text string) *events.Message {
	return &events.Message{Info: info, Message: &waE2E.Message{Conversation: proto.String(text)}}
}

func person(user string) types.MessageInfo {
	jid := types.NewJID(user, types.DefaultUserServer)
	return types.MessageInfo{
		MessageSource: types.MessageSource{Chat: jid, Sender: jid},
		ID:            "ABC", Timestamp: time.Unix(1700000000, 0), PushName: "Farmacia",
	}
}

func named(types.MessageInfo) string { return "Farmacia Central" }

func TestIncomingPassesOnlyOneToOneTextFromOthers(t *testing.T) {
	ctx := context.Background()
	data, ok := incoming(ctx, named, message(person("59171234567"), "Su pedido está listo"), "")
	if !ok || data["name"] != "Farmacia Central" || data["phone"] != "59171234567" || data["text"] != "Su pedido está listo" ||
		data["chat"] != "59171234567@s.whatsapp.net" {
		t.Fatalf("one-to-one text: %v %v", ok, data)
	}

	mine := person("59171234567")
	mine.IsFromMe = true
	mine.Sender = types.NewJID("59170000009", types.DefaultUserServer) // her: the chat is the other person
	group := person("59171234567")
	group.IsGroup = true
	group.Chat = types.NewJID("1203630", types.GroupServer)
	status := person("59171234567")
	status.Chat = types.StatusBroadcastJID
	channel := person("59171234567")
	channel.Chat = types.NewJID("1203", types.NewsletterServer)
	// Her own message (written on her phone) is passed on, marked: it tells Django she already answered.
	if data, ok := incoming(ctx, named, message(mine, "ya voy"), ""); !ok || data["from_me"] != true {
		t.Fatalf("her own message: %v %v", ok, data)
	}
	// Her chat with herself (Confío's note lives there) never is, by her number or by her LID.
	if _, ok := incoming(ctx, named, message(mine, "nota"), "59171234567"); ok {
		t.Error("her chat with herself passed on")
	}
	self := mine
	self.Chat = types.NewJID("88888", types.HiddenUserServer)
	self.Sender = types.NewJID("88888", types.HiddenUserServer)
	if _, ok := incoming(ctx, named, message(self, "clave del banco"), "59171234567"); ok {
		t.Error("her chat with herself by LID passed on")
	}
	viewOnce := message(person("59171234567"), "solo una vez")
	viewOnce.IsViewOnce = true
	if _, ok := incoming(ctx, named, viewOnce, ""); ok {
		t.Error("a view-once message passed on")
	}
	for name, info := range map[string]types.MessageInfo{"group": group, "status": status, "channel": channel} {
		if _, ok := incoming(ctx, named, message(info, "hola"), ""); ok {
			t.Errorf("%s message passed on", name)
		}
	}
	if _, ok := incoming(ctx, named, &events.Message{Info: person("591"), Message: &waE2E.Message{}}, ""); ok {
		t.Error("a message without text passed on")
	}
	edit := message(person("59171234567"), "editado")
	edit.IsEdit = true
	if _, ok := incoming(ctx, named, edit, ""); ok {
		t.Error("an edit passed on as a new message")
	}
}

func TestIncomingLidChatKeepsThePhoneWhenKnown(t *testing.T) {
	info := person("59171234567")
	info.Chat = types.NewJID("123456789", types.HiddenUserServer)
	info.SenderAlt = types.NewJID("59171234567", types.DefaultUserServer)
	data, ok := incoming(context.Background(), named, message(info, "hola"), "")
	// One chat, one id: the phone-number form, so her messages and the contact's are the same conversation.
	if !ok || data["chat"] != "59171234567@s.whatsapp.net" || data["phone"] != "59171234567" {
		t.Fatalf("lid chat: %v", data)
	}
}

func TestIncomingCutsLongTextOnRunes(t *testing.T) {
	data, _ := incoming(context.Background(), named, message(person("591"), strings.Repeat("ñ", 1500)), "")
	if got := []rune(data["text"].(string)); len(got) != 1000 || string(got[999]) != "ñ" {
		t.Fatalf("cut to %d runes", len(got))
	}
}

func TestTextOfCaptions(t *testing.T) {
	m := &waE2E.Message{ImageMessage: &waE2E.ImageMessage{Caption: proto.String("comprobante")}}
	if textOf(m) != "[foto] comprobante" {
		t.Fatal(textOf(m))
	}
	if textOf(&waE2E.Message{AudioMessage: &waE2E.AudioMessage{}}) != "" {
		t.Fatal("an audio has no text to pass on")
	}
}

func TestMessageIDIsStableAndWhatsAppShaped(t *testing.T) {
	a, b := messageID("draft-1"), messageID("draft-1")
	if a != b || messageID("draft-2") == a || len(a) != 22 || !strings.HasPrefix(string(a), "3EB0") ||
		strings.ToUpper(string(a)) != string(a) {
		t.Fatalf("ids %s %s", a, b)
	}
}

func TestTypingForIsPacedAndBounded(t *testing.T) {
	if typingFor("hola") < time.Second || typingFor(strings.Repeat("a", 5000)) != 8*time.Second {
		t.Fatal("typing pace out of bounds")
	}
}

// ---- with a database (BRIDGE_TEST_DSN, e.g. postgres://postgres@localhost/whatsapp_bridge_test?sslmode=disable)

func testDB(t *testing.T) *sql.DB {
	dsn := os.Getenv("BRIDGE_TEST_DSN")
	if dsn == "" {
		t.Skip("BRIDGE_TEST_DSN not set")
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := migrate(context.Background(), db); err != nil {
		t.Fatal(err)
	}
	for _, table := range []string{"bridge_link", "bridge_event", "bridge_sent"} {
		if _, err := db.Exec("DELETE FROM " + table); err != nil {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() { db.Close() })
	return db
}

func TestSendIsAnsweredFromTheRowForAnIDAlreadyUsed(t *testing.T) {
	db := testDB(t)
	b := newBridge(db, nil, "token", "http://django")
	b.devices["7"] = &device{link: "7", grant: "g", paired: true} // no client: nothing may reach WhatsApp
	if _, err := db.Exec(`INSERT INTO bridge_sent (id, link, state, message_id) VALUES ('d1', '7', 'sent', '3EB0X')`); err != nil {
		t.Fatal(err)
	}
	if got := b.send(context.Background(), sendRequest{Link: "7", Grant: "g", ID: "d1", To: "591", Text: "hola"}); got.Status != "sent" ||
		got.MessageID != "3EB0X" {
		t.Fatalf("sent id: %+v", got)
	}
	// One that was on its way when the process died: never sent again.
	if _, err := db.Exec(`INSERT INTO bridge_sent (id, link, state) VALUES ('d2', '7', 'entering')`); err != nil {
		t.Fatal(err)
	}
	if got := b.send(context.Background(), sendRequest{Link: "7", Grant: "g", ID: "d2", To: "591", Text: "hola"}); got.Status != "unknown" {
		t.Fatalf("entering id: %+v", got)
	}
}

func TestSendRefusesAnotherPairingsWork(t *testing.T) {
	db := testDB(t)
	b := newBridge(db, nil, "token", "http://django")
	b.devices["7"] = &device{link: "7", grant: "new", paired: true}
	got := b.send(context.Background(), sendRequest{Link: "7", Grant: "old", ID: "d1", To: "591", Text: "hola"})
	if got.Status != "not_sent" || got.Error != "not_linked" {
		t.Fatalf("old grant: %+v", got)
	}
	var n int
	_ = db.QueryRow(`SELECT count(*) FROM bridge_sent`).Scan(&n)
	if n != 0 {
		t.Fatal("an id was claimed for a refused send")
	}
}

type fakeDjango struct {
	status int
	got    []map[string]any
	auth   string
}

func (f *fakeDjango) Do(r *http.Request) (*http.Response, error) {
	body, _ := io.ReadAll(r.Body)
	var payload map[string]any
	_ = json.Unmarshal(body, &payload)
	f.got = append(f.got, payload)
	f.auth = r.Header.Get("Authorization")
	return &http.Response{StatusCode: f.status, Body: io.NopCloser(strings.NewReader("{}"))}, nil
}

func TestEventsStayQueuedUntilDjangoTakesThem(t *testing.T) {
	db := testDB(t)
	b := newBridge(db, nil, "secret-token", "http://django/events")
	fake := &fakeDjango{status: http.StatusServiceUnavailable}
	b.http = fake
	ctx := context.Background()
	b.enqueue(ctx, "7", "g", "paired", map[string]any{"phone": "59171234567"})
	b.enqueue(ctx, "7", "g", "message", map[string]any{"text": "hola"})

	batch, _ := b.pending(ctx, 50)
	if err := b.post(ctx, batch); err == nil {
		t.Fatal("a 503 counted as delivered")
	}
	if left, _ := b.pending(ctx, 50); len(left) != 2 {
		t.Fatalf("events lost after a refusal: %d", len(left))
	}
	fake.status = http.StatusOK
	runCtx, cancel := context.WithCancel(ctx)
	done := make(chan struct{})
	go func() { b.deliver(runCtx); close(done) }()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if left, _ := b.pending(ctx, 50); len(left) == 0 {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	cancel()
	<-done
	if left, _ := b.pending(ctx, 50); len(left) != 0 {
		t.Fatal("delivered events not deleted")
	}
	last := fake.got[len(fake.got)-1]["events"].([]any)
	if len(last) != 2 || last[0].(map[string]any)["kind"] != "paired" || fake.auth != "Bearer secret-token" {
		t.Fatalf("delivered %v with %q", last, fake.auth)
	}
}

func TestLogoutFindsTheKeysByTheFullDeviceID(t *testing.T) {
	db := testDB(t)
	ctx := context.Background()
	container := sqlstore.NewWithDB(db, "postgres", nil)
	if err := container.Upgrade(ctx); err != nil {
		t.Fatal(err)
	}
	dev := container.NewDevice()
	jid := types.NewADJID("59171234567", 0, 23) // as PairSuccess gives it: with its :device part
	dev.ID = &jid
	dev.Account = &waAdv.ADVSignedDeviceIdentity{Details: []byte{1}, AccountSignature: make([]byte, 64),
		AccountSignatureKey: make([]byte, 32), DeviceSignature: make([]byte, 64)}
	if err := container.PutDevice(ctx, dev); err != nil {
		t.Fatal(err)
	}
	b := newBridge(db, container, "token", "http://django")
	if _, err := db.Exec(`INSERT INTO bridge_link (link, grant_id, jid, state) VALUES ('7', 'g', $1, 'linked')`, jid.String()); err != nil {
		t.Fatal(err)
	}
	// A logout for an older pairing touches nothing.
	if err := b.logout("7", "older"); err != nil {
		t.Fatal(err)
	}
	if found, _ := container.GetDevice(ctx, jid); found == nil {
		t.Fatal("a stale logout deleted the current pairing's keys")
	}
	// Not in memory (after a restart): the keys are still found and deleted.
	if err := b.logout("7", "g"); err != nil {
		t.Fatal(err)
	}
	if found, _ := container.GetDevice(ctx, jid); found != nil {
		t.Fatal("keys left behind")
	}
	var rows int
	_ = db.QueryRow(`SELECT count(*) FROM bridge_link`).Scan(&rows)
	if rows != 0 {
		t.Fatal("link row left behind")
	}
}

func TestLooksPrivateMatchesDjango(t *testing.T) {
	if !looksPrivate("Banco Unión Tu código de verificación es 482913") {
		t.Fatal("a code passed")
	}
	if looksPrivate("Farmacia Su pedido está listo, son 120 Bs") {
		t.Fatal("an order was taken for a code")
	}
}

func TestProxiesPerCountryAreStickyPerLink(t *testing.T) {
	routes, err := parseProxies(`{"BO": "socks5://u-country-bo-session-{session}:p@gate.example:7000", "*": "socks5://u:p@any.example:8000"}`)
	if err != nil {
		t.Fatal(err)
	}
	bo := routes.For("bo", "7")
	if !strings.HasPrefix(bo, "socks5://u-country-bo-session-") || bo != routes.For("BO", "7") || bo == routes.For("BO", "8") {
		t.Fatalf("sticky per link: %s", bo)
	}
	if strings.Contains(bo, "{session}") || routes.For("MX", "7") != "socks5://u:p@any.example:8000" {
		t.Fatal("fallback or template")
	}
	none, _ := parseProxies("")
	if none.For("BO", "7") != "" {
		t.Fatal("no routes must mean direct")
	}
	lower, err := parseProxies(`{"bo": "socks5://u:p@x:1"}`)
	if err != nil || lower.Key("BO") != "BO" {
		t.Fatal("lowercase keys must match")
	}
	if _, err := parseProxies(`{"Bolivia": "socks5://u:p@x:1"}`); err == nil {
		t.Fatal("a key that is not a country accepted")
	}
	if _, err := parseProxies(`{"BO": "http://u:p@x:1"}`); err == nil {
		t.Fatal("a bad URL accepted")
	}
}

type captureLog struct{ lines *[]string }

func (c captureLog) Warnf(msg string, args ...any) {
	*c.lines = append(*c.lines, fmt.Sprintf(msg, args...))
}
func (c captureLog) Errorf(msg string, args ...any) {}
func (c captureLog) Infof(msg string, args ...any)  {}
func (c captureLog) Debugf(msg string, args ...any) {}
func (c captureLog) Sub(string) waLog.Logger        { return c }

func TestPairingLogKeepsTheShapeNotTheValues(t *testing.T) {
	var lines []string
	l := pairingLog{Logger: captureLog{&lines}}.Sub("Recv")
	l.Debugf("%s", `<notification from="s.whatsapp.net" type="link_code_companion_reg" id="123"><link_code_companion_reg stage="primary_hello" jid="59171234567@s.whatsapp.net"><link_code_pairing_ref>SECRETREF</link_code_pairing_ref></link_code_companion_reg></notification>`)
	l.Debugf("%s", `<message from="59171234567@s.whatsapp.net">hola</message>`)
	if len(lines) != 1 {
		t.Fatalf("lines: %v", lines)
	}
	got := lines[0]
	if strings.Contains(got, "59171234567") || strings.Contains(got, "SECRETREF") || !strings.Contains(got, `stage="primary_hello"`) ||
		!strings.Contains(got, "link_code_pairing_ref") {
		t.Fatalf("logged: %s", got)
	}
}
