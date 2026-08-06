# Solana sponsored transactions

Confío sponsors Solana fees by making its native AWS KMS Ed25519 account the
transaction fee payer. The user still signs every user-authorized instruction;
the server only fills fee-payer signature slot zero after validating the exact
immutable transaction message.

## Client/server protocol

1. The server calls `SolanaSponsorService.prepare()` and returns the sponsor
   address, recent blockhash, last valid block height, and fee cap.
2. The client compiles one atomic legacy or v0 transaction with the sponsor as
   fee payer. Product-specific code owns instruction/Jupiter compilation. The
   shared `signSolanaTransactionForSponsorship()` helper verifies the prepared
   sponsor and blockhash, signs the active user's required slot, verifies any
   other co-signers, and leaves sponsor slot zero empty.
3. The generic `sponsorSolanaTransaction` mutation binds the transaction to
   the JWT account's registered `solana_address` and calls `sponsor_and_send()`.
4. The relay validates user signatures and policy, checks blockhash freshness,
   the authoritative RPC fee, and the sponsor balance floor, signs inside KMS,
   simulates with signature verification enabled, atomically reserves the fee
   against per-account and global UTC-day budgets, then broadcasts. The message
   hash is the durable idempotency and audit key.

Address lookup tables are deliberately rejected in v1. Supporting them safely
requires resolving and pinning every table before program/account policy is
evaluated.

## Mandatory policy boundary

Normal transactions are generally sponsorable: when an instruction does not
receive account zero, it cannot access or debit the sponsor. An optional
program allowlist can narrow this further, while authentication, user-signature
binding, fee caps, simulation, cooldowns, and rate limits apply universally.

Only sponsor-aware instructions need product-specific policy. Their registry
validates exact instruction discriminators, account positions, mints, PDAs,
amount caps, and recipients before granting access to account zero.

By default no instruction may reference account zero (the sponsor). Solana
makes the fee payer writable and a signer; permitting an arbitrary instruction
to use it would allow a crafted System Program instruction to spend sponsor SOL
instead of only the bounded network fee.

The cUSD+ `deposit_and_mint` instruction deliberately requires the registered
issuance sponsor to co-sign. Its flow may set
`allow_sponsor_account_reference=True`, but the shared layer refuses that flag
unless a `policy_hook` is also present. That hook must accept only the exact
cUSD+ instruction discriminator and fixed sponsor account position, in
addition to validating all deposit accounts, mints, amounts, and recipients.

Production enablement requires Redis or Memcached, whose add/increment
operations are atomic across workers. The mutation fails closed on local,
file, dummy, and Django database caches. Database rows remain the monetary
authority: each transaction reserves its quoted fee under both an account
daily budget and a relay-wide daily circuit breaker before KMS signs or an RPC
sees broadcastable wire bytes. The derived transaction signature is stored
before simulation/broadcast; retries return a terminal sent result or reconcile
an unknown result without downgrading a sent row. A singleton row serializes
reservations across UTC budget rollovers; the floor subtracts every unresolved
ledger liability from the observed balance. Confirmed transactions and expired
blockhashes are reconciled to terminal states, while daily abuse spend remains
consumed even when an unbroadcast liability is safely released. A confirmed
signature remains a liability until a later sponsor-balance response reports
an equal or newer context slot, preventing lagging RPC nodes from releasing the
fee twice.

## Address registration

The server never accepts a bare public key as the wallet anchor. The client
requests a short-lived, server-signed challenge bound to the JWT account and
proposed address, signs it with the derived Solana key, and submits the detached
signature. Registration locks the Account row before its immutable first-write
check, preventing concurrent first registrations from replacing each other.

## KMS configuration

Create a customer-managed asymmetric key with:

- `KeySpec=ECC_NIST_EDWARDS25519`
- `KeyUsage=SIGN_VERIFY`
- signing algorithm `ED25519_SHA_512`
- raw-message signing (`MessageType=RAW`)

Set the variables documented in `.env.example`. Leave
`SOLANA_SPONSOR_ENABLED=false` until the KMS key, RPC, shared cache, database
budgets, and registered address flow are configured. An empty
`SOLANA_SPONSOR_ALLOWED_PROGRAM_IDS`
means ordinary programs are unrestricted; sponsor-account access remains
closed unless its exact registry policy is configured.

The Boto3 pin must retain a KMS service model that knows the Ed25519 key and
signing enums. The private sponsor key never leaves KMS.
