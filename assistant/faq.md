<!--
Approved answers for Confio Assistant. The model reads everything outside these
comments as true, so:
  - Only write what the app does TODAY on prod. If a switch or provider changes,
    update this file in the same change (notes below say which switch each fact
    depends on).
  - Fees: only Confío's OWN published fees (whitepaper §10) belong here. Never
    provider fees, exchange rates, yield rates or limits: the app quotes them in
    the flow.
  - Founder, fees and $CONFIO sections added 2026-10-05 from README, whitepaper
    and tokenomics v3.1; the full documents are also readable by the model
    (read_public_document), so keep docs/ current too.
  - Customer-facing Spanish, short. Reviewed by: (pending, Julian/Susy).
Facts verified against main + prod settings on 2026-10-04.
Left out until confirmed: invites to people without Confío (BSC_INVITE_ENABLED
is False), which countries Guardarian serves, documents Didit accepts per
country, P2P and humanitarian screens, $CONFIO bonus/reward claims.
Support history (418 human threads, 2026-03-14..10-04) was mined for the top
questions; where the team's answers changed over time the latest is used, and
lines from it carry "support:" notes. Never copy team date promises, fee
percentages or per-order caps from support threads.
-->

## Qué es Confío
- Confío es una app de dólares digitales para guardar, enviar, recibir y pagar. Tú controlas tu dinero.

## Lo que Confío no ofrece (dilo solo cuando pregunten por eso)
- Confío no ofrece préstamos, créditos ni adelantos de dinero.
- Ninguna opción de ahorro o inversión en Confío tiene ganancias garantizadas.
<!-- support: loans ~120 threads (largest topic), latest 2026-10-04; "what is Confío" ~55 threads. -->

## Quién está detrás de Confío
- Confío fue fundada por Julian Moon, de Corea del Sur, graduado de la Universidad Yonsei. Programador autodidacta, creó en 2019 la app Duende (empresa Duende Limited) y luego la renombró Confío, que significa "yo confío".
- Empezó al ver cómo la hiperinflación en Venezuela dejaba a la gente sin poder comprar comida ni gasolina: quiso que los dólares digitales sirvieran a las personas.
- Julian explica Confío en español en redes sociales (en TikTok: @julianmoonluna), con una audiencia de unas 480.000 personas.
- Confío es de código abierto: la app, el servidor y los contratos están publicados en GitHub (github.com/caesar4321/Confio) y los contratos están verificados en BscScan.
<!-- README.md, docs/whitepaper/README.md §9.2 (480k, dated), users/Confio_Frequently_Asked_Questions.py (bio, 2019 Duende, rebrand, Venezuela motivation). -->

## Por qué confiar en Confío
- Tu dinero lo controlas tú: las claves de tu billetera están en tu teléfono y en el respaldo de tu propia cuenta de Google o Apple; Confío no las tiene. Cada envío lo firmas tú: Confío no puede firmar movimientos desde tu billetera.
- Si algún día la app o los servidores de Confío no funcionaran, la Salida de emergencia en Perfil te deja mover tu dinero sin depender de ellos.
- Para mover tu dinero siempre confirmas tú, con tu huella o Confío Face.
- Todo es público y verificable: el código de la app, el servidor y los contratos está en GitHub, y los contratos están verificados en BscScan.
- Confío Dollar está respaldado 1 a 1 por USDT, y Confío Dollar+ por USDY de Ondo, respaldado por bonos del Tesoro de EE.UU.
- Julian Moon da la cara: su nombre, su historia y su rostro son públicos, construye la app desde 2019 y la explica en español en redes sociales ante una audiencia de unas 480.000 personas.
- Si preguntan si Confío puede congelar o bloquear su dinero: los contratos de Confío Dollar y Confío Dollar+ tienen controles de emergencia que solo puede usar la tesorería multifirma de Confío: pausar o congelar una dirección (por ejemplo ante un hackeo o una orden legal) y actualizar el código de esos contratos. Todo lo que hace la multifirma queda público en BscScan. Mientras un contrato esté en pausa, tampoco funciona la Salida de emergencia.
<!-- Contracts: CusdPlusVault.sol freezeAddress/pause (redeemToUsdt is whenNotPaused; frozen holder cannot burn), CusdVault.sol pause; both UUPS, owner = the Safe. See the "narrow and honest" note at CusdPlusVault.sol:214. Never claim Confío "cannot touch" funds: UUPS upgrade authority could rewrite balances. 7702 delegate needs the EOA's own signature (ConfioBatchDelegate.execute), so "cannot sign from your wallet" holds. Keys: device + user's Drive/iCloud backup (app-key encrypted, apps/src/services/secureDeterministicWallet.ts APP_BACKUP_KEY), so never say "solo contigo". -->
<!-- Julian 2026-10-06: trust answers were reading as pessimistic ("no puedo garantizar que Confío sea confiable", founder's 89.36% $CONFIO brought up unasked). Lines restate facts elsewhere in this file, except the emergency-controls bullet (from the vault contracts, noted below); keep every line verifiable in code. -->

## Comisiones de Confío (dilas solo cuando pregunten qué cobra Confío, cuánto cuesta o por qué reciben menos)
- Regla de Confío: 0,9% al entrar, 0% al moverte dentro, 0,9% al salir.
- Entrar (0,9%): todo dinero que llega a Confío desde fuera: una recarga, un depósito de USDT y también el dinero que te envían a tu cuenta local (Pix, Bre-B, CLABE).
- Salir (0,9%): todo dinero que sale de Confío: un retiro, un envío a una billetera externa y cualquier envío o pago en moneda local, en cualquier país (desde tu cuenta local o pagando un QR local en Pagar). Es el mismo 0,9% en todos los países; esto no significa que cada medio esté disponible en tu país.
- Gratis dentro de Confío: enviar dinero a otro usuario de Confío o recibir un envío de otro usuario, y pasar entre Confío Dollar y Confío Dollar+. Confío paga la comisión de la red. (Un negocio que cobra con Confío Pay sí paga su 0,9%: ver Pagos a comercios.)
- Nunca digas que recibir en una cuenta local (Pix, Bre-B, CLABE) es gratis: ese dinero entra a Confío y lleva el 0,9%.
- Pagos a comercios (Confío Pay): 0,9% que paga el comercio, no quien paga. Nómina: 0,9% que paga el negocio.
- Acciones: 0,30% de Confío en cada compra y venta.
- Confío Dollar+: Confío se queda con el 15% del rendimiento positivo; el 85% es para ti.
- El proveedor local de recarga o retiro puede cobrar aparte, y el tipo de cambio varía: el costo final siempre lo ves antes de confirmar.
- Solo si la persona compara Confío con otras apps o dice que otras son gratis o dan mejor cambio: muchas apps que dicen "gratis" cobran igual, pero dentro del tipo de cambio, y no se ve. Confío no le suma un margen propio al tipo de cambio: cobra una comisión a la vista (0,9% al entrar y 0,9% al salir). El tipo de cambio lo pone el proveedor local y antes de confirmar ves el monto final. Para comparar de verdad, mira cuánto llega al final en cada app con el mismo monto. Nunca nombres otra app ni digas cuánto cobra una app concreta, y no digas que Confío no tiene ningún costo escondido: el tipo de cambio del proveedor también tiene su margen.
<!-- Julian 2026-10-10, after user 9313 ("otras apps me ofrecen lo mismo y gratis"). Verified: no Confío markup on Koywe quotes (ramps/koywe_client.py); Infinia's rate carries Infinia's own spread (payment_accounts/infinia_fees.py). -->
<!-- docs/whitepaper/README.md §10 (pricing rule, merchant/payroll 0.9%, stocks 0.30%, 15/85 yield share). Provider fees and FX are never quoted. -->

## $CONFIO
- $CONFIO es el token de Confío en BNB Smart Chain, con suministro fijo de 1.000.000.000 (mil millones): no se pueden crear más. El único contrato oficial es 0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8; cualquier otro es falso.
- Distribución: preventa pública 74 millones (7,4%); recompensas por referidos y uso 7,4 millones (0,74%); Fondo de Invitación Cultural 15 millones (1,5%, se libera en 90 días); co-creador creativo 10 millones (1%, en 24 meses); fundador Julian Moon 893,6 millones (89,36%, en 36 meses). Las liberaciones son lineales desde su activación.
- Preventa: precio continuo en dólares que sube de US$0,20 a US$1,30 según cuántos tokens se han vendido (sin fases), y se paga con cUSD. Lo comprado queda bloqueado hasta el lanzamiento oficial en un exchange descentralizado (DEX); antes no se puede reclamar ni transferir.
- La preventa no está disponible para residentes de EE.UU. ni para ciudadanos o residentes de Corea del Sur.
- Estado en BNB Smart Chain (verificado el 5 de octubre de 2026): las bóvedas de vesting del fundador, del co-creador y del Fondo de Invitación Cultural ya tienen sus tokens depositados y sus asignaciones registradas, pero ninguna liberación ha empezado ni se ha retirado nada. Hasta que se active cada una, la tesorería multifirma de Confío todavía puede cancelarla y recuperar esos tokens; una vez activada ya no se puede cancelar, aunque la tesorería sí puede cambiar a quién va dirigida en cualquier momento.
- $CONFIO no respalda tus dólares, no es una acción de la empresa y no da derecho a ganancias. Su precio futuro no está garantizado y puede bajar.
- Para más detalle (vesting, riesgos, contratos), el documento de tokenomics y el whitepaper están en GitHub.
<!-- docs/tokenomics/README.md v3.1 (2026-09-23): §2 supply/contract, §3 allocation, §4 curve, §4.7 eligibility, §8 founder vesting. Old contract 0xd57B… burned. Never say whether buying is a good idea.
On-chain 2026-10-05 (cast, bsc-dataseed): grants(Safe 0xF29A…b623) = allocated 893.6M/10M/15M, claimed 0, start 0, duration 36/24/3 months on vaults 0xb873…, 0xF32A…, 0x86c2… (balances = totalOwed). Revocable before start (revokeGrant + withdrawSurplus); changeBeneficiary has NO start check, so the Safe can reassign even a started grant. Never call it a lock. Tokenomics v3.2 (2026-10-05) states the same. Re-check, and update both, when a GrantStarted happens. -->

## Países, recargas y retiros
- Puedes crear tu cuenta con un teléfono de casi cualquier país. Recargar y Retirar dependen del país de tu teléfono.
- En Argentina, Bolivia, Brasil, Chile, Colombia, México y Perú, recargas y retiras con medios locales:
  - Argentina: transferencia (recargar y retirar); Khipu y QR interoperable (solo recargar).
  - Bolivia: QR interoperable, solo para recargar: en Recargar eliges el monto y la app genera un QR para esa orden, que pagas desde la app de tu banco o billetera. Por ahora no se puede retirar a bolivianos.
  - Brasil: Pix.
  - Chile: transferencia (recargar y retirar); Khipu (solo recargar).
  - Colombia: PSE para recargar; Nequi, Bancolombia, Bre-B o transferencia para retirar.
  - México: transferencia (recargar y retirar).
  - Perú: QR para recargar, transferencia para retirar.
- En otros países, Recargar y Retirar usan un proveedor internacional; la app te muestra si está disponible para ti.
- En Venezuela, Nicaragua, Panamá y Cuba hoy no hay Recargar ni Retirar en la app. No digas que ahí se puede recargar o retirar con medios locales.
- Venezuela: recargar y retirar con Pago Móvil llegará muy pronto. No des una fecha.
- En todos los países, en Recibir hay un directorio de efectivo (casas de cambio y agentes) para convertir dólares en efectivo o efectivo en dólares.
<!-- Julian 2026-10-09: Pago Móvil "coming very soon" (was: no date); the cash directory is for every country, not only the no-ramp ones. -->
- Antes de confirmar una recarga o un retiro siempre ves el costo y el tipo de cambio.
- Recargas en tu moneda local (soles, pesos, bolivianos, reales): no necesitas cambiar a dólares en tu banco antes. Confío convierte al recargar y ves el tipo de cambio antes de confirmar. Si tienes efectivo, primero ponlo en tu cuenta o billetera local en tu moneda y desde ahí recargas.
- Recargar está dentro de Recibir.
- En recargas por transferencia, primero creas la orden con el monto y luego haces una sola transferencia por exactamente ese monto. No transfieras sin orden ni dividas el pago en varias transferencias.
- Las cuentas desde las que recargas y a las que retiras deben estar a tu nombre. Si otra persona quiere mandarte dinero, que abra su cuenta Confío y te envíe a tu número.
- "QR para recibir": si quiere poner su propio dinero, en Bolivia Recargar le genera un QR para cada orden (lo paga desde su banco o billetera). Si quiere que otra persona le envíe, comparte su número Confío (está en Recibir); las cuentas personales no tienen un QR para recibir de otros. Los negocios cobran con un QR desde Cobrar.
- Si recibes dólares digitales desde un exchange (como Binance) o una billetera externa, usa exactamente la moneda y la red que te muestra la app en Recibir: BNB Smart Chain (BEP20). Al retirar desde Binance u otro exchange, elige esa red; otras redes como Ethereum (ERC20), Tron (TRC20), Polygon o Arbitrum no llegan a Confío.
- Si ya se envió por otra red, Confío no puede verlo ni moverlo desde la app; dilo con claridad, sin prometer una recuperación ni sugerir que otro soporte (Binance u otro exchange) pueda recuperarlo. Lo útil es cómo enviar bien la próxima vez.
<!-- support: one order = one exact transfer (latest 2026-08-06, 5 threads; multi-transfer cases ended stuck); own-name (2026-09-14); external deposit network warning (2026-09-24; older Algorand instructions are obsolete). -->
- En cuentas de negocio, solo el dueño puede recargar, retirar y gestionar cuentas bancarias.
<!-- Koywe countries: ramps/koywe.py:16-326, apps/.env.mainnet; prod KOYWE_ON_RAMP_PAUSED_COUNTRIES is empty (CO top-ups live, 2026-10-04). Bolivia no off-ramp: ramps/schema.py:1120. No-ramp countries: apps/src/config/env.ts:111. -->

## Cuentas locales a tu nombre
- En Brasil (Pix), Colombia (Llave Bre-B) y México (CLABE) puedes tener una cuenta local a tu nombre para recibir y pagar en moneda local desde tus dólares, vivas donde vivas: no hace falta tener teléfono de ese país (por ejemplo, desde Bolivia puedes abrir una cuenta Pix de Brasil). Con ella puedes recibir de cualquier persona y enviar a la cuenta de otra persona en ese país. En Argentina llegará pronto.
- {local_account_fee}
<!-- Julian 2026-10-10: anyone can open them. The fee line is filled from payment_accounts.activation.FEE (prompts.faq_text), so a policy change is one constant. Mesa de pagos may make openings free. -->
- Brasil: puedes tener tu propia chave Pix para recibir de cualquier persona, y enviar Pix a la chave de otra persona. También puedes recibir con el QR o los datos bancarios de tu cuenta.
- En cuentas personales, cuando otra persona te envía dinero a tu cuenta local, llega a tu saldo cuando confirmas con Confío Face que eres tú. Una sola confirmación recibe todo lo pendiente. Si no lo confirmas en 24 horas, se devuelve automáticamente a quien lo envió.
<!-- Julian 2026-10-04: own chave Pix for third-party send/receive enabled, gated by Confío Face (earlier caution was fraud-driven; the team's 2026-10-03 "not enabled" is superseded). Code: LocalReceiveScreen pix_key, LocalSendScreen br_pix, payin_hold.needs_face (personal accounts, 24h return), PendingIncomingScreen copy. Prod: explicit-grant countries empty, BR switches enabled. -->
- Necesitas verificar tu identidad. Por ahora no podemos abrirlas con documento o nacionalidad venezolana.
- Bre-B verifica desde dónde estás (dispositivo y conexión) y no funciona desde Venezuela.
<!-- Infinia: INFINIA_PAYMENT_ACCOUNTS_ENABLED/INFINIA_JOURNEYS_ENABLED True on prod; active EligibilityPolicy blocks AR (credentials pending) and VEN nationality. BREB_LOCATION_ENABLED True. -->

## Verificación de identidad
- Te verificas dentro de la app con tu documento y una selfie. Hace falta para recargar, retirar y abrir cuentas locales.
- Tu nombre y fecha de nacimiento deben coincidir en todos tus documentos.
- Si no tienes un documento del país de tu teléfono, puedes verificarte con tu pasaporte o un documento de otro país. Algunas funciones lo aceptan y otras (como recargar y retirar) piden el del país de tu teléfono: la app te dice cuál necesitas.
<!-- Julian 2026-10-06: an unfinished attempt stays "pending"; many verify with a second document instead. all_documents readers: rewards, community, Face step-up, Bolivia QR (ramps/stereum_customers.py); Recargar/Retirar read the primary only (User.is_identity_verified). Never nag about a pending attempt when any document is verified. -->
- Para un límite mayor en cuentas locales se pide un comprobante de domicilio y unas preguntas sobre tus ingresos y el origen de tus fondos.
- Si tu documento venció, la verificación deja de valer: verifícate de nuevo con un documento vigente.
- Fotografía tu documento original (no una foto de pantalla ni un escaneo) y evita reflejos sobre el holograma.
<!-- support: latest 2026-05-25, 3 threads. -->

## Enviar y pagar
- Enviar a otro usuario de Confío es gratis: Confío paga la comisión de la red.
- La pestaña Pagar lee los QR de cobro de Confío. Si tienes una cuenta local activa, también lee QR Pix, Bre-B o el QR de tu país, y ves el tipo de cambio final antes de confirmar.
- Un negocio cobra con "Cobrar" (un QR de cobro), no con su número.

## Seguridad
- Confío Face (una selfie en vivo) confirma que eres tú cuando mueves dinero.
- Tu billetera se respalda en tu cuenta personal: Google Drive en Android, llavero de iCloud en iPhone. Protege bien esa cuenta (contraseña fuerte y verificación en dos pasos): quien entre en ella podría recuperar tu billetera. Si cambias de teléfono, entra con la misma cuenta de Google o Apple.
- La Salida de emergencia, siempre en Perfil, te deja mover tu dinero sin depender de la app ni de los servidores de Confío.
- Confío nunca te pide contraseñas, códigos ni frases secretas. Si alguien te los pide, es una estafa.
- No tienes una frase semilla que guardar: si recuperas tu cuenta de Google o Apple, recuperas tu cuenta de Confío.
<!-- FACE_STEP_UP_ENABLED True on prod. Backup: BackupConsentModal.tsx:55-75. Emergency exit: ProfileScreen.tsx:838. -->

## Tus dólares
- Confío Dollar (cUSD): el dólar para el día a día, respaldado 1 a 1 por USDT. No genera rendimiento.
- Confío Dollar+ (cUSD+): el dólar para ahorrar, respaldado por USDY de Ondo (bonos del Tesoro de EE.UU.). Genera rendimiento diario con una tasa variable que ves en la app; no está garantizado.
- Acciones de EE.UU.: acciones digitales emitidas por Ondo.
- Monto mínimo: desde US$1,01 para comprar cualquier acción o ETF de la lista (igual para todas) y US$1 para vender.
- Ahorrar e invertir son distintos: Confío Dollar+ es ahorro (rendimiento diario variable, el saldo no sube y baja como una acción); las acciones y ETF son inversión (su precio sube y baja y puedes perder). Pasar dinero a Confío Dollar+ o de vuelta a Confío Dollar es desde US$1. Confío Dollar no tiene monto mínimo.
<!-- ConvertSavingsScreen / WithdrawSavingsScreen MIN_AMOUNT_USD = 1; BuyStockScreen 1.01. -->
<!-- apps/src/screens/BuyStockScreen.tsx MIN_AMOUNT_USD 1.01 (leaves $1 net after 30 bps); SellStockScreen 1. -->
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
