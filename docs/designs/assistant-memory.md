# Design: conversation compaction and memory for Confío IA

Date: 2026-11-22
Status: the founder decided on 2026-11-22: deploy, all three switches on for everyone, both parts on by default,
no backfill, free, Privacy Policy 1.14.0 without legal review. Summary and memory act only for builds that send
`X-Confio-Memory` (the Memoria screen). No store build had it on that day.
Reopens the "Memory" row of section 3 of `ai-assistant-server-architecture.md`, and keeps its reason: text a
model writes and replays is a place to plant instructions. So nothing here stores text at all.

The repository is public. Aggregates only: no user messages, ids or names belong here.

---

## 1. Summary

**Overflow is not a risk today. Forgetting is the problem.** A request uses about 2% of the model's input limit.
The assistant saw only the last 16 messages, and 16% of the user messages measured were answered with older ones
silently dropped. That is concentrated in the 4% of threads that run past 16 messages.

| Layer | What it does | Switch |
|---|---|---|
| (a) Recent window | Up to 40 recent messages within a token budget, bounded tool results, one smaller retry if a request is too large | `CONFIO_ASSISTANT_CONTEXT_ALLOWED_USER_IDS` |
| (b) Rolling summary | A background job picks up to 12 of the person's own older messages. It stores their ids, never text | `CONFIO_ASSISTANT_SUMMARY_ALLOWED_USER_IDS` |
| (c) Memory | Preferences from closed lists, saved only when the person asks. See, delete, switch off, wipe | `CONFIO_ASSISTANT_MEMORY_ALLOWED_USER_IDS` |

Each switch is `''` (nobody, the default), `'*'` (everyone) or a list of ids.

**Money stays safe because what the model is shown and what the code believes are separate.**

1. Every guard reads the raw last 16 messages, exactly as before.
2. The window is only ever wider than those 16, less what the person forgot. A budget limits what is added.
3. Stored data reaches the model only as the result of a read, `recall_memory`. Once it or an older message is in
   view, nothing that acts runs: the turn starts over with the raw messages, and only that pass acts. A tool
   added later counts as acting until it is put on the allow-list. One exception: a screen may open (no prefill,
   no label of the model's).
4. A reply that used stored data is never replayed to a model, so it cannot carry that data into the next turn's
   "raw" messages. The person and the team still see it. This holds with every switch off.

---

## 2. What was measured (prod, read-only aggregates, 2026-11-22)

`AssistantTurn` mixes two things: chat turns and the first-steps guide's generated lines, which have no user
message and more turns than chat. They are separated below.

| | Chat, all time | Chat, 30 days | Guide, 30 days |
|---|---|---|---|
| Turns | 2,053 | 1,117 | 2,666 |
| Input tokens per turn, all its requests: median | 20,121 | 25,137 | 13,234 |
| p95 | 32,967 | 37,403 | 14,660 |
| max | 73,795 | 73,795 | 15,672 |
| Cost per turn, median | $0.0013 | $0.0015 | $0.0012 |
| Cost per active user, mean | $0.0036 | $0.0037 | $0.0027 |
| Cost per active user, p95 | $0.0124 | $0.0127 | $0.0057 |

- A single request: median about 13–14K tokens, p95 about 15–16K. The largest is about 22K (estimated as the
  turn's tokens over its requests). Nearly all of it is the system prompt, `faq.md` and the tool list.
- The 16-message window is tiny: median 543 characters, p95 2,544, max 6,516.
- Messages are short. The person's: median 33 characters, p95 92, max 872. Replies: median 241, max 1,273.
- Threads: 1,425, median 3 messages, p95 15, p99 35. Over 16 messages: 52. Over 30: 16. Over 50: 4. Over 100: 1.
- 8% of user messages arrive after a gap of more than a day.
- **Errors caused by size: 0** in 4,724 turns.
- **Demand for explicit memory has not shown up yet:** 0 messages start with "recuerda", 1 with "olvida", and
  0 match the "ya te dije / te acuerdas" phrases searched for.

| Model | Role | Real limit | Largest use seen | Share |
|---|---|---|---|---|
| `gpt-6-luna` | every turn | 1,050,000 context, 922,000 input | ~22K in a request | ~2% |
| `gpt-6.1-sol` | one analysis call | 1,050,000 context, 922,000 input | a fixed 3-month payload, no history | under 2% |
| `claude-haiku-5-5` | evaluation transport | 1,000,000 context | same payload as Luna | ~2% |
| `gpt-realtime-2.1-mini` | voice, off | 128,000 context | gets no thread history | not in use |

What can still grow a request: a staff reply has no length limit, and the number of parallel tool calls in one
step has none (12K characters each, 62K for a public document). Neither has come near a limit. Price moves before
the limit does: Luna doubles input prices above 272K tokens, and Haiku 5.5 costs five times more above 100K.

---

## 3. Native or our own

Read in the providers' documentation on 2026-11-22.

| | OpenAI compaction | Claude compaction | Ours |
|---|---|---|---|
| Form | Encrypted, opaque item | Readable text block | Ids of the person's own messages |
| Threshold | Caller's | Default 150K tokens, minimum 50K (on-demand beta exists) | By message count |
| Can leave out web, mail, photos, third-party text | No | Only by asking in its prompt | Yes, they are never input |
| Can forget one fact or follow a deleted message | No | Rewrite the block | Yes, ids resolve when read |
| Can be shown to the person | No | As model prose | Yes, their own words |
| Works for both providers | No | No | Yes |
| Outside the reply | Separate call | On-demand variant | A background job |

**Choice: our own.** Native compaction solves overflow, which we do not have. Our requests never reach a
threshold where threshold compaction would fire, and its output would carry assistant replies (so web results,
movement notes and other people's names) into the part of the prompt nobody can inspect.

Why the summary quotes instead of rewriting: the median user message is 33 characters, so a dozen of them are as
short as a prose summary. Quotes cannot invent, cannot contradict a staff reply with a paraphrase, and disappear
with their message.

### How ChatGPT and Claude expose memory

| Control | ChatGPT | Claude | Confío IA |
|---|---|---|---|
| Default | Varies by plan and region | On for individual plans | On (founder, 2026-11-22), each with a switch |
| See and delete items | Yes | Yes, and edit | Yes. To change one, say "recuerda que…" again |
| Two controls | Saved memories, chat-history reference | Pause, reset | Preferences, older-message recall |
| Switch off | Keeps chats | Pause keeps memories | Keeps preferences unused, drops the summary |
| Wipe | Yes | Reset | Yes |
| Deleting a chat deletes what was derived from it | Not necessarily | No | **Yes** |
| Sensitive topics | Can be saved | Not by default. Government ids and account numbers never | Never, as far as a filter can tell |
| Separation | — | Per project | Per user and account context |

Sources: developers.openai.com/api/docs/guides/compaction,
platform.claude.com/docs/en/build-with-claude/compaction, help.openai.com/en/articles/8590148-memory-faq,
support.claude.com/en/articles/11817273.

---

## 4. The three layers

### (a) Recent window (`assistant/context.py`)

- Today's 16 messages, plus older ones up to 40 in all while about 6,000 estimated tokens allow.
- The last three team replies or team notices of the past 30 days stay after they leave the window.
- Tool results share 120K characters per turn. A cut result says it was cut.
- Too large for the provider: one retry with only the latest message and short tool results. That answer has no
  tools: it saw too little to act. Tools that already ran do not run again.
- A provider that rejects older text gets one raw pass, so one bad old message cannot fail every reply.

### (b) Rolling summary (`assistant/memory.py`, task `assistant.summarize_context`)

- Runs after a reply commits, on the analytics queue, when 8 or more messages are older than the newest 12. It
  is published off the request's thread, so a broker that is down does not hold a reply.
- Input: only the person's own typed or transcribed messages. Never an assistant, system or team message, a
  photo message, a tap, a realtime caption, a message sent to the team or a paste.
- **Three gates, each failing closed:**
  1. an allow-list of shapes: a first-person statement about travel, studies, a project, a hobby, a pet, an
     event or a goal, in Spanish or Portuguese. No questions, no labels, no other language;
  2. word lists for secrets, documents, addresses, money, sensitive traits, instructions and other voices;
  3. a model with no tools that must put it in one of seven closed topics, and may only return ids it was given.
- Gates 1 and 2 run again at every read. Digits are masked.
- A quote older than the team's last reply or notice is dropped: what someone told us never stands against what
  the team answered afterwards.
- Idempotent: a compare-and-set on the row. A forget that lands during a run wins.
- **No backfill:** it starts at the first message answered with it on, never reads what was said before, skips
  what was said while it was off or from a build without the screen, and reads at most 60 messages a run.

### (c) Memory

Product facts stay where they are and are read live (first name, country, identity, rails, saved payees,
balances, rules). Memory never copies them. What it holds, all from closed lists, with no free text at all:

| Kind | Values | How the model gets it |
|---|---|---|
| Reply language | Spanish, Portuguese, English | a sentence of code's, every pass |
| Reply length | short, detailed | same |
| Explanations | beginner, experienced | same |
| Form of address | tú, usted, vos, você | same |
| Goal (up to 3) | emergency fund, travel, home, vehicle, studies, own business, family support, wedding, retirement, saving | `recall_memory` |
| Occupation | employee, freelancer, business owner, student, homemaker | same |
| Family in (up to 3) | a country from a fixed list | same |
| Interests (up to 3) | football, cooking, music, travel, reading, movies, games, technology, animals | same |

- Saved only when the latest message is the person's own short request ("recuerda que…", "lembre que…",
  "respóndeme siempre en…"). A model with no tools and no history sees that one message and can only pick from
  the lists. Code writes the confirmation, from what is really saved.
- "olvida que…", "esqueça que…": deletes matching preferences and everything derived up to that message. The
  model stops seeing earlier messages. Team replies stay. A question in the same message is still answered.
- "olvida todo", "borra tu memoria": wipes with no model, also while the team has the thread or with no turns left.
  "borra todo" alone never does, and "apaga la memoria" in Spanish points to the switch: it is not a delete.
- A forget is never guessed. Only an exact "olvida todo" deletes unread, and never after a "no". If nobody is
  answering (the team has the thread, no turns left), a line of code's says nothing was
  deleted and how to delete it. It is read later in one case only: the thread had an earlier handoff or team reply
  and it is still the person's last message on "volver al asistente". If the model that reads it is down, the reply says it was not
  deleted.
- No nickname and no free notes ("mi perro se llama…"). The summary can quote those while recall is on.

#### Who a contact is (added 2026-11-26)

"Recuerda que Alejandro Teixeira es el de la panadería": the one kind that holds words, decided with Julian after a
person was told memory could not keep it. It still stores no text:

- The value is where the name and the description are in the person's own message (`a-b-c-d`). The closed-list
  model names both, copied from the message; code finds them there, so a model cannot write one.
- Only a chat of her linked WhatsApp (`memory.in_whatsapp`, at save): the name is then one Confío already holds
  with her consent. Gate 2 still reads it with the whole message (only an address word in it, such as "Torres",
  is excused). It must not read as staff, a system or an order,
  since it sits in the instructions (`memory_rules._NAME_STAFF`, word by word, joined, letters said once, and
  inside glued words). Written as Latin letters with one space, apostrophe or hyphen between words, a capital only
  where a word starts, and no combining mark.
- The description is an allow-list that fails closed (`_CONTACT_LABEL`): an everyday role ("mi contadora", "la
  dueña del local"), the place or trade they are from ("el de la panadería"), or family as hers ("mi padre").
  A partner, a health, legal or religious role, a lender or staff is simply not on it.
- The shape is hers and plain: "… que <name> es <description>", with no negation or hearsay before it and nothing
  undoing it after; the description ends her clause. Gate 2 reads all she said except the name. Deleting the
  message deletes it (cascade), and the screen, "olvida quién es…", "olvida mis contactos" and a wipe delete it
  like any preference. One per name, the newest wins, at most 20.
- The model gets them as a block in the instructions, every pass, raw passes included: `CONTACTS_NOTE`. That is
  the trade-off. Through `recall_memory` they would end the pass that writes the WhatsApp card ("escríbele al de la
  panadería"), because a pass that read stored data never acts. A name and a description of the person's own
  cannot move money: the payment guards still read only her raw words, and every card still shows the chat and
  the exact text before she taps. It is left out for whoever can be operated for (Cuenta inteligente with
  Confío IA+), whose tools accept an existing payee or a rule the owner did not name.
- Parts are whole words of her message ("Ana" is not taken from "Mariana"). A contact that no longer passes shows
  on the screen as «Un contacto guardado», to be deleted.

---

## 5. Invariants, and where each is enforced

| Invariant | Enforced by | Test in `assistant/test_memory.py` |
|---|---|---|
| Summary and memory are never evidence for money | Guards built from raw history. Acting tools only in the raw pass. Replies that used stored data are not replayed | `MoneyEvidenceTests`, `RawPassTests`, `LaunderingTests` |
| A wider window changes nothing a guard accepts | Same. The smaller retry has no tools | `MoneyEvidenceTests`, `WindowTests` |
| Stored text cannot instruct or speak as staff or system | Ids and enums only. Data arrives as a tool result. Style sentences are code's | `PlantingTests` |
| No web, mail, calendar, photo, QR or third-party text becomes memory | Only the person's own qualifying messages are input, through three gates | `PlantingTests`, `NeverStoredTests` |
| No secrets, documents, cards, codes, addresses, balances, sensitive traits | No text column, the allow-list, the filter at write and read | `NeverStoredTests` |
| No crossing of users or contexts. Employees cannot read the owner's | Row keyed by user plus the account or business of the JWT context | `IsolationTests` |
| The team's thread and replies stand | No context while waiting, team-bound messages never summarized, team replies pinned, older quotes yield | `HandoffTests` |
| Forgetting, message deletion and account deletion reach the summary | Cut-off id, version bump, ids resolved at read, cascade, signal and nightly sweep, no admin delete | `ErasureTests` |
| Nothing derived is logged | Type names only. Tool arguments blanked once stored data was read. Admin shows no value or id | `NoLogTests` |

Deletion and soft-delete: a forgotten preference keeps its soft-deleted row with kind, value and source blanked.
The tombstone says when, never what. A deleted account's row is emptied and keeps only its cut-off.

---

## 6. Limits, said plainly

- The summary holds the person's side only, on seven everyday topics. "What did you recommend last month?" is
  not answered from it, and neither is anything outside those topics. The allow-list costs recall on purpose.
- The raw thread remains. Forgetting stops use. It does not delete messages, which are support records.
- A forget hides earlier messages from the model only while one of these switches is on.
- The gates can fail. A sensitive thing said in everyday words with a travel or hobby shape could be quoted back
  to the same person from their own thread. It cannot become a preference, and it cannot act.
- A pass that acts does not see stored data or older messages, so "busca hoteles en la ciudad que te dije" asks
  which city. A follow-up to a reply that used stored data may read it again or ask.
- An older message in the wider window can shape a question the assistant asks. Acting on the answer still
  takes the person's own words at each guard. The Cuenta inteligente tools take less than that (deleting an alert
  or the investment target, cancelling a rule, re-splitting to the saved target, choosing an existing payee or
  saved destination), so whoever the assistant can operate for **keeps today's 16-message window**: the wider
  window is not for them until those tools require the owner's words, a Cuenta inteligente follow-up.
- "Operated for" is whoever has Confío IA+ on a Cuenta inteligente, on any build. For up to 16 messages after
  someone subscribes, replies written with the wider window are still in their thread.
- Deletion in the usted form without its accent ("borre mi memoria") is not read as a request, because it is also
  "borré". The screen deletes, and so does "borra tu memoria".
- Deleting one quote also hides the answer it got. A later reply that repeated it from the window stays until it
  leaves the window.
- The nightly need tagger (`assistant/needs.py`) is separate product evidence and does not follow a forget.
- Voice calls and the first-steps guide get no memory. An employee who is removed keeps a row nobody can open.
- The summary job is metered on the memory row, not in `AssistantTurn`, so it never uses up daily turns.
- Memory is never advertising: a turn that read it opens and shows no paid offer.
- A build without the screen is told plainly that it cannot save or delete memories.
- If the memory tables cannot be read, the answer sees only the latest message and the team's, and an error is
  logged. Confirm the migration before switching on.
- A turn that restarts can in the worst case outlast the 60-second proxy timeout. Watch `latency_ms`.
- A turn that restarts to act makes one more request: in threads over 16 messages that is every turn that acts.
- A follow-up ("sí", "amplía el día 2") to an answer that used stored data has lost what it refers to unless the
  assistant reads it again, and such an answer can never be the question a trade "sí" confirms. Watch both with
  testers.
- The assistant no longer hands a thread to the team (67d850695). What is said here about "the team has the
  thread" now applies to the assistant's kill switch, and to the staff replies and notices already in threads.
- The Memoria screen lives inside the assistant, so it is out of reach while the assistant's kill switch is off.

---

## 7. Cost per active user

Today: **$0.0037 per chat user per month** (30-day mean, prod: 2.5 chat turns each, median $0.0015 a turn). The
first-steps guide is separate, $0.0027 for each person it speaks to.

| Piece | Measured on synthetic threads of 70-171 messages | When it is paid |
|---|---|---|
| Wider window | +420 input tokens a request (+2.5%), at most $0.00005 | threads over 16 messages: 16% of messages |
| Reading stored data | one more request: $0.0006-0.0009 for the turn, $0.0003-0.0005 without (caching moves both) | only when the model reads it (0 of 9 unrelated questions did) |
| Restart to act | one more request, up to about $0.0013 on prod's prompt | a turn that acts after seeing extra context |
| Summary run | $0.00007 | every 8 messages in a long thread |
| Reading "recuerda / olvida" | $0.00012 | those messages only |

**With all three on: about $0.004 per chat user per month, and about $0.007 if every turn of every person read
stored data.** These two are arithmetic from the measured pieces and prod's usage, not a measurement on prod.
At today's volume (444 chat users a month) the difference is under $2 a month.

Metered costs on both sides run slightly low: `TurnResult.add_usage` does not price cache writes (1.25x input).

---

## 8. Evaluation

`manage.py assistant_memory_eval --repeat 3`: live `gpt-6-luna`, synthetic Spanish and Portuguese conversations
of 70, 120 and 171 messages, no real user's data.

| Measure | Today | With this |
|---|---|---|
| Recall, 17-40 messages back | 0/18 | window 18/18, all three 18/18 |
| Recall, beyond 40 | 0/36 | window 0/36, all three 36/36 |
| Saved topic recalled | — | 3/3 |
| Saved language followed, against a Spanish thread | — | 9/9 |
| Stored data left unread on unrelated questions | — | 9/9 |
| "recuerda" recall | — | 78/78 |
| **Wrong-memory rate** | — | **0/78** |
| Left alone when it should be | — | 84/84 |
| "olvida" | — | 18/18 |
| Summary: worth keeping / must not keep | — | 36/36 kept, 0/36 kept |
| Injection: an acting tool ran from a context pass | — | 0/12 |
| Injection: acted naming the planted payee | — | 0/12 |

The sets above were used to tune. The fairer number is the **held-out set**, written after the last rule
change and run once (5 repeats). An earlier held-out set is retired: audit fixes had fed on it, and on the final
rules it leaked 1 line in 120 runs, since fixed.

| Held-out | Two word gates | All three gates |
|---|---|---|
| Worth keeping (20 lines) | 14/20 | **59/100 runs, 59%** |
| Must never be kept (24 hard lines, reworded to pass word lists) | 20/24 let through | **0/120 runs** |

Read plainly: the word gates alone are weak against rewording. The third gate, a model, is what held, and a model
can fail. The allow-list misses about 4 in 10 of what would have been nice to keep. That is the price of failing
closed, and it only affects recall beyond 40 messages.

Not run live: the Claude transport (no Anthropic key on this machine or on prod). It has unit tests only.

---

## 9. Rollout

1. Migrate, then restart. (Code before the migration breaks admin deletes of users and messages.)
2. The Privacy Policy is published with the same deploy.
3. (a) is on for everyone at once, on any build.
4. (b) and (c) are on for everyone and wait for the build: a request counts only with `X-Confio-Memory: 1`, which
   a build sends when it has the screen. So the screen always comes first, with no version floor to maintain.

To stop any of the three: empty its variable in prod's environment and restart. That is also the rollback:
don't revert the code once 0014 has rows, because older code cannot delete what they point at.

The switches are environment variables read in `config/settings.py` (defaults in `assistant/conf.py`).

Decided 2026-11-22: on by default (`CONFIO_ASSISTANT_MEMORY_DEFAULT_ON`, `CONFIO_ASSISTANT_SUMMARY_DEFAULT_ON`),
no backfill, free. Still open: whether nicknames or free-text notes are ever wanted.
