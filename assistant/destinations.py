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
    'presale': 'Preventa de $CONFIO.',
    'discover': 'Descubrir: novedades y comunidad.',
    'profile': 'Perfil y configuración.',
    'verification': 'Verificación de identidad (KYC).',
    'cash_directory': 'Directorio de efectivo (casas de cambio y agentes).',
    'messages': 'Mensajes: Julian, Confío News y Confio Assistant.',
    'notifications': 'Notificaciones.',
    'achievements': 'Logros y recompensas.',
    'pending_incoming': 'Dinero por recibir: transferencias a tu cuenta local que esperan tu confirmación con Confío Face.',
}

# Screens only the account owner sees (employees never get bank rails).
OWNER_ONLY = {'receive', 'top_up', 'withdraw', 'pending_incoming'}
# Screens that only exist for personal accounts.
PERSONAL_ONLY = {'pending_incoming'}
