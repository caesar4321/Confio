# Design: mail and calendars for Confío IA

Date: 2026-11-22
Status: stage 1 (phone calendar) and the approved Gmail pilot are built and switched off. Nothing is deployed or submitted to Google or Apple.
Fits the assistant-first redesign. Its rules for anything that moves money apply here: only the owner's signature moves money, the payee is the rail's answer, and third-party content is data.

The repository is public. This document holds no user data, tokens or mail content, and none may be added.

---

## 0. Summary

**Decided (founder, 2026-11-22), latest wins:**

1. Mail must arrive by itself. Forwarding one mail at a time would lose users.
2. Forward-all is not built: it cannot be set up in the Gmail app, and nearly all monthly actives sign in with a Gmail address (checked on prod, described qualitatively; iCloud is a small minority, and a login address is a proxy for the main inbox).
3. **Gmail pilot approved:** up to 100 testers in a separate Google project in Testing, `gmail.readonly` and `gmail.send` with confirmed sends, encrypted refresh tokens on our server, no mail stored.
4. Not approved: OAuth verification, CASA, public Gmail launch, any deploy, app passwords.

| Source | Route | Set up inside the mail app? | Set up on a phone at all? | Approval and cost | Status |
|---|---|---|---|---|---|
| Apple Calendar | Phone calendar (EventKit) | — | Yes, one permission | Privacy text | **Stage 1, built, off** |
| Google Calendar | Phone calendar | — | Yes, one permission, if the account syncs to the phone | Privacy text | **Stage 1, built, off** |
| iCloud Mail | Forward all | No | Yes, icloud.com in the browser | None | Not built |
| Gmail | Forward all | No | Not documented, must be tested | None | Weak: setup barrier |
| Gmail | OAuth connect | Inside Confío, a tap and a consent screen | Yes | Verification, CASA from about US$675 a year, up to 5,400 at that lab | **Pilot approved** |
| iCloud or Gmail | IMAP app password | No | Yes, account page in the browser | None. We would hold a password to the whole mailbox | Not recommended |
| Any | Cloud browser | — | — | Blocked by Google, against iCloud's terms | No |

---

## 1. Feasibility

"Not verified" means no primary source was found.

### 1.1 By source and platform

| Source | Platform | How access works | Approval | Background | On device only | Impossible |
|---|---|---|---|---|---|---|
| Apple Calendar | iOS | [EventKit](https://developer.apple.com/documentation/eventkit/accessing-the-event-store). iOS 17+ needs full access to read, there is no read-only level | Usage string, privacy text, App Review | Refresh runs are [not guaranteed](https://developer.apple.com/documentation/backgroundtasks/bgtaskrequest/earliestbegindate). A scheduled local notification fires without the app | Read, filter, remind | A dependable wake-up for an event added while the app is closed |
| Apple Calendar | Android | None. Only CalDAV from a server or app with an [app-specific password](https://support.apple.com/en-us/102654) | None | Needs a held password | No | OAuth or a REST API (none is documented) |
| Google Calendar | iOS | EventKit, if the account was added in the phone's settings | As Apple Calendar | As Apple Calendar | Yes | Seeing calendars that live only inside the Google Calendar app |
| Google Calendar | Android | [Calendar Provider](https://developer.android.com/identity/providers/calendar-provider), `READ_CALENDAR`, no OAuth | Runtime permission, Data safety. [No special Play declaration](https://support.google.com/googleplay/android-developer/answer/9888170) | WorkManager, subject to Doze | Yes | Events of an account with sync off |
| Google Calendar | Both, server | `calendar.events.readonly` and [push channels](https://developers.google.com/workspace/calendar/api/guides/push) | [Sensitive verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification): demo video, policy, verified domain | Yes, with a refresh token and an HTTPS webhook | No | — |
| Gmail | Both, device | `gmail.readonly`, polled by the app | Restricted verification. [Google's text](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) ties CASA to the ability to reach data "from or through a third-party server". No written on-device exemption was found | Poor on iOS | Only with an on-device model and nothing derived leaving the phone | Using our hosted assistant on it without counting as a server path |
| Gmail | Both, server | `gmail.readonly` + [`users.watch`](https://developers.google.com/workspace/gmail/api/guides/push) and Pub/Sub, renewed at least every 7 days | Restricted verification, CASA every 12 months | Yes, with refresh tokens | No | A read scope that is not restricted |
| iCloud Mail | Both | [IMAP](https://support.apple.com/en-us/102525), `imap.mail.me.com:993`, app-specific password | None | Needs a held password | Only while the app runs | OAuth (none is documented) |
| Apple Mail app | iOS | No read API. A Shortcuts email trigger may pass on new mail (4.5, untested). [MailKit](https://developer.apple.com/documentation/mailkit) is macOS only | — | — | — | Reading its messages |
| Apple Mail app | Android | The app does not exist | — | — | — | Everything |

### 1.2 What the briefing assumed

| Assumption | Verdict |
|---|---|
| Gmail read scopes are restricted | Confirmed. [`gmail.metadata` is restricted too](https://developers.google.com/workspace/gmail/api/auth/scopes), and it cannot search or read bodies |
| Restricted means verification plus a paid yearly CASA | Confirmed for a server path. Google charges nothing, the lab does. The free self-scan is gone: the [current levels](https://appdefensealliance.dev/casa/casa-tiering) AL1 and AL2 are both lab-verified, although a Google help page still mentions a free tier |
| Calendar scopes are sensitive, with no CASA | Confirmed for reading events. The category of each individual scope shows only in the Cloud Console |
| The app uses Google Sign-In with Drive appData | Confirmed (1.3) |
| Apple Calendar has no server API | Confirmed as far as documentation goes. No API is documented, and CalDAV needs an app-specific password |
| Apple Mail has no API, iCloud Mail is IMAP only | Confirmed for iOS. MailKit exists on macOS only |
| Sharing a mail into Confío is a path without scopes | **Not verified.** Whether iOS Mail and the Gmail apps share a message body must be tested on phones. Our Android share target accepts only images today |

### 1.3 What the app has today

- Scopes: `email`, `profile`, and `drive.appdata` when the user opts into backup (`apps/src/services/authService.ts`, `configureGoogleSignIn`). `drive.appdata` is [non-sensitive](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), so none of these needed scope verification.
- No calendar or mail scope, permission or usage string before this slice.
- Sign-in sets `offlineAccess: true`, but no code found sends or exchanges the server auth code. Our server holds no Google refresh token through it.
- **Not checked: the consent screen's publishing and brand-verification status.** The Cloud Console needs the owner's sign-in. Look at Google Auth Platform → Audience and Verification Center for project `confio-abbda`.
- Until verified, a project in Testing has [100 test users and grants that expire after 7 days](https://support.google.com/cloud/answer/15549945). An unverified scope in production shows a warning and has a lifetime 100-user cap.
- The Privacy Policy (`users/legal/documents.py`) names OpenAI for messages, audio and photos sent to the assistant. It covers neither calendar nor mail.

### 1.4 CASA price and time

- TAC Security, as [reported in November 2026](https://deepstrike.io/blog/google-casa-security-assessment-2025): US$675–855 for a one-time AL1 assessment and US$5,400 for AL2. Secondary source, TAC's own site refused the fetch.
- [Leviathan's public list](https://leviathansecurity.com/programs/google-casa-cloud-application-security-assessment) for AL1: US$3,000 (starts within 30 days), US$4,500 (10 days), US$6,000 (2 days). Its AL2 price is not listed.
- Google picks the level from data sensitivity, user count and risk. It can change. Every year is a [full retest](https://support.google.com/cloud/answer/13463816).
- Ask two or three labs for quotes if this is reopened. The cost depends mostly on the level Google assigns, which is known only after applying.

---

## 2. How the four assistants do it

Read from each company's own pages on 2026-11-22. What they say, not an audit of what they do.

| | Gmail | Calendar | Where it is processed | Training on that data | Approval evidence |
|---|---|---|---|---|---|
| **Muse** (Meta) | [Connector](https://www.meta.com/help/superintelligence/1687253048996149/) that can read new mail. Also its own [forwarding address](https://www.meta.com/help/superintelligence/1149305437517250/) that gives no inbox access | Connector, updates on changes | Meta's servers | States Google Limited Use for Workspace data. Mail sent to the Muse address may be used, depending on settings | Limited Use statement. No CASA statement found |
| **Dots** (OpenAI) | ChatGPT's Google app, [scope `gmail.modify`](https://help.openai.com/en/articles/10408842-google-connector-for-chatgpt-data-controls-faq), can trigger on new mail | `calendar.events` | OpenAI's cloud. [Background research is read-only](https://openai.com/index/introducing-dots/) | No generalized training on Google app data or its derivations, with exceptions for feedback, pasted text and text that appears in replies | A restricted scope in public use |
| **Pickle** | [Google OAuth](https://pickle.com/ko/privacy-policy). Naver Mail by [IMAP app password](https://pickle.com/help/connect/naver-mail) | Google OAuth, plus the phone's calendar | US servers. Tokens in a credential enclave. Content goes to Google, OpenAI, Anthropic, xAI and their hosts, and joins history and memory | Never connected-account data. Conversations only by opt-in | A restricted scope in public use. No CASA statement found |
| **Zapia** | [Reads bills and notices](https://zapia.com/?lang=en). Its "Radar" warns before a bill is due | Google Calendar | Servers. Its [policy](https://zapia.com/privacy?lang=en) names OpenAI, Anthropic, Google, Together AI, Tencent and Alibaba | "By default" none on conversations | **States CASA Tier 2** |

What this means for Confío:

1. All four use the ordinary route: OAuth, tokens on a server, hosted models, a promise not to train. None found a way around Google's approval.
2. Zapia is the closest to what Confío wants and publicly claims the CASA route. A company of that size can get through it.
3. Muse shows the cheap path that needs no scope: a forwarding address, with refusals to act on financial requests that arrive by mail.
4. Pickle shows both the phone-calendar route and the cost of app passwords for mail without OAuth.
5. Confío's difference is what follows the nudge: paying on Pix and the other local rails, signed by the owner.

---

## 3. Google's rules on AI

Sources: the [Workspace API user data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy) and its [FAQ](https://support.google.com/cloud/answer/13463817).

- Transfers are allowed to provide a visible user-facing feature, with consent.
- Creating, training or improving a general model with the data is prohibited, as is storing it with one.
- The FAQ also says data must be used "only for a personalized model". Read literally, that could exclude sending mail to a hosted frontier model. Read with the next sentence and with the market (section 2), it excludes training and retention, and allows inference for the user's own feature.
- **This second reading is our inference, not Google's written answer.** State the exact flow (provider, no training, retention) in the verification submission and open Gmail to the public only after Google accepts it. The approved test pilot runs before that answer.
- Prompt-injection protection is a listed required security measure.
- No human may read the data without the user's specific consent. Support staff read the assistant thread today, so mail and calendar content must not be written into it.
- Derived data (a due date, an amount) is treated here as Google user data. The human-access clause names "derivations".

Calendar data read through EventKit or the Calendar Provider does not come through a Google API. Apple's and Google Play's rules govern it.

---

## 4. Smallest useful scope

### 4.1 Calendar

Read on the phone first. No OAuth, no token, both Apple and Google calendars, nothing leaves the phone to show or remind. Server OAuth adds one thing, noticing changes while the app is closed. Take it only with the Gmail verification.

### 4.2 Gmail

| Option | Finds a bill by itself | Scope | Approval | Data we hold | Verdict |
|---|---|---|---|---|---|
| A. Server `gmail.readonly` + watch, narrow filters | Yes, within minutes | Restricted | Verification + CASA | Tokens. Mail in memory. Derived needs | **Pilot approved**, by polling |
| B. Full read and indexing, like a general agent | Yes | Restricted | The same | A mailbox copy | No. Same gate, far more risk |
| C. `gmail.metadata` + watch | Partly. No body, no search | Restricted | The same | Tokens, headers | No. Same gate, worse product |
| D. Polling on the phone | When the app is opened | Restricted | Verification, CASA probably | Tokens on the phone | No. Misses the wake-up |
| E. Forward all new mail | Yes, new mail except spam | None | None | Every new mail, in memory | Not built (4.4), weak setup on Gmail |
| F. Share sheet (text, PDF, screenshot) | No | None | None | The shared item, in memory | Cheap extra, after the device test |

For A: request `gmail.readonly`, plus `gmail.send` only for confirmed sends (4.6). Never `gmail.modify`. On each change fetch headers first, then the body only for likely needs (billers, tickets, due dates). No backfill beyond 30 days, no inbox copy.

### 4.3 App passwords

[OpenAI's iCloud Mail plugin](https://www.macrumors.com/2026/10/27/chatgpt-icloud-mail-calendar-plugin/), which Dots can use since 2026-10-27, works this way. So can Gmail, with a [Google app password](https://support.google.com/accounts/answer/185833), no OAuth and no CASA.

Not recommended for a wallet:

- The password cannot be limited. It reads the whole mailbox, security codes included, and can send.
- A leak on our side becomes a takeover of the user's other accounts.
- Google says app passwords "aren't recommended". They are unavailable with Advanced Protection or security-key-only 2-Step, and die when the main password changes.
- Both need two-factor and a setup most users will not finish.

### 4.4 Forward all mail

Not being built. Kept for the case where mailboxes other than Gmail need a route.

Each user gets a random, replaceable address and turns on forwarding once. After that it runs on the provider's servers with the phone off. It brings new mail only: no history, and Gmail leaves out spam.

| | Gmail | iCloud |
|---|---|---|
| Inside the mail app | No | No, and no iPhone Settings path was found |
| Documented setup | [A computer](https://support.google.com/mail/answer/10957): about 14 steps, with a confirmation mail in the middle | [icloud.com/mail in the phone's browser](https://support.apple.com/guide/icloud-iphone/automatically-forward-email-mm6b1a3960/icloud): 4 steps |
| Phone browser | Reported to work in desktop mode by some guides, denied by others. Test on real phones | Documented |
| Can Confío turn it on for the user? | No. [The API method](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings/updateAutoForwarding) is only for Workspace service accounts | No API |
| Extra hurdles | Adding an address is a [sensitive action](https://support.google.com/accounts/answer/7162782): Google asks to verify identity and can hold the change for 7 days if it cannot | Web access must be on (off by default with Advanced Data Protection) |

Rules for the receiver:

- **The secret address identifies the account, the sender does not.** Automatic forwarding keeps the original sender, so "only from the user's own address" would reject exactly the mail we want. SPF usually fails after forwarding. DKIM results are a signal, not a gate.
- Anyone who learns an address can at most cause a nudge. Nudges have no payee and no pay-by-itself action (sections 6 and 8). The user can replace the address, and it is rate-limited.
- **Forward-all means we receive every password reset and sign-in code of every connected user.** A break-in to the receiver would be a takeover of their other accounts. Run it as an isolated service with no content in logs and no staff access.
- Mail that looks like a security code, password reset or sign-in link is dropped before any model sees it. The one exception is Gmail's forwarding confirmation, accepted only with Google's DKIM signature during a setup window the user opened, and shown only to that user.
- No S3 and no mailbox copy. A mail is accepted only after it is processed. When busy or down the receiver answers with a temporary error and the sender retries.
- Parsed in memory, never spooled to disk. Text and PDF only, size-limited. Links and remote content are never fetched.
- **Hosting:** [Amazon SES cannot receive mail in eu-central-2](https://docs.aws.amazon.com/general/latest/gr/ses.html). Keep to the Zurich rule with a small SMTP receiver of our own there. SES in Frankfurt would be an exception the founder would have to make.

Storage and cost, assuming 50 mails a day of 75 KB per user (an assumption, not measured), for 10,000 connected users:

| Choice | Stored | Cost a month |
|---|---|---|
| **Keep nothing but derived needs (recommended)** | A few MB in Postgres | About nothing |
| Keep raw mail 1 day | 38 GB | About US$1 at [Zurich S3 prices](https://aws.amazon.com/s3/pricing/) (US$0.02695/GB) |
| Keep raw mail 30 days | 1.1 TB | About US$30 |
| AI reads every mail | — | About US$2,600 |
| A cheap rule filter first, AI on 10–20% | — | About US$260–520 |

Space is not the problem. The reasons not to keep mail are the breach risk and that it is not needed. The AI bill is the cost to control.

### 4.5 Other routes checked

| Route | Finding |
|---|---|
| Cloud browser | Google [stops sign-ins](https://support.google.com/accounts/answer/7675428) from browsers controlled by automation or embedded in an app. [iCloud's terms](https://www.apple.com/legal/internet-services/icloud/en/terms.html) forbid access by automated means. Advanced Data Protection turns [web access](https://support.apple.com/en-us/102630) off by default. OpenAI itself says [some sites block the cloud browser](https://learn.chatgpt.com/docs/dots/computers-and-apps). A kept session would also be a stronger credential than an app password |
| A connected Mac, as Dots does | Works because macOS lets an approved app operate other apps and the Mac stays online. iOS has no equivalent. Most of our users have only a phone |
| Android screen reading | Play [prohibits](https://support.google.com/googleplay/android-developer/answer/10964491) using Accessibility to plan and execute actions autonomously. Android only, and too broad for a wallet |
| iPhone Shortcuts | The [Email trigger](https://support.apple.com/guide/shortcuts/communication-triggers-apdd711f9dff/ios) filters by sender, subject, account or recipient and can run without asking. It covers any account in Apple Mail and could hand a mail to a Confío App Intent. iPhone only, set up by hand. **Not tested:** whether the body arrives and how late. A two-day spike on a real iPhone |
| Unified API vendors | [Unipile](https://www.unipile.com/pricing-api/) says its CASA covers customers: from US$55 a month, then US$3–5.50 per account a month. Dearer than CASA and puts mailboxes with a third party |

---

### 4.6 Writing mail

Approved for the pilot on 2026-11-22.

**Discarding mail does not prevent writing.** The mailbox is the store. To answer a mail or a question about the inbox, the server fetches that thread again from Gmail, uses it and drops it.

| | Gmail | iCloud, or any mail without a connection |
|---|---|---|
| Read, search, summarize | `gmail.readonly`, fetched when needed | No. Only what the user pastes or shares |
| Draft | By the assistant, in Confío | By the assistant, in Confío |
| Send | [`gmail.send`](https://developers.google.com/workspace/gmail/api/auth/scopes), **sensitive, no extra CASA**. [Replies stay in their thread](https://developers.google.com/workspace/gmail/api/guides/threads) | Opens the phone's composer filled in ([iOS](https://developer.apple.com/documentation/messageui/mfmailcomposeviewcontroller), [Android](https://developer.android.com/guide/components/intents-common)). The user taps send. No credential |
| Not requested | `gmail.compose`, `gmail.modify`: restricted, only needed for Gmail drafts, labels and archiving | App passwords (4.3) |

- **Eligibility.** Google [approves Gmail scopes](https://developers.google.com/workspace/workspace-api-user-data-developer-policy) for email clients, tools that improve email productivity (it names generative AI summaries) and monitoring that improves the email experience (it names itineraries). A wallet that only mines mail for bills is an uncertain fit. Reading, summarizing and answering in a visible mail feature is a clearer one. Google decides at verification.
- **Every send is confirmed** on a native sheet with the exact sender, recipient, subject and body. A Reply-To that differs from the sender is highlighted. No blind copies, no attachments in v1, no automatic replies.
- **A mail cannot cause a send.** The call that reads a mail can only return text for the draft. Recipients come from the thread's headers or the owner's own words, never from a mail's body.
- **Stored:** the token, message ids, derived needs, and an unsent draft (encrypted, deleted on send or after 24 hours). Mail answers are not written into the support thread staff can read.
- **The others:** Dots (`gmail.modify`, approval rules), Muse (asks before sending by default) and Zapia (drafts and sends) all write. They also keep what they read in history or memory, as Pickle does. For iCloud Dots uses an app password. No built-in iCloud mail connection was found for Muse, Pickle or Zapia.

---

## 5. Processing and storage

| Data | Where it is processed | Stored |
|---|---|---|
| Phone calendar events | Phone | Never |
| Chosen calendar ids | Phone | Keychain, this device only, per user |
| Titles the user ticks for the AI | Our server, then OpenAI, for that request | Never by us. `store: false` at OpenAI, whose abuse-monitoring retention still applies unless zero retention is contracted |
| Reminders | Phone | The OS schedule, with generic text |
| Mail body and attachments (stages 2–3) | Server memory | Never |
| Forwarding address (stage 2) | Server | The random address only, until replaced or revoked |
| Derived need (stages 2–3) | Server | Kind, due date, status and a keyed hash of the mail id. Encrypted: amount, currency, the mail id. Deleted 30 days after the date or on revoke |
| Gmail address, unsent draft (pilot) | Server | Encrypted. The draft is deleted on send or after 24 hours (the sweep runs every 15 minutes) |
| OAuth refresh token (stage 3) | Server | Encrypted under a key of its own (SSM SecureString), never the wallet master key |

Logs carry counts, status and error types, never titles, senders, subjects or provider error bodies.

---

## 6. From need to nudge to action

```
source ──▶ detector ──▶ need (fixed fields) ──▶ nudge ──▶ the owner opens it ──▶ normal confirmed flow
           no tools      kind, date, amount      push or     nothing happens       payment card + sheet,
           no history    never free text         thread      by opening            or the Pagar screen
```

- **Nudge.** A lock-screen-safe push, at most one a day. Since 10d it carries counts by fixed kind ("2 pagos y 1 cita") and today's calendar count, never text from a mail or an event. "No me avises de esto" closes the need.
- **Thread.** A card rendered from the need's fixed fields, pointing at the record by id, as the payment card does. No third-party text becomes a message the model reads on later turns.
- **Action.** The button opens Pagar empty, or asks the owner to paste or scan the code. A payee, key, account or code is never taken from a mail or an event. A `PaymentIntent` starts only from the owner's own scan, paste or words, and the owner signs with Confío Face.
- **Amount.** A detected amount is labelled "según el correo" and is never prefilled.
- **Free and paid.** Noticing, nudging and preparing a one-off payment are free. Recurring execution is a Cuenta inteligente rule the owner signs, whose payee never comes from a mail.

---

## 7. Consent, revoke, delete

| Step | Behaviour |
|---|---|
| Connect | One source at a time, from the assistant's settings. The purpose is shown before the OS or Google prompt |
| Choose | Calendars start unticked |
| Share with AI | A separate, explicit act that names the provider (App Review [5.1.2(i)](https://developer.apple.com/app-store/review/guidelines/)). In stage 1 it is per send, with the exact text on screen |
| Revoke | One button. Clears the choice, cancels reminders. Later stages also stop the watch, revoke the token at Google and delete token and needs at once |
| Permission removed in settings | Treated as a revoke the next time the screen opens |
| Sign-out | Stage 1: clears the choice and every reminder, scheduled or delivered. The same runs when the server ends the session, as after account deletion |
| Account deletion | Later stages: deletes tokens, needs and the forwarding address |
| Accounts | Personal account only, taken from the JWT. Employees and businesses have none |

---

## 8. Injection: mail and events are untrusted input

Anyone can mail a user or invite them to an event.

1. **The reader has no power.** The model call that sees third-party text has no tools, no history, no balance and no account data.
2. **Its output is a closed schema** when it detects needs: enums, numbers and dates, validated, with copy written by our code. An answer or a draft the owner asked for is text, shown as plain text with its sources, never as an action.
3. **No path to a payee.** Third-party text cannot create or change a payee, a payout method, a rule or an intent.
4. **No path to the web.** Nothing from a source reaches web search or a URL fetch, and links are never opened.
5. **Less goes in.** Subscribed calendars and unanswered or declined invitations are excluded (Android exposes no subscription flag, so there only the second holds). Links, emails, long codes and every number are stripped from titles.
6. **Nudges do not vouch.** They say "parece un pago", never that a bill is genuine. A mail that claims to be from Confío is never turned into a nudge.

Remaining risk: a planted event can earn a wrong label. It cannot add an action.

---

## 9. Privacy Policy and store declarations

| Document | Stage 1 (calendar) | Stage 2 (forwarding) | Stage 3 (Gmail, Calendar API) |
|---|---|---|---|
| Privacy Policy | On-device reading, the titles sent on request, OpenAI, no storage, how to revoke | Mail received, what is derived, retention | A Google section with the Limited Use sentence, scopes, deletion, no human access, no training |
| App Privacy | On-device reading is [not "collected"](https://developer.apple.com/app-store/app-privacy-details/). Because the AI provider may retain titles briefly, declare Other User Content, linked, App Functionality | Add Emails or Text Messages | The same |
| Play [Data safety](https://support.google.com/googleplay/android-developer/answer/10787469) | Calendar events: collected, optional, App functionality | Add Emails | The same |
| In the app | Purpose strings and disclosure before the send | Disclosure when the address is created | Disclosure before the Google screen |
| iOS privacy manifest | Add the collected type. EventKit has no required-reason entry | Add email | The same |

Legal text is a draft for counsel and the founder. It must be published before the flag is turned on.

---

## 10. Stage 1 as built

Why this slice: it needs no Google approval and no credential, covers Apple and Google calendars at once, and nudges without a server.

- The phone lists the next 14 days (up to 200 events) from the calendars the user picked.
- "Avísame" schedules a local reminder with generic text.
- The user can tick up to 12 events and send **only those titles**, cleaned. Dates, places, guests and notes are not sent. The model returns a position and one of five kinds.
- It lives in its own sheet, not in the chat thread, because the thread is stored, read by support and replayed to a model that has tools. A thread card follows with the needs record (section 6).

| Piece | Where |
|---|---|
| App | `apps/src/assistant/calendar/`, entry in `MascotPicker.tsx` |
| iOS | `apps/ios/Confio/ConfioCalendar.swift`, `.m`, in every build since 2026-11-24, with both purpose strings in `Info.plist` |
| Android | `ConfioCalendarPackage.kt` in the main source set, `READ_CALENDAR` in the main manifest |
| Server | `assistant/calendar_context.py`, `assistant/calendar_schema.py`, no model or migration |

**On for everyone since 2026-11-24 (founder's decision, ahead of counsel's answer).** `ASSISTANT_CALENDAR_ENABLED = true` in the app and `ASSISTANT_CALENDAR_ALLOWED_USER_IDS` defaults to `'*'`. The switch that remains is the server's: set that name to an empty value in `config/settings.py` (it is still not read from the environment) and the send to OpenAI stops; reading on the phone and the local reminders need a new build to stop.

### Release gates

State on 2026-11-24: 4 is done in code and the Android release variant compiles; 5 was replaced by the `'*'` default. Still open: 1 (counsel has not answered; clause drafted in `docs/drafts/privacy-phone-calendar.md`, not published), 2 (store declarations), 3 (no real-device test of a release build yet) and 7.


1. The founder approves the copy and the send to OpenAI. Counsel updates the Privacy Policy.
2. Update App Privacy, Data safety and the privacy manifest.
3. Test on a real iPhone and a real Android phone with iCloud, Google and invitation events, including revoke and reinstall. On iOS, add the two purpose strings locally first.
4. Remove the iOS Debug guards and add `NSCalendarsFullAccessUsageDescription` and `NSCalendarsUsageDescription`. Move the Android package and `READ_CALENDAR` from debug to main.
5. Read `ASSISTANT_CALENDAR_ALLOWED_USER_IDS` from the environment in `config/settings.py`. It is not wired on purpose.
6. Confirm DEBUG is off wherever real titles are sent (its request log redacts this operation as well).
7. Test group first, then everyone.

---

## 10b. Gmail pilot as built

| Piece | Where |
|---|---|
| Server | `assistant/gmail/`, migration `assistant/0012_gmail_pilot`, sweep every 15 minutes |
| App | `apps/src/assistant/mail/`, entry in `MascotPicker.tsx` |
| Secret | `scripts/ops/gmail_pilot_secret.py` writes `/confio/secrets/prod/gmail-pilot` |

- Off until `GMAIL_PILOT_USER_IDS` lists testers (at most 100, no wildcard), the secret exists, and a build has `ASSISTANT_MAIL_ENABLED = true`.
- Connect uses the system browser. The callback page only hands the code to the app. The exchange needs the signed-in person and a verifier their phone holds, so a forwarded link cannot attach a victim's mailbox to an attacker.
- Background reading fetched only mails matching Gmail's own keyword filter until 10d, which reads everything received except promotions, social and forums: the newest 100 in the window, 20 a run, at most 200 a day, 30 days back at first. A busy first month can therefore miss some. A keyed hash of each mail already read is kept in the cache for 2 days per connection, so none is sent to the model twice. Disconnecting erases the needs, so reconnecting reads them again, inside the per-person daily cap.
- The sweep and the sync run on the analytics worker, never on the money queue: 30 seconds a sync, 20 syncs a sweep, and a task not started within 14 minutes is dropped. Past about 20 active testers each mailbox is read less often than every 15 minutes: give them a worker of their own then.
- A send is built, read back and compared with what was confirmed before it leaves.
- Secrets: codes are masked in every mail before a model sees it. Only a mail whose job is a code or a reset is dropped.
- The "claims to be Confío" rule (section 8) looks at the sender, with look-alike letters folded. A body can still mention Confío.
- The kill switch for the pilot is the tester list. `CONFIO_ASSISTANT_ENABLED` also hides the settings screen that holds Disconnect: while that is off, people disconnect at myaccount.google.com/permissions or through support.
- It lives in its own sheet, outside the support thread. A nudge is one push a day (10d: counts only).
- When two Confío accounts connect the same Gmail, the grant is revoked at Google only when the last one leaves.
- With the pilot off (an empty tester list), disconnecting and deletion keep working and still revoke at Google, as long as `GMAIL_PILOT_SECRET_NAME` stays set.
- **The migration must run before the first restart on this code, pilot or no pilot:** deleting a user cascades into these tables and the sweep queries them.

### Before the first tester

1. Google Cloud, new project `confio-gmail-pilot`, signed in as the owner: enable the Gmail API and the Google Calendar API (10d; the third scope under Data Access is `calendar.events.readonly`). In Google Auth Platform set Branding (Confío, `confio.lat`, privacy URL), Audience External and Testing, add the testers' Gmail addresses, add the three scopes under Data Access, and create a Web client with redirect `https://confio.lat/gmail/connect/callback/`. Do not press Publish or submit for verification.
2. Run the secret script.
3. Publish the Privacy Policy's Google section (section 7 of the 1.15.0 draft) and update the store declarations for any build that ships the flag on.
4. Deploy with the migration first, after the founder's go. `scripts/deployment/deploy_ec2_systemd.sh` continues when `migrate` fails (`|| true`): check that `showmigrations assistant` shows 0012 through 0015 applied before the restart. Set `GMAIL_PILOT_SECRET_NAME=prod/gmail-pilot` and never unset it. Keep the one-time code out of nginx's error log, which records the full request line when the upstream is down (the root `nginx.conf` access log already drops queries):

   ```
   location = /gmail/connect/callback/ {
       access_log off;
       error_log /dev/null crit;
       proxy_pass http://127.0.0.1:8000;
       # All four, as in location /: without X-Real-IP a client could forge its own IP.
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

   Put the block in the repo's root `nginx.conf`, above `location /`, and test it with `nginx -t`: the deploy script copies that file over the server's, so an edit made only on the server is lost at the next deploy. Confirm the application server's own log drops query strings there too.
5. Set `GMAIL_PILOT_USER_IDS`, restart web, `celery`, `celery-analytics` (it runs the pilot's tasks) and `celery-beat`, and test with the owner's own account first.

---

## 11. Rollout, cost and time

Engineering times and run costs are estimates.

| Stage | What | Build | External wait | Outside cost | Run cost per user |
|---|---|---|---|---|---|
| 1 | Phone calendar, reminders, AI on request | Built, 2–4 days to release | App review | None | Under US$0.001 a check |
| 2a, not planned | Forward-all receiver in Zurich, filter, needs record, thread card | About 3 weeks | None | None beyond our servers | About US$0.03–0.05 a month |
| 2b, not planned | Guided setup with connection check for iCloud, and Gmail if the phone test passes | About 1 week | None | None | — |
| 3b, pilot approved | Confirmed sending through Gmail, composer handoff for other mail | About 1 week | Inside the same verification | No extra CASA | Small |
| 3a, pilot approved | Gmail OAuth connect | 3–4 weeks | A test pilot of up to 100 users needs none (consent repeats every 7 days). Public: 8–12 weeks | CASA yearly, about US$675–6,000 plus remediation | About US$0.03–0.15 a month |

Measure per stage: connected, nudge shown, nudge opened, paid after a nudge, revoked, marked wrong. Continue only if nudges are opened and revokes stay low.

---

## 12. Decisions for the founder

Decided on 2026-11-22: the Gmail pilot in section 0.

Each of these still needs a yes before any work that depends on it.

1. Deploy the pilot, and create the test Google project (needs the owner's Google Cloud sign-in, steps in 10b).
2. After the pilot: OAuth verification and the yearly CASA budget.
3. Release stage 1: the copy, the send to OpenAI, the privacy and store changes.
4. Confirm that Confío will not ask for Apple or Google app passwords.

## 10c. Discovery and a full pilot

`assistant/connections.py`, `apps/src/assistant/connections/`. Switch: `ASSISTANT_CONNECTIONS_DISCOVERY_ENABLED` (default off).
Personal accounts only. An older server, or the switch off, shows nothing. Needs an app build.

**Where people see it:** a card among the chat's starters. After "Ahora no" (14 days on that phone) or an answer, a
small "Correo y calendario" chip stays there. The chip, never the card, also appears when, in that opening of the
chat, they ask to read or connect mail or calendar.

| State | When | What they see |
|---|---|---|
| soon | pilot off | Próximamente: "Sí, avísame" / "Solo miraba". No address is asked. |
| request | pilot on, places left | "Pedir un cupo", typing the Gmail to add in Google (also whoever said yes earlier). |
| left | had access and declined | Saliste de la prueba, can ask to be told. |
| waiting | answered yes, or a place reserved | En la lista, and "Salir de la lista". |
| full / waiting_full | 100 given here, or `GMAIL_PILOT_FULL` | Cupos completos, told if it opens to more people. Never a price, never a place for sale. |
| invited | a place given | Connect with that exact address, or decline. An older build says to update. |
| connected / reconnect | connected / 7-day expiry | Open, or reconnect. |
| paused | connected and the pilot is off | Not reading, can disconnect. |

**When the 100 fill and public launch isn't paid for:** those inside keep it (reconnecting every 7 days), everyone
else joins the list. A public launch is verification plus CASA, decided from that list.

**Giving a place:** Django admin, Assistant connection requests. Filter Gmail + yes, oldest first.

1. "Apartar cupo" shows who and which address, and on confirming spends the place and freezes the address. No
   access yet. Only @gmail.com / @googlemail.com are taken.
2. Add exactly that address under "Test users" in the Google project.
3. "Ya lo agregué en Google" asks to confirm, then opens access and sends a generic notice.

Reserved by mistake and never typed into Google: "Deshacer un cupo apartado" frees it, with a confirmation. It is
the only thing that frees a place, and it refuses once step 3 was done. Every grant, removal and undo is in the
row's History with who did it (never the address).

The typed address is erased when they connect. With the pilot off, waiting addresses are kept (no fixed period
until counsel answers question 7 of the privacy draft).

"Quitar acceso" erases the connection. Removing or declining never frees a place, because Google does not free it.
Someone who had access comes back only with "Devolver acceso", which asks to confirm, so a bulk step never readmits who was removed. A reservation that never reached step 3 (a typo, they left) is
asked for the address again, and goes through all three steps on the same place.
The admin only counts places given here, so when Google's console is full set `GMAIL_PILOT_FULL=True` and restart.
"Avisar a quienes esperan" is how "te avisamos" is kept: use it when places open or it opens to everyone.

**Stopping:** empty `GMAIL_PILOT_USER_IDS` stops all Gmail, invited people included. The discovery switch only hides
the card for those without a place.

**Deploy:** migrate and confirm `assistant.0013_connection_requests` in showmigrations before any restart (the deploy
script ignores a failed migrate, and deleting a user needs this table).

**Before switching on:** discovery with the pilot off stores a yes/no only. With the pilot on it stores an address,
which the privacy text has to cover first (the Gmail privacy draft, 1.15.0). Don't give places before a build with the mail
flag on is in the stores: older builds can only say "Actualiza la app".

## 10d. Beyond deadlines, and Google Calendar in the daily notice

Decided by the founder on 2026-11-22: the pilot reads for context, not only for bills, and the daily push counts calendar items too. Built, not deployed; the pilot is still off.

| Change | How |
|---|---|
| Mail read | The keyword filter is gone. Everything received is read except promotions, social, forums, sent, drafts, chats, spam and trash. Same caps: newest 100, 20 a run, 200 a day |
| Kinds | `payment`, `ticket`, `trip`, `deadline` plus `reply`, `appointment`, `delivery`, `money`. Still a fixed list: anything else is dropped |
| Old mail | A need without a date is kept only from a mail of the last 3 days, so the first 30-day read does not surface old letters |
| Summary | One line (90 characters) written by the model, sealed with the need, shown only in the sheet as "Según el correo: …" |
| Calendar | Third, optional scope `calendar.events.readonly` on the same grant. Primary calendar only. `GmailConnection.can_calendar` records whether it was ticked |
| Push | `sync.notice`: "Tienes por atender: 2 pagos y 1 cita. Hoy en tu calendario: 3 eventos." One a day, 07:00 to 21:00 for the person, plus at most one more for something due that same day that arrived later. Counts above 9 read "más de 9". The calendar is counted once, between 07:00 and 11:00; if Google fails, the whole notice waits for the next sweep, for three tries or until 10:00 |
| Sheet | "Hoy y mañana en tu calendario", read from Google when the sheet opens (`showAssistantMailAgenda`) |
| Consent | Version 2, in the app and on the server. A build with the old text cannot connect, and a connection made under version 1 is not read at all (every Google call goes through `session._token`, which refuses it), noticed or shown until the person accepts the new text |

What this changes in the rules above, and what holds them:

- **Section 6 said "never free text".** The summary is the one exception. It never reaches a push, the support thread or a later model call. Numbers are removed in code, with the links, addresses and @handles it detects (`text.strict_line`, which also folds look-alike dots and drops joiners and stray combining marks), so a phone, an account or a code cannot ride in it as digits. Words can still spell one out. It can still be misleading words, which is why the sheet labels it as the mail's claim and keeps the existing warning.
- **Nothing from the calendar is stored or sent to a model.** The push needs a number, so `events_today` returns only a count. The sheet shows titles with links removed, read for that one answer. Only the day of the last count is kept (`calendar_checked_on`).
- **Invitations are untrusted (section 8).** Only events the person organizes and invitations they answered yes or maybe are counted or shown. Cancelled events, unanswered or declined invitations, events where they are not among the guests, birthdays, out-of-office, focus time, working location and events Gmail builds from a mail are left out. Pages are followed (4 of 250, the person's own guest entry only), so it takes more than a thousand earlier events in three days to push a real one out. Titles lose the links, addresses and @handles detected, any five digits in a row unless letters separate them, and every digit when the title holds eight or more (`text.strict_line`). A seven-digit number split by a word, or one spelled out, still passes: the titles are the person's own events or ones they accepted.
- **To check by hand before the first tester:** from a second Gmail account, send an invitation whose API request sets the guest's `responseStatus` to `accepted`. If Google honours that on the guest's copy, `_mine` must stop trusting `accepted` for events the person does not organize.
- **The day is the calendar's own.** Google names the calendar's timezone and the day is computed in it. The hour of the notice still comes from a fixed offset per country, which can be an hour or three off (Chile in winter, the US west coast).
- **The notice is stored like any notification**, with its counts, and is erased on disconnect.
- **Known limits.** Only the newest 100 mails of a window are listed and 200 a day are read, so a sender who floods a mailbox can crowd out a real bill for that day. The first read after connecting pays for up to 100 mails, most of which are dropped as old.
- **Cost and exposure go up.** Every received mail is now sent to the model, not only keyword matches. The 200-a-day cap is the bound. The privacy draft asks counsel whether that needs its own consent.
- **Apple Calendar is not covered** by this route. The phone-calendar slice (section 10) stays as built and off.

Before the first tester, additionally: enable the Calendar API and add the third scope in the Google project (step 1 above), and ship a build whose consent screen is version 2.


## 10e. Self-serve places (2026-11-24)

The founder chose unverified production: the Google project `confio-gmail-pilot` is "In production" without verification, so no address is typed into Google's console. People see Google's "unverified app" screen, and Google itself refuses a 101st account for the project's lifetime.

- `GMAIL_PILOT_SELF_SERVE=True` (with a non-empty `GMAIL_PILOT_USER_IDS`) lets anyone eligible without a place connect while places are left. The admin waitlist steps keep working.
- Opening Google's screen holds a place for 15 minutes (`GmailOAuthState`), under the seats lock, so places are never handed out past what is left. A member (has a place) is never held back: a reconnect always works.
- Google counts every account that consents, even one we then refuse. `GmailGrant` mirrors that count: a keyed hash per Google account, or a random key when the address is unknown, kept forever and not linked to the Confío account. Places left = 100 − max(our places, Google accounts) − open attempts.
- Someone who consented is never refused for capacity: the hold was taken before Google's screen. A place taken away is not taken again by connecting.
- `GMAIL_PILOT_FULL=True` stays the backstop when Google's console shows a higher count than ours.
- The refresh token no longer expires every 7 days (that was Testing mode only).

## 10f. Gmail in the conversation (2026-11-24)

The founder asked for Gmail to work like WhatsApp: no writing or replying on the Gmail screen; everything happens in the Confío IA conversation.

- **Screens.** Gmail and the phone Calendario use the WhatsApp setup design (`apps/src/assistant/connections/SetupScreen.tsx`). The Gmail screen only manages the connection. The calendar screen picks all calendars at once, groups them by account and cleans Android's raw names (`calendar_displayname_local`).
- **Told in the conversation** (`assistant/gmail/chat.py`). A new need from mail of the last two days is posted by code: sender name and subject between «», cleaned of links, addresses and numbers, «» stripped from them; the one-line summary after «Según el correo»; our own kind words. At most six a day. Replay to the model marks them as third parties' words (`engine.GMAIL_PREFIX`). Erased on disconnect and on a mailbox change, under the connection's row lock, so a post racing a disconnect is either erased or never written.
- **A prompt notice.** Each told need also sends a fixed-text push at once ("Tu Gmail trae un pago pendiente. Te lo cuento en Confío IA."), in the person's daytime, at most one an hour; it counts as noticed, so the morning notice does not repeat it. The morning notice stays for the rest and for the calendar.
- **Writing.** The chat model's `prepare_mail` tool, or the "Responder…" chip, puts a mail on a card (`mail_draft`). It leaves only from Enviar, with the display hash. An address counts only if she wrote it whole, or it is the address of the card being changed; links and 3+ digit numbers she never wrote are dropped from her request. A new version deletes the earlier drafts, so only the newest card can be sent. A sender name shared by two addresses is never guessed between.
- **Consent.** Version 2 stays the floor for reading. Version 3 (this build's text) is needed for anything in the conversation; a connection under 2 keeps the daily notice only, and the new app asks again.
- The old in-sheet ask, inbox and draft operations stay on the server for older builds.
