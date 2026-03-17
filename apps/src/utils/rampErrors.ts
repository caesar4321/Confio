export const getFriendlyRampError = (rawError?: string | null): string => {
  const message = (rawError || '').trim();
  const normalized = message.toLowerCase();

  if (!message) {
    return 'Inténtalo nuevamente en unos segundos.';
  }

  if (
    normalized.includes('qr data not available from bind') ||
    (normalized.includes('bind') && normalized.includes('qr'))
  ) {
    return 'No pudimos generar el QR interoperable en este momento. Prueba con transferencia bancaria o intenta de nuevo más tarde.';
  }

  if (normalized.includes('payment method is restricted')) {
    return 'Este medio de pago no está disponible por el momento. Prueba con otro método.';
  }

  if (normalized.includes('invalid address')) {
    return 'No pudimos preparar la compra por un problema con la dirección de destino. Inténtalo de nuevo en unos segundos.';
  }

  if (normalized.includes('koywe credentials are not configured')) {
    return 'El servicio de compra y retiro no está disponible temporalmente. Inténtalo más tarde.';
  }

  return message;
};
