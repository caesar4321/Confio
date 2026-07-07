# Design System — Confío Website («Radicalmente Normal»)

Source of truth for confio.lat (the `web/` marketing site). The mobile app's own
design laws live in the app codebase and `apps/src/config/theme.ts`; this file
ports that world to the web and governs every visual decision on the site.

## Product Context
- **What this is:** Marketing landing for Confío — LATAM's open wallet for digital dollars (send/receive/save cUSD, cUSD+ savings, US stocks via Ondo, $CONFIO presale).
- **Who it's for:** Spanish-first LATAM users (Venezuela, Argentina, Mexico) battered by inflation and wary of crypto scams; diaspora sending remittances. Mobile-heavy.
- **Space/industry:** LATAM fintech/wallets. Peers: ARQ (ex-DolarApp), Lemon, Nubank, Mercado Pago.
- **Project type:** Marketing site. Its job: trust + app downloads + presale interest.

## The Memorable Thing
"Revolutionary and frontier" — expressed as **radical normalcy**. Confío's
revolution is that dollars, savings, and stocks feel as normal as WhatsApp.
The frontier is shown by the real product working calmly, never by crypto
aesthetics (no dark-noir, no neon, no monospace money, no terminal vibes).
**The website looks like the app because the app is the proof.**

## Aesthetic Direction
- **Direction:** Luminous calm — light, product-true, warm. App-token continuity, elevated craft.
- **Decoration level:** Intentional — flat mint surfaces as soft rounded blocks (like app cards); the only "decoration" is real product UI. No gradients, no blobs, no floating emoji, no icon-in-circle grids.
- **Mood:** A calm, finished, trustworthy money app; confident enough to state the revolution as plain fact («Dólares. Así de simple.»).
- **Reference sites (researched 2026-07-07):** arq/dolarapp.com (went sober-editorial — category leaders abandoned pastel-friendly), lemon.me (acid brutalism — not us), phantom.com / family.co (soft-playful — not us), world.org (austere institutional). Confío's lane: product-true warmth.
- **Anti-direction (explicitly rejected by founder):** dark ink/crypto-noir, neon signal green, monospaced money figures, manifesto-shouting headlines. It "looks so much crypto website" — the opposite of the product's premise.

## Brand / Logo
- **The mark:** `web/src/images/CONFIO.png` — mint C¢ coin on the violet blob. Use it as-is; never recolor, redraw, or flatten it.
- **The lockup:** mark + "Confío" set in Bricolage Grotesque 800, **one single color** (text `#1F2937` on light, `#F9FAFB` on dark, white on emerald). **Never split-color the letters** (no green "ío", no accent-colored characters) — that treatment does not exist in the brand.
- The word may appear alone (headers, footer sig) but always single-color.

## Typography
- **Display/Hero:** Bricolage Grotesque (700–800, tight tracking ~-0.03em) — warm, characterful humanist-bold; friendly without being childish. Replaces Poppins.
- **Body:** Instrument Sans (400–500) — quiet, warm workhorse; not an Inter clone.
- **UI/Labels:** Instrument Sans (600–700).
- **Data/Numbers:** Instrument Sans 700 with `font-variant-numeric: tabular-nums` — matches the app's balance style. **Never monospace for money** (mono re-cryptifies it).
- **Code:** JetBrains Mono (docs/portal only, never marketing surfaces).
- **Loading:** Google Fonts `<link>`: `Bricolage+Grotesque:opsz,wght@12..96,400..800` + `Instrument+Sans:ital,wght@0,400..700;1,400`. Full Spanish diacritics required.
- **Scale:** hero clamp(2.6rem→4.3rem) / section clamp(1.8rem→2.7rem) / subtitle 1.15rem / body 17px (1.0625rem) / small 0.85rem / caption 0.78rem. Line-height: headings 1.02–1.1, body 1.6.

## Color
- **Approach:** Restrained-balanced, tokens 1:1 with `apps/src/config/theme.ts`.
- **Primary:** `#34D399` (emerald-400) — brand, money, positivity. CTA fill: `#10B981` (emerald-500). Deep text-on-mint: `#064E3B`.
- **Mint surfaces:** `#ECFDF5` (blocks/kickers), `#D1FAE5` (emphasis).
- **Secondary:** `#8B5CF6` violet — **appears ONLY next to $CONFIO token content** (same law as the app). Never as generic decoration. **One recorded exception (founder decision 2026-07-07):** the Business pricing card in the fee section keeps its violet theme as deliberate differentiation from the free personal plan.
- **Accent:** `#3B82F6` blue — informational only, sparingly.
- **Neutrals:** bg `#FFFFFF`, surface `#F9FAFB`, surface-2 `#F3F4F6`, border `#E5E7EB`, text `#1F2937`, secondary `#6B7280`, tertiary `#9CA3AF`.
- **Semantic:** success `#10B981` on `#ECFDF5`; warning `#92400E` on `#FEF3C7`; error `#991B1B` on `#FEE2E2`; info `#3B82F6` on `#DBEAFE`.
- **Dark mode («modo noche»):** optional, app-like not noir — bg `#111827`, surface `#1F2937`, border `#374151`, same emerald, violet lightened to `#A78BFA`, text `#F9FAFB`.

## Spacing
- **Base unit:** 4px (app grid).
- **Density:** spacious in marketing sections, comfortable in UI fragments.
- **Scale:** xs(4) sm(8) md(12) lg(16) xl(20) xxl(24) xxxl(32) — plus section padding 76px desktop / 48px mobile.

## Layout
- **Approach:** Hybrid — disciplined grid, hero is product-forward (headline left, real app screenshot right in a device frame).
- **Grid:** 12-col desktop, single column <760px. Max content width 1160px.
- **Border radius:** app scale — sm 8, md 12, lg 16, xl 24, pill 999 (buttons are pills, like app quick actions). Phone frame 44/32.
- **Sections mirror the app's IA:** Enviar · Recibir/Cobrar · Ahorrar (cUSD+) · Negocios — each shown with a real UI fragment or screenshot, never an icon in a colored circle.
- **Hero rule:** the real app screenshot (current demo build) is the hero image. No illustrations, no stock photos, no 3D renders. Keep screenshots current with the shipped app.

## Motion
- **Approach:** Intentional. One signature: **tick-settle** — money figures roll in softly (~1.2s ease-out cubic, IntersectionObserver-triggered once) and settle with a brief emerald pulse. It embodies the product promise (the visible daily savings tick).
- Everything else: native-feeling micro-transitions (150–250ms). No scroll-jacking, no parallax, no floating/looping animations.
- **Easing:** enter ease-out, exit ease-in, move ease-in-out. **Duration:** micro 50–100ms, short 150–250ms, medium 250–400ms, tick-settle 1200ms.

## Voice & Copy Rules
- Spanish-first; calm declarative confidence («Dólares. Así de simple.»), never manifesto-shouting, never crypto jargon on marketing surfaces.
- **Money amounts display as `US$` (US$52,642), never bare `$`** — MXN, ARS, CLP, COP all write their own peso as "$", so a bare "$" is ambiguous for the LATAM audience. Token tickers ($cUSD, $CONFIO, $cUSD+) keep their `$` prefix — they are names, not amounts.
- **Number separators: fixed `en-US` grouping (1,234,567), no geo-detection.** The website can't know the visitor's country reliably (unlike the app, which uses the phone country code), and IP-based locale adds infra for marginal gain. Mitigation: **marketing stats are whole dollars only** (no cents except the literal US$0.00) — without decimals, three-digit groups can't be misread as decimals in comma-decimal countries (AR/CL/CO/VE).
- **No beta/waiting-list framing.** The app is live (2026): no "beta exclusiva", "acceso temprano", "lista de espera". The product speaks in the present tense.
- Traction numbers must be real and live (deposited volume, presale raised, users). Fake or stale counters are worse than none. **No hardcoded fallback snapshots client-side** — a stat without live data simply doesn't render.
- No hardcoded rates/fees/APY in copy — server-quoted values only (same law as the app).
- Hashtags when sharing: #Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital (exactly these 5).

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-07 | Initial system created by /design-consultation | Research (ARQ, Lemon, Phantom, Family, World) + founder brief |
| 2026-07-07 | Crypto-noir direction («La Frontera») rejected by founder | "Looks so much crypto website" — contradicts the app's hide-the-crypto premise |
| 2026-07-07 | «Radicalmente Normal» approved | Revolutionary = radical normalcy; site inherits app tokens 1:1 |
| 2026-07-07 | Hero must use real app screenshots | Founder request; the product is the proof |
| 2026-07-07 | Two-tone wordmark ("Conf"+green "ío") rejected | Not the brand — lockup is the CONFIO.png mark + single-color "Confío" text |

Preview artifact: `~/.gstack/projects/caesar4321-Confio/designs/design-system-20260707/radicalmente-normal-preview.html`
