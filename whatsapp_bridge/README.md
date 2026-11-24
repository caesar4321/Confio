# whatsapp-bridge

Each Confío user's own WhatsApp, linked as one more device with [whatsmeow](https://github.com/tulir/whatsmeow),
on the prod host. Django (`whatsapp_link/`) is its only client.

- **Django → bridge**: HTTP over the Unix socket `/run/whatsapp-bridge/bridge.sock` (mode 0660, group `nginx`):
  `POST /pair`, `POST /send`, `POST /logout`, `GET /link`, `GET /health`. The socket is the authentication.
- **Bridge → Django**: events (`code`, `paired`, `pair_timeout`, `pair_error`, `logged_out`, `banned`,
  `outdated`, `message`) are queued in the bridge's database and POSTed in order to
  `http://127.0.0.1:8000/internal/whatsapp-bridge/events` with `Authorization: Bearer <token>` until Django
  answers 200. Django refuses anything that came through nginx.
- **Keys**: whatsmeow's device store (Signal keys) lives in its own database `whatsapp_bridge` on the encrypted
  RDS instance, with its own role. Django's database user has no access to it.
- **Never**: read receipts, "online" presence, groups, status, a send without an id (one id is sent once).

## Secrets (SSM, eu-central-2)

- `/confio/whatsapp-bridge/dsn` (SecureString): `postgres://whatsapp_bridge:…@<rds>/whatsapp_bridge?sslmode=require`.
  Outside `/confio/secrets/`, which every Django process loads.
- `/confio/secrets/prod/whatsapp-bridge` (SecureString): `{"token": "…"}`, read by both sides.
- `/confio/whatsapp-bridge/proxies` (SecureString, optional): where each country's devices connect from, so a
  LATAM phone's linked device is not seen from a European datacenter. `{"BO": "socks5://USER-…-session-{session}:PASS@host:port" (SOCKS5 only),
  "*": "…"}`; `{session}` becomes a stable id per link (sticky exit IP). A country without an entry connects
  directly. Changing it takes a restart (every device reconnects through its new route).

## Build and deploy

First install (a system user of its own, never in the app's group; the socket unit gives nginx the socket):

    sudo useradd --system --no-create-home --shell /sbin/nologin whatsapp-bridge
    sudo install -d -o root -g root -m 0755 /opt/whatsapp-bridge
    sudo install -m 0644 deploy/whatsapp-bridge.socket deploy/whatsapp-bridge.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now whatsapp-bridge.socket whatsapp-bridge.service

Then, each release:

    cd whatsapp_bridge && GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o whatsapp-bridge .
    scp whatsapp-bridge confio-prod:/tmp/ && ssh confio-prod 'sudo install -o root -g root -m 0755 \
        /tmp/whatsapp-bridge /opt/whatsapp-bridge/whatsapp-bridge && sudo systemctl restart whatsapp-bridge'

Keep whatsmeow current (`go get go.mau.fi/whatsmeow@latest && go mod tidy`): WhatsApp refuses outdated
clients, and the bridge reports it as an `outdated` event (logged as an error in Django).

## Tests

    BRIDGE_TEST_DSN='postgres://postgres@localhost/whatsapp_bridge_test?sslmode=disable' go test ./...
