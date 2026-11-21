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
    'ia_plus': 'Confío IA+: el asistente opera tu Cuenta inteligente por ti; tú confirmas cada cambio.',
    'cuenta_inteligente': ('Cuenta inteligente: cuenta de pago con pagos y transferencias automáticas, inversión '
                           'automática y beneficiario. Abre su pantalla con los planes y si la persona ya puede '
                           'abrirla.'),
}

# Paid-offer probe keys and the waitlist product each one opens.
PAID_OFFERS = {'ia_plus': 'ia_plus', 'cuenta_inteligente': 'smart_account'}

# Screens only the account owner sees (employees never get bank rails).
OWNER_ONLY = {'receive', 'top_up', 'withdraw', 'pending_incoming', 'month_summary', 'emergency_exit',
              'ia_plus', 'cuenta_inteligente'}
# Screens that only exist for personal accounts.
PERSONAL_ONLY = {'pending_incoming', 'my_store'}
# Keys newer builds open directly. The action also carries this older key, so
# a build that doesn't know the new one still lands on the closest screen.
FALLBACKS = {
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
