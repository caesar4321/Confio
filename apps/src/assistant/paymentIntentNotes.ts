/** Where an exact payment's spare goes, said on the card as on Pagar: the
 *  dollars cover the exact amount with a margin, and what the conversion
 *  lands above it is not returned to the wallet. A Pix charge (local_charge)
 *  returns it, so it needs no note; a Bolivian QR is priced by its provider. */
export function exactSurplusNote(intent: { amountExact?: boolean | null; family?: string | null; methodId?: string | null }): string {
  if (!intent.amountExact) return '';
  if (intent.family === 'local_transfer') {
    return 'Incluye las comisiones y un margen por si el tipo de cambio se mueve: lo que sobre queda en tu cuenta en moneda local.';
  }
  if (intent.family === 'ramp_order' && intent.methodId === 've_pagomovil_send') {
    return 'Incluye las comisiones y un pequeño margen por si la tasa se mueve; ese margen no se devuelve.';
  }
  return '';
}
