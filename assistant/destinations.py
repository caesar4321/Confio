"""Screens Confio Assistant may open. The app maps each key to its own route.

Keys are a contract with the client (apps/src/assistant/destinations.ts):
add new ones freely, never rename. Old clients ignore keys they don't know.
"""

DESTINATIONS = {
    'home': 'Inicio: saldos de tus billeteras y botones Enviar / Recibir.',
    'pay_qr': 'Pagar: escáner para pagar con un código QR.',
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
    'discover': 'Descubrir: novedades y comunidad.',
    'profile': 'Perfil y configuración.',
    'verification': 'Verificación de identidad (KYC).',
    'cash_directory': 'Directorio de efectivo (casas de cambio y agentes).',
    'messages': 'Mensajes: Julian, Confío News y Confio Assistant.',
    'notifications': 'Notificaciones.',
    'achievements': 'Logros y recompensas.',
    'pending_incoming': 'Dinero por recibir: transferencias a tu cuenta local que esperan tu confirmación con Confío Face.',
    # Paid-offer probes: a pitch with "Sí, avísame". Only offered while each
    # probe is on (users/paid_offers.py); chips are capped by the server.
    'ia_plus': 'Confío IA+: la versión más avanzada de Confío IA que estamos preparando (lista de espera).',
    'cuenta_inteligente': 'Cuenta inteligente: pagos y débitos automáticos que estamos preparando (lista de espera).',
}

# Paid-offer probe keys and the waitlist product each one opens.
PAID_OFFERS = {'ia_plus': 'ia_plus', 'cuenta_inteligente': 'smart_account'}

# Screens only the account owner sees (employees never get bank rails).
OWNER_ONLY = {'receive', 'top_up', 'withdraw', 'pending_incoming', 'month_summary', 'emergency_exit',
              'ia_plus', 'cuenta_inteligente'}
# Screens that only exist for personal accounts.
PERSONAL_ONLY = {'pending_incoming'}
# Keys newer builds open directly. The action also carries this older key, so
# a build that doesn't know the new one still lands on the closest screen.
FALLBACKS = {
    'stock': 'stocks',
    'month_summary': 'home',
    'emergency_exit': 'profile',
    'tokenomics': 'invest',
    'ia_plus': 'home',
    'cuenta_inteligente': 'home',
}
