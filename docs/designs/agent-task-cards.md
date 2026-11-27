# Agent task cards: one general card, filled by the server

**Status:** decided B (Julian, 2026-11-27). Built: the server composes `agentTaskCard` (agent_tasks/cards.py) for
orders, subscribe, requests (manage and bookings), steps and Sí, avísame; one mutation `answerAgentCard`. The app's
`TaskCard` draws it in place of those older branches; products, sign-in, codes, addresses, the account wait and the
payment card stay native.

## The problem

Every new kind of task the agent can do (shopping, managing an order, reservations, and next flights, tickets
and appointments) has so far needed new drawing code in `apps/src/agentTasks/PurchaseCard.tsx`, and so an app
release. Reservations shipped without one only because they reuse the cards of an order being managed
(`kind` is reported as `manage`, `act` for approvals, `approve` for a booking paid now). That works, but the
words on the buttons are a purchase's ("Sí, envíala", "Envío a:") and every new case stretches it further.

Today the card draws these states, each with its own code: `choose` (products with photos and the "Elegir up to"
cap), `login` (store credentials), `otp` (a code), `address` (saved addresses or a new one), `approve` and
`subscribe` (the order: item, breakdown, total, address), `act` (a request to approve), `step` (yes or no to a
step the judge could not read), `account_wait`, `payer_data` and `no_rail` (notify me), plus the journey and the
payment card.

## Decision to make

**A. A card per job** (flight card, hotel card, restaurant card, bus card...). Each looks exactly right, but
every new job is an app release, old builds cannot show new jobs at all, and the cards drift apart.

**B. One general card the server fills** (recommended). The app learns a small, fixed vocabulary of blocks
once; the server composes any job from it. A flight, a hotel, a table, a refund or a doctor's appointment are
all "a title, a picture, some labelled lines, a total, and one or two buttons". New jobs need no app release.

## Recommendation: B, with three native exceptions

### The card's shape (`card` on `AgentTaskType`, versioned)

```
card {
  version: 1
  icon: "bed" | "bus" | "plane" | "table" | "bag" | "package" | "calendar" | ...   (unknown -> a generic icon)
  title: "Hostal Las Tunas"               subtitle: "booking.com"
  image: url | null
  lines: [{label: "Entrada", value: "mar 3 feb"}, {label: "Huéspedes", value: "2 adultos"}, ...]
  total: {label: "Total", value: "US$ 120", note: "Se paga en el alojamiento"} | null
  notice: "No pide tarjeta" | null        (one short line, never a warning row)
  actions: [{id: "approve", label: "Confirmar reserva", style: "primary", binding: "<digest>"},
            {id: "decline", label: "No, déjalo así", style: "link", binding: "<digest>"}]
}
```

One mutation answers every card: `answerAgentCard(id, action, binding)`. The `binding` is the server's own
digest of exactly what the card showed (today's `total`/`address`/`what` checks in `service.approve` and
`answer_request`, made general), so a tap approves what was seen and nothing else.

### What stays native (special blocks, not new cards)

1. **Choosing among options with photos** (today's `choose`): a `choices` block, so flights or rooms can use it
   too.
2. **Typing a secret** (store sign-in, a code): a `secret_input` block. It never echoes into the thread.
3. **The payment card**: its own flow, as today.

### Backward compatibility

- The server keeps sending today's fields (`reason`, `order`, `request`, `options`, `message`) alongside
  `card`. Builds before the general card keep drawing what they draw today.
- A build that knows `card.version` 1 draws `card` when present and ignores the legacy fields.
- An unknown block, icon or action is skipped. The `message` text is always present, so even the oldest build
  says what is going on. A job an old build cannot act on gets one line: "Actualiza Confío para confirmar esto
  aquí".
- Each block is optional, and new block types are added rarely and only to the app's vocabulary, never
  per job.

### Order of work

1. Server: build `card` for every current state (shopping, manage, reservation), reusing the existing notes.
   It is shipped dark only in the sense that old builds ignore it; nothing changes for them.
2. App: one `TaskCard` renderer for the blocks, plus `answerAgentCard`. It replaces the per-reason branches in
   PurchaseCard once it draws every state at least as well.
3. Then every new job (flights, tickets, appointments) is server-only.
