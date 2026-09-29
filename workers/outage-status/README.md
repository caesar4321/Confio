# confio-outage-status

Signed "is Confío reachable?" status for the emergency exit
(`apps/src/services/emergencyExit/reachability.ts`). It runs on Cloudflare,
independently of Confío's servers, so the app can tell a real outage from a
local block:

| Phone reaches Confío | Worker says | App state |
|---|---|---|
| no | Confío is up (fresh) | `blocked`: same rules as normal (72h wait, then face or a second wait) |
| no | Confío down since T (fresh) | `outage`, measured from T; immediate after 72h |
| no | unreachable / stale / bad signature | `outage`, measured locally (72h) |

"Fresh" means `checkedAt` is within 30 minutes of BSC chain time.

## Deploy

```bash
npm install
npx wrangler kv namespace create STATUS      # paste the id into wrangler.toml
npm run keygen                               # prints the private and public keys
npx wrangler secret put STATUS_SIGNING_KEY   # paste the private key
npm run deploy
curl https://confio-outage-status.<account>.workers.dev/v1/status
```

Then set, in `apps/src/services/emergencyExit/outageStatusConfig.ts`:

- `OUTAGE_STATUS_URLS`: the Worker URL(s) ending in `/v1/status`
- `OUTAGE_STATUS_PUBLIC_KEY_HEX`: the public key from `npm run keygen`

Until both are set the app ignores the Worker and keeps the local 72h rule.

Keep the Worker running after Confío's servers are gone: it is what lets the
exit open immediately (after 72h of confirmed outage) instead of every
user's phone having to observe the outage itself. Rotating the key needs an
app release, since the public key ships in the bundle.
