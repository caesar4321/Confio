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
country, P2P and humanitarian screens.
-->

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
- Antes de confirmar una recarga o un retiro siempre ves el costo y el tipo de cambio.
- En cuentas de negocio, solo el dueño puede recargar, retirar y gestionar cuentas bancarias.
<!-- Koywe countries: ramps/koywe.py:16-326, apps/.env.mainnet; prod KOYWE_ON_RAMP_PAUSED_COUNTRIES is empty (CO top-ups live, 2026-10-04). Bolivia no off-ramp: ramps/schema.py:1120. No-ramp countries: apps/src/config/env.ts:111. -->

## Cuentas locales a tu nombre
- En Brasil (Pix), Colombia (Llave Bre-B) y México (CLABE) puedes tener una cuenta local a tu nombre para recibir y pagar en moneda local desde tus dólares. En Argentina llegará pronto.
- Necesitas verificar tu identidad. Por ahora no podemos abrirlas con documento o nacionalidad venezolana.
- Bre-B verifica desde dónde estás (dispositivo y conexión) y no funciona desde Venezuela.
<!-- Infinia: INFINIA_PAYMENT_ACCOUNTS_ENABLED/INFINIA_JOURNEYS_ENABLED True on prod; active EligibilityPolicy blocks AR (credentials pending) and VEN nationality. BREB_LOCATION_ENABLED True. -->

## Verificación de identidad
- Te verificas dentro de la app con tu documento y una selfie. Hace falta para recargar, retirar y abrir cuentas locales.
- Tu nombre y fecha de nacimiento deben coincidir en todos tus documentos.
- Para un límite mayor en cuentas locales se pide un comprobante de domicilio y unas preguntas sobre tus ingresos y el origen de tus fondos.

## Enviar y pagar
- Enviar a otro usuario de Confío es gratis: Confío paga la comisión de la red.
- La pestaña Pagar lee los QR de cobro de Confío. Si tienes una cuenta local activa, también lee QR Pix, Bre-B o el QR de tu país, y ves el tipo de cambio final antes de confirmar.
- Un negocio cobra con "Cobrar" (un QR de cobro), no con su número.

## Seguridad
- Confío Face (una selfie en vivo) confirma que eres tú cuando mueves dinero.
- Tu billetera se respalda cifrada en tu cuenta personal: Google Drive en Android, llavero de iCloud en iPhone. Si cambias de teléfono, entra con la misma cuenta de Google o Apple.
- La Salida de emergencia, siempre en Perfil, te deja mover tu dinero sin depender de Confío.
- Confío nunca te pide contraseñas, códigos ni frases secretas. Si alguien te los pide, es una estafa.
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
- La comunidad de Confío está en Telegram: t.me/confio4world. Allí no se atienden casos de cuentas; para eso, este chat.
