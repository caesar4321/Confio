"""Screens Confio Assistant may open. The app maps each key to its own route.

Keys are a contract with the client (apps/src/assistant/destinations.ts):
add new ones freely, never rename. Old clients ignore keys they don't know.
"""

DESTINATIONS = {
    'home': 'Inicio: saldos de tus billeteras y botones Enviar / Recibir.',
    'pay_qr': ('Pagar: escáner para pagar un código QR con la cámara o con una imagen de la galería (por ejemplo '
               'una captura del QR). Úsalo cuando piden pagar un QR ("págame este QR", "paga este Pix"). En Brasil '
               'paga QR Pix de tiendas, apps y personas; si el QR trae monto, se paga exactamente ese monto en '
               'reales. La persona revisa y confirma el pago en esa pantalla: tú nunca pagas.'),
    'send': 'Enviar dinero (a un contacto, a tu propia cuenta bancaria o a otra billetera).',
    'receive': 'Recibir dinero (tu número Confío, cuentas locales y "Recargar ahora").',
    'top_up': 'Recargar: cargar dólares desde tu banco (dentro de Recibir).',
    'withdraw': 'Retirar: enviar dólares a tu propia cuenta bancaria (dentro de Enviar).',
    'invest': 'Invertir: acciones de EE.UU. y preventa de $CONFIO.',
    'stocks': 'Lista de acciones de EE.UU. disponibles.',
    'stock': 'Página de una acción o ETF concreto (precio, gráfico, comprar o vender). Indica cuál en `asset` (ticker o nombre).',
    'month_summary': 'Tu mes: cuánto entró y salió este mes, por categoría y por contacto.',
    'emergency_exit': 'Salida de emergencia: mover el dinero sin depender de la app ni de los servidores de Confío.',
    'tokenomics': 'Tokenomics de $CONFIO: suministro, distribución y liberación (vesting).',
    'presale': 'Preventa de $CONFIO.',
    'discover': 'Comunidad (dentro de Invertir): lo que comparten otros miembros sobre su dinero.',
    'community': 'Comunidad (dentro de Invertir): lo que comparten otros miembros sobre recargas, retiros e inversiones.',
    'comprar': 'Comprar: productos de vendedores verificados de tu ciudad, con pago protegido y envío por Yango.',
    'my_store': 'Mi tienda: abrir tu tienda en Comprar y publicar productos (cuenta personal verificada).',
    'market_orders': 'Mis compras y ventas en Comprar.',
    'profile': 'Perfil y configuración.',
    'verification': 'Verificación de identidad (KYC).',
    'cash_directory': 'Efectivo con un agente (casas de cambio y agentes).',
    'messages': 'Mensajes: Julian, Confío News y Confio Assistant.',
    'notifications': 'Notificaciones.',
    'achievements': 'Logros y recompensas.',
    'pending_incoming': 'Dinero por recibir: transferencias a tu cuenta local que esperan tu confirmación con Confío Face.',
    # Paid offers. Confío IA+ is a pitch with "Sí, avísame". Cuenta inteligente
    # opens the real offer on builds >= SMART_ACCOUNT_MIN_APP_VERSION (it says
    # whether this person may sign) and, on older builds, the subscribe screen
    # for whoever can subscribe and the waitlist pitch otherwise. Chips are
    # capped by the server.
    # Doors the menu and Perfil have, so that everything can be done from the
    # chat (2026-11-22). Each has a FALLBACK for builds that predate it.
    'charge': 'Cobrar: un QR de cobro de Confío con el monto que pongas, para que otro usuario de Confío te pague.',
    'invite': 'Invitar y ganar: invitar por WhatsApp, tu código de invitación y cómo funciona el programa.',
    'commissions': 'Mis comisiones: lo que has ganado por las personas que invitaste.',
    'agenda': 'Agenda: tus cuentas bancarias guardadas y las de las personas a quienes envías.',
    'ramp_history': 'Historial de tus recargas y retiros con el banco.',
    'wallet_dollar': 'Tu dólar (Confío Dollar o Confío Dollar+): su saldo y su historial de movimientos.',
    'wallet_confio': '$CONFIO: tu saldo y su historial.',
    'stocks_activity': 'Mis operaciones: el historial de tus compras y ventas de acciones.',
    'league': 'Liga: el ranking de inversores por ganancias, y los equipos.',
    'community_post': 'Publicar en Comunidad: escribir una publicación tuya.',
    'notification_settings': 'Ajustes de notificaciones: qué avisos recibes.',
    'edit_profile': 'Editar tu perfil (o los datos de tu negocio).',
    'username': 'Cambiar tu @usuario, que también es tu código de invitación.',
    'share_username': 'Compartir mi usuario: tu @usuario con su QR, para que otra persona con Confío te envíe.',
    'memberships': 'Mis instituciones: las instituciones (cooperativas, asociaciones) a las que estás vinculado.',
    'create_business': 'Crear una cuenta de negocio.',
    'payroll': 'Nómina: pagar a tu equipo desde la cuenta del negocio.',
    'employees': 'Empleados: las personas de tu negocio y sus permisos.',
    'terms': 'Términos y condiciones de Confío.',
    'ia_plus': 'Confío IA+: el asistente opera tu Cuenta inteligente por ti; tú confirmas cada cambio.',
    'cuenta_inteligente': ('Cuenta inteligente: cuenta de pago con pagos y transferencias automáticas, inversión '
                           'automática y beneficiario. Abre su pantalla con los planes y si la persona ya puede '
                           'abrirla.'),
}

# Paid-offer probe keys and the waitlist product each one opens.
PAID_OFFERS = {'ia_plus': 'ia_plus', 'cuenta_inteligente': 'smart_account'}

# Screens only the account owner sees (employees never get bank rails).
OWNER_ONLY = {'receive', 'top_up', 'withdraw', 'pending_incoming', 'month_summary', 'emergency_exit',
              'ia_plus', 'cuenta_inteligente', 'ramp_history', 'wallet_dollar', 'wallet_confio', 'edit_profile',
              'share_username'}
# Screens that only exist for personal accounts.
PERSONAL_ONLY = {'pending_incoming', 'my_store', 'invite', 'commissions', 'agenda', 'username', 'memberships',
                 'create_business', 'community_post', 'league', 'stocks_activity'}
# Screens only the owner of a business account has.
BUSINESS_OWNER_ONLY = {'payroll', 'employees'}
# Keys newer builds open directly. The action also carries this older key, so
# a build that doesn't know the new one still lands on the closest screen.
FALLBACKS = {
    'charge': 'home',
    'invite': 'profile',
    'commissions': 'profile',
    'agenda': 'profile',
    'ramp_history': 'home',
    'wallet_dollar': 'home',
    'wallet_confio': 'home',
    'stocks_activity': 'invest',
    # (`discover`, not `community`: a fallback must be a key every build knows.)
    'league': 'discover',
    'community_post': 'discover',
    'notification_settings': 'profile',
    'edit_profile': 'profile',
    'username': 'profile',
    'share_username': 'profile',
    'memberships': 'profile',
    'create_business': 'profile',
    'payroll': 'home',
    'employees': 'profile',
    'terms': 'profile',
    'stock': 'stocks',
    'month_summary': 'home',
    'emergency_exit': 'profile',
    'tokenomics': 'invest',
    'ia_plus': 'home',
    'cuenta_inteligente': 'home',
    'community': 'discover',
    'comprar': 'home',
    'my_store': 'profile',
    'market_orders': 'home',
    # Confío IA+ rule proposal chip (smart_account.assistant_ops.rule_chip):
    # never a `navigate` target the model picks, only attached by the tool.
    # Builds without it land on the Cuenta inteligente door.
    'smart_account_rule': 'cuenta_inteligente',
}
# Keys the app opens that are never a `navigate` choice of the model: only a
# tool attaches them (the Confío IA+ rule proposal chip).
CHIP_ONLY = {'smart_account_rule'}


# What the same keys open in the conversation home, where Inicio is the chat
# itself (docs/designs/ai-assistant-first-redesign.md 7): only the entries
# whose description changes.
CONVERSATION_DESTINATIONS = {
    'home': ('Mi dinero: el menú, con tu saldo total y todas tus billeteras. Inicio es esta misma conversación: '
             'no uses esta clave para "ir a Inicio" o "volver al inicio" (ya está ahí; dilo y no abras nada).'),
    'discover': 'Comunidad: lo que comparten otros miembros sobre su dinero.',
    'community': 'Comunidad: lo que comparten otros miembros sobre recargas, retiros e inversiones.',
    'messages': 'Mensajes: Julian, Confío News y mensajes directos.',
    'profile': 'Perfil y ajustes: tu identidad, seguridad (biometría, PIN, respaldo en la nube) y demás ajustes.',
}
