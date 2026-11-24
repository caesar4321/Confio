// Command whatsapp-bridge keeps each Confío user's own WhatsApp linked as one more device (whatsmeow), on the
// prod host, in place of a cloud browser.
//
// Django drives it over a Unix socket (only the app's group may open it): pair, send, logout. What WhatsApp
// sends back (a link made, a device removed, a new message) is queued in this service's own database and
// delivered to Django's internal endpoint until it answers 200, so nothing is lost across restarts.
//
// What it never does: mark a chat read, show the person "online", send anything Django did not ask for with
// an id (one id is sent once), or keep a message after Django took it.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/aws/aws-sdk-go-v2/service/ssm/types"
	_ "github.com/lib/pq"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

type secrets struct {
	DSN     string `json:"-"`
	Token   string `json:"token"`
	Proxies string `json:"-"`
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

// loadSecrets: the database and the token Django checks, from the parameter store (prod) or the environment
// (a developer's machine). Never from a file in the repository. The database lives under its own path, outside
// /confio/secrets/ (which every Django process loads): only this service reads the keys' database.
func loadSecrets(ctx context.Context) (secrets, error) {
	if dsn := os.Getenv("BRIDGE_DSN"); dsn != "" {
		return secrets{DSN: dsn, Token: os.Getenv("BRIDGE_TOKEN"), Proxies: os.Getenv("BRIDGE_PROXIES")}, nil
	}
	cfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(env("BRIDGE_AWS_REGION", "eu-central-2")))
	if err != nil {
		return secrets{}, err
	}
	client := ssm.NewFromConfig(cfg)
	read := func(name string) (string, error) {
		out, err := client.GetParameter(ctx, &ssm.GetParameterInput{Name: aws.String(name), WithDecryption: aws.Bool(true)})
		if err != nil {
			return "", err
		}
		return aws.ToString(out.Parameter.Value), nil
	}
	dsn, err := read(env("BRIDGE_SSM_DSN", "/confio/whatsapp-bridge/dsn"))
	if err != nil {
		return secrets{}, err
	}
	raw, err := read(env("BRIDGE_SSM_TOKEN", "/confio/secrets/prod/whatsapp-bridge"))
	if err != nil {
		return secrets{}, err
	}
	var value secrets
	if err := json.Unmarshal([]byte(raw), &value); err != nil || value.Token == "" {
		return secrets{}, errors.New("token parameter is not {\"token\": ...} JSON")
	}
	// Optional: without it every country connects directly from this host.
	routes, err := read(env("BRIDGE_SSM_PROXIES", "/confio/whatsapp-bridge/proxies"))
	var missing *types.ParameterNotFound
	if err != nil && !errors.As(err, &missing) {
		return secrets{}, err
	}
	return secrets{DSN: dsn, Token: value.Token, Proxies: routes}, nil
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	log.SetFlags(log.LstdFlags | log.LUTC)

	sec, err := loadSecrets(ctx)
	if err != nil || sec.DSN == "" || sec.Token == "" {
		log.Fatalf("secrets: %v", err)
	}
	db, err := sql.Open("postgres", sec.DSN)
	if err != nil {
		log.Fatalf("database: %v", err)
	}
	db.SetMaxOpenConns(8)
	if err := migrate(ctx, db); err != nil {
		log.Fatalf("migrate: %v", err)
	}
	// whatsmeow's own logs stay at WARN: below that they can carry numbers and message details.
	container := sqlstore.NewWithDB(db, "postgres", waLog.Stdout("store", "WARN", false))
	if err := container.Upgrade(ctx); err != nil {
		log.Fatalf("store: %v", err)
	}
	// What the person sees in Dispositivos vinculados when it is linked by code: "Chrome".
	store.DeviceProps.Os = proto.String("Confío")
	// Only new messages are used: ask WhatsApp for as little history as it allows (and it is never downloaded).
	if sync := store.DeviceProps.HistorySyncConfig; sync != nil {
		sync.FullSyncDaysLimit, sync.FullSyncSizeMbLimit = proto.Uint32(1), proto.Uint32(1)
		sync.RecentSyncDaysLimit, sync.StorageQuotaMb = proto.Uint32(1), proto.Uint32(1)
	}

	routes, err := parseProxies(sec.Proxies)
	if err != nil {
		log.Fatalf("proxies: %v", err)
	}
	log.Printf("proxy routes for: %v", routes.Countries())
	b := newBridge(db, container, sec.Token, env("BRIDGE_CALLBACK", "http://127.0.0.1:8000/internal/whatsapp-bridge/events"))
	b.proxies = routes
	sessionKey = []byte(sec.Token)
	if err := b.restore(ctx); err != nil {
		log.Fatalf("restore: %v", err)
	}
	go b.deliver(ctx)
	go b.expirePairings(ctx)
	go b.reportTraffic(ctx)

	listener, path, err := listen()
	if err != nil {
		log.Fatalf("listen: %v", err)
	}
	server := &http.Server{Handler: b.routes(), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
		b.closeAll()
	}()
	log.Printf("whatsapp-bridge listening on %s with %d linked devices", path, b.count())
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatalf("serve: %v", err)
	}
}

// listen: the socket systemd made (whatsapp-bridge.socket: group nginx, 0660), so this process needs no
// membership in the app's group (it would read the app's files); else one of its own (a developer's machine).
// The socket is the whole authentication of Django's calls.
func listen() (net.Listener, string, error) {
	if os.Getenv("LISTEN_FDS") == "1" && os.Getenv("LISTEN_PID") == strconv.Itoa(os.Getpid()) {
		listener, err := net.FileListener(os.NewFile(3, "systemd-socket"))
		return listener, "systemd socket", err
	}
	path := env("BRIDGE_SOCKET", "/run/whatsapp-bridge/bridge.sock")
	_ = os.Remove(path)
	listener, err := net.Listen("unix", path)
	if err != nil {
		return nil, path, err
	}
	return listener, path, os.Chmod(path, 0o660)
}

func migrate(ctx context.Context, db *sql.DB) error {
	statements := []string{
		// Which device is whose. link: Django's WhatsAppLink id; grant: its pairing, so older work is ignored.
		`CREATE TABLE IF NOT EXISTS bridge_link (
			link TEXT PRIMARY KEY, grant_id TEXT NOT NULL, jid TEXT NOT NULL DEFAULT '',
			state TEXT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`,
		// Waiting for Django to take it. Deleted once Django answered 200.
		`CREATE TABLE IF NOT EXISTS bridge_event (
			id BIGSERIAL PRIMARY KEY, link TEXT NOT NULL, grant_id TEXT NOT NULL, kind TEXT NOT NULL,
			data JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())`,
		// The number's country: which proxy route the device connects through, also after a restart.
		`ALTER TABLE bridge_link ADD COLUMN IF NOT EXISTS country TEXT NOT NULL DEFAULT ''`,
		// The route it was linked through ("" direct, "*", or a country): one that no longer resolves is never
		// silently taken direct.
		`ALTER TABLE bridge_link ADD COLUMN IF NOT EXISTS route TEXT NOT NULL DEFAULT ''`,
		// One row per send id: a retried request never sends again. Kept for a week.
		`CREATE TABLE IF NOT EXISTS bridge_sent (
			id TEXT PRIMARY KEY, link TEXT NOT NULL, state TEXT NOT NULL, message_id TEXT NOT NULL DEFAULT '',
			created_at TIMESTAMPTZ NOT NULL DEFAULT now())`,
	}
	for _, statement := range statements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("%.60s: %w", strings.Join(strings.Fields(statement), " "), err)
		}
	}
	return nil
}
