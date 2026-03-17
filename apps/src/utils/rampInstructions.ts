type RampInstructionInput = {
  direction: 'ON_RAMP' | 'OFF_RAMP';
  paymentMethodCode?: string | null;
  paymentMethodDisplay?: string | null;
  paymentDetails?: Record<string, unknown> | string | null;
  nextActionUrl?: string | null;
};

export type RampInstructionRow = {
  label: string;
  value: string;
};

export type RampInstructionVariant =
  | 'bank_transfer'
  | 'redirect'
  | 'qr'
  | 'payout_pending'
  | 'generic';

export type RampInstructionView = {
  variant: RampInstructionVariant;
  title: string;
  subtitle: string;
  sectionTitle?: string;
  sectionBody?: string;
  steps?: string[];
  note?: string;
  actionLabel?: string;
  allowExternalAction?: boolean;
  qrValue?: string;
  rows: RampInstructionRow[];
};

const parsePaymentDetails = (value?: Record<string, unknown> | string | null): Record<string, unknown> | null => {
  if (!value) return null;
  if (typeof value === 'string') {
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  }
  return value;
};

const normalizeMethodCode = (value?: string | null) => (value || '').trim().toUpperCase();

const splitAddressLines = (value?: string | null): string[] =>
  (value || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

const prettifyRowLabel = (raw: string) => {
  const normalized = raw.toLowerCase();
  if (normalized === 'cvu') return 'CVU';
  if (normalized === 'cbu') return 'CBU';
  if (normalized === 'clabe') return 'CLABE';
  if (normalized === 'cci') return 'CCI';
  if (normalized === 'alias') return 'Alias';
  if (normalized === 'banco') return 'Banco';
  if (normalized === 'tef' || normalized === 'email') return 'Email';
  if (normalized === 'pix') return 'PIX';
  return raw.charAt(0).toUpperCase() + raw.slice(1);
};

const parseAddressRows = (rawAddress?: string | null): RampInstructionRow[] => {
  return splitAddressLines(rawAddress).map((line, index) => {
    if (line.includes('@') && !line.includes(' ')) {
      return { label: 'Email', value: line };
    }
    const match = line.match(/^([A-Za-z]+)\s+(.*)$/);
    if (!match) {
      return { label: `Dato ${index + 1}`, value: line };
    }
    return {
      label: prettifyRowLabel(match[1]),
      value: match[2].trim(),
    };
  });
};

export const buildRampInstructionView = ({
  direction,
  paymentMethodCode,
  paymentMethodDisplay,
  paymentDetails,
  nextActionUrl,
}: RampInstructionInput): RampInstructionView => {
  const normalizedCode = normalizeMethodCode(paymentMethodCode || paymentMethodDisplay);
  const details = parsePaymentDetails(paymentDetails);
  const providedAddress =
    typeof details?.providedAddress === 'string' ? details.providedAddress : null;
  const providedAction =
    typeof details?.providedAction === 'string' ? details.providedAction : null;

  if (normalizedCode.startsWith('WIRE')) {
    return {
      variant: direction === 'ON_RAMP' ? 'bank_transfer' : 'payout_pending',
      title: direction === 'ON_RAMP' ? 'Haz la transferencia' : 'Retiro en proceso',
      subtitle:
        direction === 'ON_RAMP'
          ? 'Usa estos datos desde tu banco o billetera para completar el pago.'
          : 'Estos son los datos del destino registrados para tu retiro.',
      sectionTitle:
        direction === 'ON_RAMP' ? 'Datos para transferir' : 'Cuenta registrada',
      sectionBody:
        direction === 'ON_RAMP'
          ? 'Copia los datos exactamente como aparecen y haz la transferencia por el monto indicado.'
          : 'Revisaremos esta cuenta mientras el proveedor procesa el retiro.',
      steps:
        direction === 'ON_RAMP'
          ? [
              'Copia los datos de la cuenta.',
              'Haz la transferencia desde tu banco o billetera.',
              'Conserva el comprobante hasta ver el saldo acreditado.',
            ]
          : [
              'Confirma que los datos del destino sean correctos.',
              'Espera la validación del proveedor.',
              'Consulta el estado aquí hasta ver el retiro completado.',
            ],
      note:
        direction === 'ON_RAMP'
          ? 'Envía el monto indicado y conserva el comprobante hasta que veas la acreditación.'
          : 'La acreditación puede tardar según el banco y la validación del proveedor.',
      allowExternalAction: false,
      rows: parseAddressRows(providedAddress),
    };
  }

  if (normalizedCode === 'PSE') {
    return {
      variant: 'redirect',
      title: 'Continúa con PSE',
      subtitle: 'Serás redirigido para elegir tu banco y completar el pago.',
      sectionTitle: 'Qué pasará ahora',
      sectionBody: 'Abriremos PSE para que selecciones tu banco y autorices el pago.',
      steps: [
        'Abre PSE desde el botón de abajo.',
        'Elige tu banco y completa la autorización.',
        'Vuelve a esta pantalla para seguir el estado del pago.',
      ],
      note: 'No cierres la app hasta terminar el proceso en PSE.',
      actionLabel: nextActionUrl ? 'Ir a PSE' : undefined,
      allowExternalAction: Boolean(nextActionUrl),
      rows: [],
    };
  }

  if (normalizedCode === 'KHIPU') {
    return {
      variant: 'redirect',
      title: 'Continúa con Khipu',
      subtitle: 'Abriremos Khipu para que completes el pago desde tu banco.',
      sectionTitle: 'Qué pasará ahora',
      sectionBody: 'Khipu te llevará al flujo de tu banco para completar el pago de forma segura.',
      steps: [
        'Abre Khipu desde el botón de abajo.',
        'Confirma el pago desde tu banco.',
        'Regresa a esta pantalla y revisa el estado.',
      ],
      note: 'Revisa que el monto y el titular coincidan antes de confirmar.',
      actionLabel: nextActionUrl ? 'Ir a Khipu' : undefined,
      allowExternalAction: Boolean(nextActionUrl),
      rows: [],
    };
  }

  if (
    normalizedCode.startsWith('QRI') ||
    normalizedCode === 'SIP_QR' ||
    normalizedCode === 'PIX_QR' ||
    normalizedCode === 'PIX-QR'
  ) {
    const qrValue = providedAction && !providedAction.startsWith('http') ? providedAction : undefined;
    return {
      variant: 'qr',
      title: 'Paga con QR',
      subtitle: qrValue
        ? 'Escanea este QR desde tu app bancaria o billetera compatible.'
        : 'Abre el proveedor para escanear o visualizar el QR interoperable.',
      sectionTitle: 'Cómo pagar',
      sectionBody: qrValue
        ? 'Escanea el QR con una app compatible y confirma el pago por el monto indicado.'
        : 'Abriremos el proveedor para que puedas ver o escanear el QR.',
      steps: qrValue
        ? [
            'Escanea el QR desde tu app bancaria o billetera.',
            'Confirma el pago.',
            'Vuelve aquí para seguir el estado de la compra.',
          ]
        : [
            'Abre el proveedor desde el botón de abajo.',
            'Visualiza o escanea el QR.',
            'Completa el pago y vuelve a esta pantalla.',
          ],
      note: qrValue
        ? 'Si no puedes escanearlo, copia el código y ábrelo desde una app compatible.'
        : 'Si tu app bancaria no abre el QR, prueba con otra app compatible.',
      actionLabel: nextActionUrl ? 'Ver QR' : undefined,
      allowExternalAction: Boolean(nextActionUrl) && !qrValue,
      qrValue,
      rows: [],
    };
  }

  if (normalizedCode === 'NEQUI') {
    return {
      variant: direction === 'ON_RAMP' ? 'redirect' : 'payout_pending',
      title: direction === 'ON_RAMP' ? 'Continúa con Nequi' : 'Retiro a Nequi',
      subtitle:
        direction === 'ON_RAMP'
          ? 'Abre Nequi para completar el pago.'
          : 'Tu retiro será enviado a la cuenta Nequi registrada.',
      sectionTitle: direction === 'ON_RAMP' ? 'Qué pasará ahora' : 'Cuenta de destino',
      sectionBody:
        direction === 'ON_RAMP'
          ? 'Abriremos Nequi para que completes el pago.'
          : 'El retiro se enviará a tu cuenta Nequi una vez que el proveedor lo procese.',
      note: direction === 'OFF_RAMP' ? 'Verifica que el número de celular sea correcto.' : undefined,
      actionLabel: nextActionUrl ? 'Abrir Nequi' : undefined,
      allowExternalAction: Boolean(nextActionUrl),
      rows: [],
    };
  }

  if (normalizedCode === 'BANCOLOMBIA') {
    return {
      variant: direction === 'ON_RAMP' ? 'redirect' : 'payout_pending',
      title: direction === 'ON_RAMP' ? 'Continúa con Bancolombia' : 'Retiro a Bancolombia',
      subtitle:
        direction === 'ON_RAMP'
          ? 'Abre el proveedor para completar el pago con Bancolombia.'
          : 'Tu retiro se enviará a la cuenta Bancolombia registrada.',
      sectionTitle: direction === 'ON_RAMP' ? 'Qué pasará ahora' : 'Cuenta registrada',
      sectionBody:
        direction === 'ON_RAMP'
          ? 'El proveedor te llevará al flujo de pago de Bancolombia.'
          : 'El proveedor procesará el retiro hacia tu cuenta Bancolombia.',
      actionLabel: nextActionUrl ? 'Abrir proveedor' : undefined,
      allowExternalAction: Boolean(nextActionUrl) && direction === 'ON_RAMP',
      rows: [],
    };
  }

  return {
    variant: 'generic',
    title: direction === 'ON_RAMP' ? 'Siguiente paso' : 'Retiro creado',
    subtitle:
      direction === 'ON_RAMP'
        ? `Sigue las instrucciones para pagar con ${paymentMethodDisplay || 'tu método seleccionado'}.`
        : `Sigue las instrucciones para completar el retiro por ${paymentMethodDisplay || 'tu método seleccionado'}.`,
    sectionTitle: direction === 'ON_RAMP' ? 'Instrucciones' : 'Estado del retiro',
    sectionBody:
      direction === 'ON_RAMP'
        ? 'Completa el pago con el método elegido y revisa el estado aquí.'
        : 'Tu retiro fue creado. Sigue este estado hasta ver el procesamiento final.',
    actionLabel: nextActionUrl ? 'Abrir proveedor' : undefined,
    allowExternalAction: false,
    rows: parseAddressRows(providedAddress),
  };
};
