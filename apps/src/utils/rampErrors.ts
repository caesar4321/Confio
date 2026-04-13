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

  if (
    normalized.includes('the active account does not have a destination wallet address configured')
  ) {
    return 'No pudimos preparar la compra por un problema con la dirección de destino. Inténtalo de nuevo en unos segundos.';
  }

  if (
    normalized.includes('invalid address') &&
    normalized.includes('different country than the document')
  ) {
    return 'No pudimos preparar la compra porque los datos del perfil no coinciden con el país de la operación. Revisa tu documento y país e inténtalo de nuevo.';
  }

  if (normalized.includes('koywe credentials are not configured')) {
    return 'El servicio de compra y retiro no está disponible temporalmente. Inténtalo más tarde.';
  }

  if (
    normalized.includes('bankcode not valid nequi') ||
    (normalized.includes('nequi') && normalized.includes('bankcode not valid'))
  ) {
    return 'Nequi todavía no está habilitado para retiros en este ambiente. Puedes intentar con otro método mientras coordinamos la activación con Koywe.';
  }

  if (
    normalized.includes('bankcode not valid bancolombia') ||
    (normalized.includes('bancolombia') && normalized.includes('bankcode not valid'))
  ) {
    return 'Bancolombia todavía no está habilitado para retiros en este ambiente. Puedes intentar con otro método mientras coordinamos la activación con Koywe.';
  }

  if (
    normalized.includes('bankcode not valid') &&
    (
      normalized.includes('banco_btg_pactual') ||
      normalized.includes('banbco_btg_pactual') ||
      normalized.includes('nubank') ||
      normalized.includes('banco_itau') ||
      normalized.includes('banco_bradesco')
    )
  ) {
    return 'Los retiros por PIX en Brasil todavía no están habilitados correctamente en este ambiente. Puedes intentar con otro método mientras coordinamos la activación con Koywe.';
  }

  if (
    normalized.includes('accounttype is required') &&
    normalized.includes('checking, savings, interbanking')
  ) {
    return 'Este método todavía requiere una configuración adicional del proveedor en este ambiente. Intenta con otro método mientras lo coordinamos con Koywe.';
  }

  return message;
};
