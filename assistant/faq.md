<!--
Approved answers for Confio Assistant. The model reads everything outside these
comments as true, so:
  - Only write what the app does TODAY on prod. If a switch or provider changes,
    update this file in the same change (notes below say which switch each fact
    depends on).
  - Never put fee amounts, exchange rates, yields or limits here: the app quotes
    them in the flow.
  - Customer-facing Spanish, short. Reviewed by: (pending, Julian/Susy).
Facts verified against main + prod settings on 2026-10-04.
Left out until confirmed: invites to people without Confío (BSC_INVITE_ENABLED
is False), which countries Guardarian serves, documents Didit accepts per
country, P2P and humanitarian screens, presale details, $CONFIO bonus claims.
Support history (418 human threads, 2026-03-14..10-04) was mined for the top
questions; where the team's answers changed over time the latest is used, and
lines from it carry "support:" notes. Never copy team date promises, fee
percentages or per-order caps from support threads.
-->

## Qué es Confío
- Confío es una app de dólares digitales para guardar, enviar, recibir y pagar. Tú controlas tu dinero.
- Confío no ofrece préstamos, créditos ni adelantos de dinero.
- Ninguna opción de ahorro o inversión en Confío tiene ganancias garantizadas.
<!-- support: loans ~120 threads (largest topic), latest 2026-10-04; "what is Confío" ~55 threads. -->

## Países, recargas y retiros
- Puedes crear tu cuenta con un teléfono de casi cualquier país. Recargar y Retirar dependen del país de tu teléfono.
- En Argentina, Bolivia, Brasil, Chile, Colombia, México y Perú, recargas y retiras con medios locales:
  - Argentina: transferencia (recargar y retirar); Khipu y QR interoperable (solo recargar).
  - Bolivia: QR interoperable, solo para recargar. Por ahora no se puede retirar a bolivianos.
  - Brasil: Pix.
  - Chile: transferencia (recargar y retirar); Khipu (solo recargar).
  - Colombia: PSE para recargar; Nequi, Bancolombia, Bre-B o transferencia para retirar.
  - México: transferencia (recargar y retirar).
  - Perú: QR para recargar, transferencia para retirar.
- En otros países, Recargar y Retirar usan un proveedor internacional; la app te muestra si está disponible para ti.
- En Venezuela, Nicaragua, Panamá y Cuba no hay Recargar ni Retirar en la app. En Recibir verás un directorio de financieras para convertir efectivo.
- Venezuela: estamos trabajando para habilitar Pago Móvil. Todavía no tiene fecha; no prometas una.
- Antes de confirmar una recarga o un retiro siempre ves el costo y el tipo de cambio.
- Recargar está dentro de Recibir.
- En recargas por transferencia, primero creas la orden con el monto y luego haces una sola transferencia por exactamente ese monto. No transfieras sin orden ni dividas el pago en varias transferencias.
- Las cuentas desde las que recargas y a las que retiras deben estar a tu nombre. Si otra persona quiere mandarte dinero, que abra su cuenta Confío y te envíe a tu número.
- Si recibes dólares digitales desde un exchange o una billetera externa, usa exactamente la moneda y la red que te muestra la app. Con otra red puedes perder el dinero.
<!-- support: one order = one exact transfer (latest 2026-08-06, 5 threads; multi-transfer cases ended stuck); own-name (2026-09-14); external deposit network warning (2026-09-24; older Algorand instructions are obsolete). -->
- En cuentas de negocio, solo el dueño puede recargar, retirar y gestionar cuentas bancarias.
<!-- Koywe countries: ramps/koywe.py:16-326, apps/.env.mainnet; prod KOYWE_ON_RAMP_PAUSED_COUNTRIES is empty (CO top-ups live, 2026-10-04). Bolivia no off-ramp: ramps/schema.py:1120. No-ramp countries: apps/src/config/env.ts:111. -->

## Cuentas locales a tu nombre
- En Brasil (Pix), Colombia (Llave Bre-B) y México (CLABE) puedes tener una cuenta local a tu nombre para recibir y pagar en moneda local desde tus dólares. En Argentina llegará pronto.
- Brasil: recibes Pix con el QR o los datos bancarios de tu cuenta. Todavía no puedes registrar tu propia clave Pix.
<!-- prod 2026-10-04: BRA FinancialAccounts active with qr + bank_details instructions, no pix-key kind; team said "own Pix key not enabled" 2026-10-03. -->
- Necesitas verificar tu identidad. Por ahora no podemos abrirlas con documento o nacionalidad venezolana.
- Bre-B verifica desde dónde estás (dispositivo y conexión) y no funciona desde Venezuela.
<!-- Infinia: INFINIA_PAYMENT_ACCOUNTS_ENABLED/INFINIA_JOURNEYS_ENABLED True on prod; active EligibilityPolicy blocks AR (credentials pending) and VEN nationality. BREB_LOCATION_ENABLED True. -->

## Verificación de identidad
- Te verificas dentro de la app con tu documento y una selfie. Hace falta para recargar, retirar y abrir cuentas locales.
- Tu nombre y fecha de nacimiento deben coincidir en todos tus documentos.
- Para un límite mayor en cuentas locales se pide un comprobante de domicilio y unas preguntas sobre tus ingresos y el origen de tus fondos.
- Fotografía tu documento original (no una foto de pantalla ni un escaneo) y evita reflejos sobre el holograma.
<!-- support: latest 2026-05-25, 3 threads. -->

## Enviar y pagar
- Enviar a otro usuario de Confío es gratis: Confío paga la comisión de la red.
- La pestaña Pagar lee los QR de cobro de Confío. Si tienes una cuenta local activa, también lee QR Pix, Bre-B o el QR de tu país, y ves el tipo de cambio final antes de confirmar.
- Un negocio cobra con "Cobrar" (un QR de cobro), no con su número.

## Seguridad
- Confío Face (una selfie en vivo) confirma que eres tú cuando mueves dinero.
- Tu billetera se respalda cifrada en tu cuenta personal: Google Drive en Android, llavero de iCloud en iPhone. Si cambias de teléfono, entra con la misma cuenta de Google o Apple.
- La Salida de emergencia, siempre en Perfil, te deja mover tu dinero sin depender de Confío.
- Confío nunca te pide contraseñas, códigos ni frases secretas. Si alguien te los pide, es una estafa.
- No tienes una frase semilla que guardar: si recuperas tu cuenta de Google o Apple, recuperas tu cuenta de Confío.
<!-- FACE_STEP_UP_ENABLED True on prod. Backup: BackupConsentModal.tsx:55-75. Emergency exit: ProfileScreen.tsx:838. -->

## Tus dólares
- Confío Dollar (cUSD): el dólar para el día a día, respaldado 1 a 1 por USDT. No genera rendimiento.
- Confío Dollar+ (cUSD+): el dólar para ahorrar, respaldado por USDY de Ondo (bonos del Tesoro de EE.UU.). Genera rendimiento diario con una tasa variable que ves en la app; no está garantizado.
- Acciones de EE.UU.: acciones digitales emitidas por Ondo.
- Confío Dollar+ y acciones no están disponibles en EE.UU., Canadá, Brasil, la Unión Europea, Reino Unido, Suiza, Singapur, Hong Kong, Malasia y algunos otros países, por requisitos del emisor (Ondo).
- Las recargas nuevas llegan como Confío Dollar+ si está disponible en tu país; si no, como Confío Dollar.
<!-- CUSD_DEPOSITS_PAUSED True; useRampFlows.tsx:39-50 (eligibility decides cUSD+ vs Confío Dollar); CUSD_PLUS_STOCK_TRADING_ENABLED True; eligibility by phone country: cusd_plus/eligibility.py:18-33. -->

## Negocios
- Roles: el dueño puede todo; un admin, todo menos eliminar el negocio; un gerente no gestiona empleados ni edita el negocio; un cajero solo cobra y ve movimientos (no ve el saldo ni envía).
- Nómina paga a personas guardadas que tengan Confío, desde el fondo de nómina del negocio.

## Ayuda
- Puedes pedir hablar con una persona del equipo en este mismo chat. Normalmente responden en unas horas, pero no hay un tiempo garantizado.
- En este chat no se pueden enviar capturas de pantalla. Si ves un error, escribe el mensaje tal como aparece.
- Por ahora Confío no tiene tarjeta de débito.
<!-- No attachment UI in the assistant sheet (2026-10-04); team kept asking for screenshots users could not send. No card code in the repo; team answer 2026-08-07. -->
- La comunidad de Confío está en Telegram: t.me/confio4world. Allí no se atienden casos de cuentas; para eso, este chat.
