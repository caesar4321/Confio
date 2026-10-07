# Confio Assistant

Replaces "Soporte" in Mensajes with an assistant that answers first and hands money problems to people. The entry point is a floating mascot bubble on **every** screen; the Home-header inbox button is gone for good.

## Decisions (Julian, 2026-10-04)

- **AI-first, same thread.** Confio Assistant answers in the existing `SupportConversation`. Handoff happens via `escalate_to_human` or "hablar con una persona". The team owns the thread until 24h of staff silence or until the user taps "Volver a Confio Assistant".
- **Bubble.** It sits on every screen inside the logged-in app, can't be hidden, and can be dragged; it snaps to the left or right edge and the position is remembered per user. It's the only way into Mensajes (unread badge plus hints). It hides only while the keyboard is up or the chat is open.
- **Models.** Luna (`gpt-6-luna`) handles every text turn. Sol (`gpt-6.1-sol`) runs only inside `analyze_finances`. Realtime calls use `gpt-realtime-2.1-mini`.
- **Assistant+ at US$9.99/month.** Each store sets the regional prices. Billing goes **direct to Apple and Google, no RevenueCat**: our own native module (`ConfioBilling`) and our own server verification.
- **Floating message box.** The bubble opens a floating window (not a screen) with chat heads for Confio Assistant, Julian and Confío News. Legacy `HomeMessages` links and pushes redirect into it.
- **Pets.** Built-in (Confi, llama, capybara, cat, dog, plus color) **or created by the user**, like OpenAI's dots or Meta's Muse:
  - From an idea, or from a photo of the user's own pet. Photos with people are refused, and moderation fails closed.
  - One `gpt-image-2` low-quality image, measured at ≈US$0.008. Moods are shown through motion.
  - Limits: free 3 per week, Assistant+ 10 per day.
  - Stored privately in S3, under `assistant/pets/<user>/`, with short-lived signed URLs.

## Launch decision (2026-10-04): free, no realtime

- **Ships free:** text, voice notes, analysis of the user's own transactions, pets, and the floating box.
- **Built but dark:** realtime voice and the wake word (`CONFIO_ASSISTANT_REALTIME_ENABLED` False). Realtime was 52–82% of simulated AI cost.
- **No store purchases (2026-10-07):** Apple/Google in-app purchases were removed from the app and the server (none was ever sold; Duende Limited, Seychelles, can't be a Google Play merchant). `AssistantSubscription` stays, for Confío to grant and bill Assistant+ itself (direction: a Cuenta Confío-style membership).
- **Simulated cost without realtime** (`manage.py assistant_economics --simulate`): $0.03 per IA user per month on average, which needs $3.4/month of boundary volume at 0.9% to break even. The capped worst case is $2.38.
- **Measured Sol analysis cost:** $0.019 with two months of movements. Cut to the current month only, it is **$0.012** (4.7k input tokens). Free cap is now 3 analyses a day, so the capped worst case is **$1.97 a month** (messages $0.24, voice-note transcription $0.54, analyses $1.10, pets $0.10).
- **No control group** (Julian, 2026-10-04): everyone gets Confio Assistant plus pets. Read `assistant_economics` cohorts as correlation only.
- **Floating box:**
  - It springs out of the bubble, with a tail pointing back at it.
  - The bubble stays on screen as the ✕ close button.
  - Chat heads with names switch between Confio Assistant, Julian and News.
  - Pet entry points: "🐾 Mi mascota" in the IA header, a "🐾 Crea tu mascota" starter, and long-pressing the bubble.
- **Guardrail eval:** `manage.py assistant_eval` checks escalation of money problems, no advice or price predictions (including Confío's own products), no claims of moving money, no secrets. 45/45 passed on 2026-10-04. Re-run on every prompt or model change.

## Plans (if Assistant+ is ever offered)

| | Free | Assistant+ (US$9.99) |
|---|---|---|
| Text + voice notes | 40 turns/day | 300 turns/day |
| `analyze_finances` (Sol) | 5/day | 30/day |
| Realtime voice call | — | 100 min/month (server-clocked) |
| "Confío" wake word | — | ✓ (opt-in, foreground only) |

## What Confio Assistant can do (tools, all JWT-scoped)

- `navigate`: opens *verb* screens only (Recargar → Recibir, Retirar → Enviar, Acciones/Preventa → Invertir), so the country, geo and Face checks always run.
- `get_month_summary`: the same numbers as "Tu mes".
- `get_transactions`: the user's own classified movements (date, type, amount, counterparty, category, id), filtered by group and counterparty name.
- `categorize_transactions`: the Tu mes rules (counterparty rule or single override). Only on the user's request or confirmation; ids resolve inside the account's own scope.
- `analyze_finances`: Sol, fed three monthly summaries plus up to 50 movements per month.
- `escalate_to_human`.

Employees get no money tools. The AI never moves money and never states balances.

## Architecture

- **Text and voice notes.** `askAssistant` runs a synchronous Responses API loop (`store=false`, encrypted reasoning) inside the GraphQL request. Every turn is metered in `AssistantTurn`.
- **Realtime.**
  - `startAssistantVoice` mints a 2-minute OpenAI client secret, with the session's instructions and tools set by the server.
  - The app connects over WebRTC (`react-native-webrtc`) and relays every non-navigate tool call to `runAssistantVoiceTool`, which uses the same Toolbelt as text.
  - `logAssistantVoice` saves transcripts into the thread (modality `REALTIME`) and acts as a heartbeat. Minutes are counted from server timestamps, and the call is cut when the month's minutes run out.
  - Audio goes to the loudspeaker via `ConfioAudioRoute`.
- **Entitlement.** Assistant+ is whatever an entitled `AssistantSubscription` row says (`assistant/billing.py`). There is no store billing; how Confío bills it is still to be designed.
- **Wake word.** Porcupine 3.0.4 (iOS 13+, keeps iOS 15 users), on-device, foreground only. It pauses while the chat is open or a call is live. The AccessKey is served only to Assistant+ users.

## Setup only Julian can do (the features stay dark until done)

1. **Secrets Manager `prod/confio-assistant`** (JSON): `picovoice_access_key`.
2. **Picovoice:**
   - Get an AccessKey. Commercial use needs a paid plan.
   - Train the Spanish keyword "Confío" for **Porcupine v3.0** for iOS and Android, and download `porcupine_params_es.pv` (v3).
   - Add `confio_es_ios.ppn` and `porcupine_params_es.pv` to the iOS app's bundle resources, and `confio_es_android.ppn` and `porcupine_params_es.pv` to `android/app/src/main/assets/`.
3. **Store cleanup (no in-app purchases since 2026-10-07):** archive any `confio_ia_plus_monthly` product in App Store Connect / Play Console, and remove the App Store Server Notifications URL and the Play RTDN push subscription if they were set (those webhooks are gone).

## Open

- Daily macro/FX briefing in the prompt versus per-question web search ($0.01 per call).
