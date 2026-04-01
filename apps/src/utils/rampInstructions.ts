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
  actionUrl?: string;
  qrValue?: string;
  qrImageUri?: string;
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
    .filter((line) => Boolean(line) && line.toLowerCase() !== 'undefined');

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

const parseWirePeRows = (rawAddress?: string | null): RampInstructionRow[] => {
  const lines = splitAddressLines(rawAddress);
  const rows: RampInstructionRow[] = [];
  let pendingRucValue: string | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const nextLine = lines[index + 1];
    const prevLine = index > 0 ? lines[index - 1] : null;

    if (line.includes('@') && !line.includes(' ')) {
      rows.push({ label: 'Email', value: line });
      continue;
    }

    if (/^ruc$/i.test(line) && nextLine) {
      pendingRucValue = nextLine.trim();
      rows.push({ label: rows.some((row) => row.label === 'RUC') ? 'RUC (beneficiario)' : 'RUC', value: pendingRucValue });
      index += 1;
      continue;
    }

    if (/^cci$/i.test(line) && nextLine) {
      const cciLabel = rows.some((row) => row.label === 'CCI') ? 'CCI interbancaria' : 'CCI';
      rows.push({ label: cciLabel, value: nextLine.trim() });
      index += 1;
      continue;
    }

    if (/^ligo$/i.test(line)) {
      rows.push({ label: 'Entidad receptora', value: 'Ligo' });
      continue;
    }

    if (/^koywe$/i.test(line) && nextLine && /^per[uú]\s+sac$/i.test(nextLine)) {
      rows.push({ label: 'Beneficiario', value: `${line} ${nextLine}`.trim() });
      index += 1;
      continue;
    }

    if (/^bcp$/i.test(line)) {
      rows.push({ label: 'Banco', value: 'BCP' });
      if (nextLine && /^cuenta\b/i.test(nextLine)) {
        rows.push({ label: 'Tipo de cuenta', value: nextLine.trim() });
        index += 1;
      }
      continue;
    }

    const nroMatch = line.match(/^(?:nro\.?|n[úu]mero)\s*(.+)$/i);
    if (nroMatch) {
      rows.push({ label: 'Número de cuenta', value: nroMatch[1].trim() });
      continue;
    }

    const compactRucMatch = line.match(/^ruc\s+(.+)$/i);
    if (compactRucMatch) {
      const value = compactRucMatch[1].trim();
      if (value !== pendingRucValue || !pendingRucValue) {
        rows.push({ label: rows.some((row) => row.label === 'RUC') ? 'RUC (beneficiario)' : 'RUC', value });
      }
      continue;
    }

    const compactCciMatch = line.match(/^cci\s+(.+)$/i);
    if (compactCciMatch) {
      const cciLabel = rows.some((row) => row.label === 'CCI') ? 'CCI interbancaria' : 'CCI';
      rows.push({ label: cciLabel, value: compactCciMatch[1].trim() });
      continue;
    }

    if (/^koywe\b/i.test(line) && !/^koywe\s+per[uú]\s+sac$/i.test(line)) {
      rows.push({ label: 'Beneficiario', value: line });
      continue;
    }

    if (/^per[uú]\s+sac$/i.test(line) && prevLine && /^koywe$/i.test(prevLine)) {
      continue;
    }

    const match = line.match(/^([A-Za-z]+)\s+(.*)$/);
    if (match) {
      rows.push({
        label: prettifyRowLabel(match[1]),
        value: match[2].trim(),
      });
      continue;
    }

    rows.push({ label: `Dato ${index + 1}`, value: line });
  }

  return rows;
};

const parseWireMxRows = (rawAddress?: string | null): RampInstructionRow[] => {
  const lines = splitAddressLines(rawAddress);
  const rows: RampInstructionRow[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (line.includes('@') && !line.includes(' ')) {
      rows.push({ label: 'Email', value: line });
      continue;
    }

    if (/^koywe\b/i.test(line)) {
      const nextLine = lines[index + 1];
      if (nextLine && !/^\d+$/.test(nextLine) && !/@/.test(nextLine) && !/^stp$/i.test(nextLine)) {
        rows.push({ label: 'Beneficiario', value: `${line} ${nextLine}`.trim() });
        index += 1;
        continue;
      }
      rows.push({ label: 'Beneficiario', value: line });
      continue;
    }

    const match = line.match(/^([A-Za-z]+)\s+(.*)$/);
    if (match) {
      rows.push({
        label: prettifyRowLabel(match[1]),
        value: match[2].trim(),
      });
      continue;
    }

    if (/^\d{18}$/.test(line)) {
      rows.push({ label: 'CLABE', value: line });
      continue;
    }

    if (/^\d+$/.test(line)) {
      rows.push({ label: 'Referencia', value: line });
      continue;
    }

    if (/^stp$/i.test(line)) {
      rows.push({ label: 'Institución receptora', value: 'STP' });
      continue;
    }

    rows.push({ label: `Dato ${index + 1}`, value: line });
  }

  return rows;
};

const parseWireCoRows = (rawAddress?: string | null): RampInstructionRow[] => {
  const lines = splitAddressLines(rawAddress);
  const rows: RampInstructionRow[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (line.includes('@') && !line.includes(' ')) {
      rows.push({ label: 'Email', value: line });
      continue;
    }

    // "Koywe SAS" or "Koywe Colombia" → Beneficiario
    if (/^koywe\b/i.test(line)) {
      rows.push({ label: 'Beneficiario', value: line });
      continue;
    }

    // "NIT 901.620.954-1" → NIT
    if (/^nit\b/i.test(line)) {
      const match = line.match(/^nit\s+(.+)$/i);
      if (match) {
        rows.push({ label: 'NIT', value: match[1].trim() });
        continue;
      }
    }

    // "Cta de ahorro" or "Cta corriente" → Tipo de cuenta
    if (/^cta\b/i.test(line)) {
      rows.push({ label: 'Tipo de cuenta', value: line });
      continue;
    }

    // "Banco Davivienda" → Banco
    if (/^banco\b/i.test(line)) {
      const match = line.match(/^banco\s+(.+)$/i);
      if (match) {
        rows.push({ label: 'Banco', value: match[1].trim() });
        continue;
      }
    }

    // Pure number → Número de cuenta
    if (/^\d+$/.test(line)) {
      rows.push({ label: 'Número de cuenta', value: line });
      continue;
    }

    const match = line.match(/^([A-Za-z]+)\s+(.*)$/);
    if (match) {
      rows.push({ label: prettifyRowLabel(match[1]), value: match[2].trim() });
      continue;
    }

    rows.push({ label: `Dato ${index + 1}`, value: line });
  }

  return rows;
};

const parseWireClRows = (rawAddress?: string | null): RampInstructionRow[] => {
  const lines = splitAddressLines(rawAddress);
  const rows: RampInstructionRow[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (line.includes('@') && !line.includes(' ')) {
      rows.push({ label: 'Email', value: line });
      continue;
    }

    if (/^koywe\b/i.test(line)) {
      const nextLine = lines[index + 1];
      if (nextLine && !/^\d/.test(nextLine) && !/@/.test(nextLine) && !/^bci$/i.test(nextLine) && !/^cta\b/i.test(nextLine)) {
        rows.push({ label: 'Beneficiario', value: `${line} ${nextLine}`.trim() });
        index += 1;
        continue;
      }
      rows.push({ label: 'Beneficiario', value: line });
      continue;
    }

    if (/^\d{1,3}\.\d{3}\.\d{3}-[0-9kK]$/.test(line)) {
      rows.push({ label: 'RUT', value: line });
      continue;
    }

    const accountMatch = line.match(/^cta\s+cte\s+(.+)$/i);
    if (accountMatch) {
      rows.push({ label: 'Cuenta corriente', value: accountMatch[1].trim() });
      continue;
    }

    const match = line.match(/^([A-Za-z]+)\s+(.*)$/);
    if (match) {
      rows.push({
        label: prettifyRowLabel(match[1]),
        value: match[2].trim(),
      });
      continue;
    }

    if (/^bci$/i.test(line)) {
      rows.push({ label: 'Banco', value: 'BCI' });
      continue;
    }

    rows.push({ label: `Dato ${index + 1}`, value: line });
  }

  return rows;
};

const resolveExternalActionUrl = (
  details: Record<string, unknown> | null,
  providedAction: string | null,
  nextActionUrl: string | null | undefined,
) => {
  if (nextActionUrl && nextActionUrl.startsWith('http')) {
    return nextActionUrl;
  }

  const candidates = collectStringCandidates(details);
  if (providedAction) {
    candidates.unshift({ path: 'providedAction', value: providedAction });
  }

  const prioritized = [...candidates].sort((left, right) => {
    const leftScore = scoreUrlCandidate(left.path);
    const rightScore = scoreUrlCandidate(right.path);
    return rightScore - leftScore;
  });

  for (const candidate of prioritized) {
    const trimmed = candidate.value.trim();
    if (trimmed.startsWith('http')) {
      return trimmed;
    }
  }

  return undefined;
};

type StringCandidate = {
  path: string;
  value: string;
};

const MAX_STRING_DISCOVERY_DEPTH = 5;

const maybeParseNestedJson = (value: string): Record<string, unknown> | unknown[] | null => {
  const trimmed = value.trim();
  if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
};

const collectStringCandidates = (
  value: unknown,
  path = 'root',
  depth = 0,
  sink: StringCandidate[] = [],
  seen = new Set<unknown>(),
): StringCandidate[] => {
  if (value == null || depth > MAX_STRING_DISCOVERY_DEPTH) {
    return sink;
  }
  if (typeof value === 'string') {
    sink.push({ path, value });
    const nested = maybeParseNestedJson(value);
    if (nested) {
      collectStringCandidates(nested, `${path}.__parsed__`, depth + 1, sink, seen);
    }
    return sink;
  }
  if (typeof value !== 'object') {
    return sink;
  }
  if (seen.has(value)) {
    return sink;
  }
  seen.add(value);
  if (Array.isArray(value)) {
    value.forEach((entry, index) => collectStringCandidates(entry, `${path}[${index}]`, depth + 1, sink, seen));
    return sink;
  }
  Object.entries(value as Record<string, unknown>).forEach(([key, entry]) => {
    collectStringCandidates(entry, `${path}.${key}`, depth + 1, sink, seen);
  });
  return sink;
};

const isImageLikeValue = (value: string) => {
  const trimmed = value.trim();
  return (
    trimmed.startsWith('data:image/')
    || trimmed.startsWith('iVBORw0KGgo')
    || trimmed.startsWith('/9j/')
    || trimmed.startsWith('PHN2Zy')
    || trimmed.startsWith('<svg')
  );
};

const toImageDataUri = (value: string) => {
  const trimmed = value.trim();
  if (trimmed.startsWith('data:image/')) {
    return trimmed;
  }
  if (trimmed.startsWith('iVBORw0KGgo')) {
    return `data:image/png;base64,${trimmed}`;
  }
  if (trimmed.startsWith('/9j/')) {
    return `data:image/jpeg;base64,${trimmed}`;
  }
  if (trimmed.startsWith('PHN2Zy')) {
    return `data:image/svg+xml;base64,${trimmed}`;
  }
  if (trimmed.startsWith('<svg')) {
    return `data:image/svg+xml;utf8,${encodeURIComponent(trimmed)}`;
  }
  return undefined;
};

const scoreUrlCandidate = (path: string) => {
  const normalized = path.toLowerCase();
  let score = 0;
  if (/providedaction|redirect|action|url|link|deeplink/.test(normalized)) score += 5;
  if (/providerlinkurl/.test(normalized)) score += 3;
  if (/response\.__parsed__/.test(normalized)) score += 1;
  return score;
};

const scoreImageCandidate = (path: string) => {
  const normalized = path.toLowerCase();
  let score = 0;
  if (/providerlinkurl/.test(normalized)) score += 8;
  if (/qr|image|png|jpg|jpeg|svg/.test(normalized)) score += 5;
  if (/response\.__parsed__/.test(normalized)) score += 2;
  return score;
};

const scoreQrTextCandidate = (path: string) => {
  const normalized = path.toLowerCase();
  let score = 0;
  if (/providedaction/.test(normalized)) score += 8;
  if (/qr|payload|content|code|providerlinkurl/.test(normalized)) score += 5;
  if (/response\.__parsed__/.test(normalized)) score += 2;
  return score;
};

const resolveQrImageUri = (details: Record<string, unknown> | null, providedAction: string | null) => {
  const imageLikeValues: StringCandidate[] = [];

  const candidates = collectStringCandidates(details);
  if (providedAction) {
    imageLikeValues.push({ path: 'providedAction', value: providedAction });
  }
  imageLikeValues.push(...candidates);

  const prioritized = imageLikeValues
    .filter((candidate) => isImageLikeValue(candidate.value))
    .sort((left, right) => scoreImageCandidate(right.path) - scoreImageCandidate(left.path));

  for (const candidate of prioritized) {
    const uri = toImageDataUri(candidate.value);
    if (uri) {
      return uri;
    }
  }

  return undefined;
};

const resolveQrValue = (details: Record<string, unknown> | null, providedAction: string | null, qrImageUri?: string) => {
  if (qrImageUri) {
    return undefined;
  }

  const candidates = collectStringCandidates(details);
  if (providedAction) {
    candidates.unshift({ path: 'providedAction', value: providedAction });
  }

  const prioritized = [...candidates].sort((left, right) => {
    const leftScore = scoreQrTextCandidate(left.path);
    const rightScore = scoreQrTextCandidate(right.path);
    return rightScore - leftScore;
  });

  for (const candidate of prioritized) {
    const trimmed = candidate.value.trim();
    if (!trimmed) {
      continue;
    }
    if (trimmed.startsWith('http')) {
      continue;
    }
    if (isImageLikeValue(trimmed)) {
      continue;
    }
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      continue;
    }
    if (trimmed.length > 3000) {
      continue;
    }
    return trimmed;
  }

  return undefined;
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
  const externalActionUrl = resolveExternalActionUrl(details, providedAction, nextActionUrl);
  const qrImageUri = resolveQrImageUri(details, providedAction);

  if (normalizedCode.startsWith('WIRE') || normalizedCode === 'STP') {
    const payoutRows: RampInstructionRow[] = [];
    return {
      variant: direction === 'ON_RAMP' ? 'bank_transfer' : 'payout_pending',
      title: direction === 'ON_RAMP' ? 'Haz la transferencia' : 'Retiro en proceso',
      subtitle:
        direction === 'ON_RAMP'
          ? 'Usa estos datos desde tu banco o billetera para completar el pago.'
          : 'Tu retiro fue creado y el proveedor está validando la cuenta de destino.',
      sectionTitle:
        direction === 'ON_RAMP' ? 'Datos para transferir' : 'Qué sigue ahora',
      sectionBody:
        direction === 'ON_RAMP'
          ? 'Copia los datos exactamente como aparecen y haz la transferencia por el monto indicado.'
          : 'No necesitas hacer nada más por ahora. Revisa el destino arriba y consulta el estado hasta ver el retiro completado.',
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
      rows:
        direction === 'ON_RAMP'
          ? normalizedCode === 'WIREPE'
            ? parseWirePeRows(providedAddress)
            : normalizedCode === 'WIRECL'
              ? parseWireClRows(providedAddress)
            : normalizedCode === 'WIREMX' || normalizedCode === 'STP'
              ? parseWireMxRows(providedAddress)
            : normalizedCode === 'WIRECO'
              ? parseWireCoRows(providedAddress)
              : parseAddressRows(providedAddress)
          : payoutRows,
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
      actionLabel: externalActionUrl ? 'Ir a PSE' : undefined,
      allowExternalAction: Boolean(externalActionUrl),
      actionUrl: externalActionUrl,
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
      actionLabel: externalActionUrl ? 'Ir a Khipu' : undefined,
      allowExternalAction: Boolean(externalActionUrl),
      actionUrl: externalActionUrl,
      rows: [],
    };
  }

  if (
    normalizedCode.startsWith('QRI') ||
    normalizedCode === 'SIP_QR' ||
    normalizedCode === 'PIX_QR' ||
    normalizedCode === 'PIX-QR'
  ) {
    const qrValue = resolveQrValue(details, providedAction, qrImageUri);

    if (direction === 'OFF_RAMP' && !qrImageUri && !qrValue && !externalActionUrl) {
      return {
        variant: 'payout_pending',
        title: 'Retiro en proceso',
        subtitle: 'Tu retiro fue creado y el proveedor está validando la cuenta o destino registrado.',
        sectionTitle: 'Qué sigue ahora',
        sectionBody: 'No necesitas pagar ni escanear un QR. Solo espera la validación del proveedor y consulta el estado aquí.',
        steps: [
          'Confirma que el destino del retiro sea correcto.',
          'Espera la validación del proveedor.',
          'Consulta el estado aquí hasta ver el retiro completado.',
        ],
        note: 'La acreditación puede tardar según la validación del proveedor y el banco o billetera de destino.',
        allowExternalAction: false,
        rows: [],
      };
    }
    return {
      variant: 'qr',
      title: direction === 'ON_RAMP' ? 'Paga con QR' : 'Continúa con QR',
      subtitle: qrImageUri || qrValue
        ? direction === 'ON_RAMP'
          ? 'Escanea este QR desde tu app bancaria o billetera compatible.'
          : 'Usa o comparte este QR según las instrucciones del proveedor.'
        : direction === 'ON_RAMP'
          ? 'Abre el proveedor para escanear o visualizar el QR interoperable.'
          : 'Abre el proveedor para ver el QR o continuar con el flujo indicado.',
      sectionTitle: direction === 'ON_RAMP' ? 'Cómo pagar' : 'Qué sigue ahora',
      sectionBody: qrImageUri || qrValue
        ? direction === 'ON_RAMP'
          ? 'Escanea el QR con una app compatible y confirma el pago por el monto indicado.'
          : 'Usa este QR solo si el proveedor o la billetera de destino te lo solicita para completar el retiro.'
        : direction === 'ON_RAMP'
          ? 'Abriremos el proveedor para que puedas ver o escanear el QR.'
          : 'Abriremos el proveedor para que puedas continuar con el flujo del retiro.',
      steps: qrImageUri || qrValue
        ? direction === 'ON_RAMP'
          ? [
              'Escanea el QR desde tu app bancaria o billetera.',
              'Confirma el pago.',
              'Vuelve aquí para seguir el estado de la compra.',
            ]
          : [
              'Muestra, comparte o usa el QR según el flujo del proveedor.',
              'Completa la confirmación requerida.',
              'Vuelve aquí para seguir el estado del retiro.',
            ]
        : direction === 'ON_RAMP'
          ? [
              'Abre el proveedor desde el botón de abajo.',
              'Visualiza o escanea el QR.',
              'Completa el pago y vuelve a esta pantalla.',
            ]
          : [
              'Abre el proveedor desde el botón de abajo.',
              'Sigue el flujo que te muestre el proveedor.',
              'Vuelve aquí para revisar el estado del retiro.',
            ],
      note: qrImageUri
        ? direction === 'ON_RAMP'
          ? 'Escanea el QR directamente desde otra app bancaria o billetera compatible.'
          : 'Usa este QR solo si el proveedor lo requiere para el retiro.'
        : qrValue
        ? direction === 'ON_RAMP'
          ? 'Si no puedes escanearlo, copia el código y ábrelo desde una app compatible.'
          : 'Si el proveedor requiere el contenido del QR, copia el valor y úsalo solo en una app compatible.'
        : direction === 'ON_RAMP'
          ? 'Si tu app bancaria no abre el QR, prueba con otra app compatible.'
          : 'Si el flujo no muestra un QR utilizable, continúa desde el proveedor y consulta el estado aquí.',
      actionLabel: externalActionUrl ? (direction === 'ON_RAMP' ? 'Ver QR' : 'Continuar') : undefined,
      allowExternalAction: Boolean(externalActionUrl) && !qrImageUri && !qrValue,
      actionUrl: externalActionUrl,
      qrImageUri,
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
      actionLabel: externalActionUrl ? 'Abrir Nequi' : undefined,
      allowExternalAction: Boolean(externalActionUrl),
      actionUrl: externalActionUrl,
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
      actionLabel: externalActionUrl ? 'Abrir proveedor' : undefined,
      allowExternalAction: Boolean(externalActionUrl) && direction === 'ON_RAMP',
      actionUrl: externalActionUrl,
      rows: [],
    };
  }

  if (normalizedCode === 'RECAUDO-PE') {
    if (direction === 'OFF_RAMP') {
      return {
        variant: 'payout_pending',
        title: 'Retiro en proceso',
        subtitle: 'Tu retiro fue creado y el proveedor está validando la cuenta de destino registrada.',
        sectionTitle: 'Qué sigue ahora',
        sectionBody: 'No necesitas abrir ninguna app bancaria. Solo revisa el destino arriba y consulta el estado hasta ver el retiro completado.',
        steps: [
          'Confirma que el destino del retiro sea correcto.',
          'Espera la validación del proveedor.',
          'Consulta el estado aquí hasta ver el retiro completado.',
        ],
        note: 'La acreditación puede tardar según la validación del proveedor y el banco receptor.',
        allowExternalAction: false,
        rows: [],
      };
    }

    const rows = parseWirePeRows(providedAddress);
    const hasRows = rows.length > 0;
    return {
      variant: hasRows ? 'bank_transfer' : 'redirect',
      title: 'Continúa con Recaudo BCP',
      subtitle:
        hasRows
          ? 'Usa estos datos para completar el pago en Perú.'
          : 'Abriremos el proveedor para que completes el pago con Recaudo BCP.',
      sectionTitle:
        hasRows ? 'Datos para pagar' : 'Qué pasará ahora',
      sectionBody:
        hasRows
          ? 'Copia los datos exactamente como aparecen y completa el pago por el monto indicado.'
          : 'Abriremos el proveedor para que completes el recaudo.',
      steps:
        hasRows
          ? [
              'Copia los datos del recaudo.',
              'Completa el pago desde tu banco o canal compatible.',
              'Conserva el comprobante hasta ver la acreditación.',
            ]
          : [
              'Abre el proveedor desde el botón de abajo.',
              'Completa el recaudo por el monto indicado.',
              'Vuelve aquí para seguir el estado de la compra.',
            ],
      note:
        'Si el proveedor abre un enlace externo, completa el pago y luego vuelve a esta pantalla.',
      actionLabel: externalActionUrl ? 'Abrir recaudo' : undefined,
      allowExternalAction: Boolean(externalActionUrl),
      actionUrl: externalActionUrl,
      rows,
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
    actionLabel: externalActionUrl ? 'Abrir proveedor' : undefined,
    allowExternalAction: Boolean(externalActionUrl),
    actionUrl: externalActionUrl,
    rows: parseAddressRows(providedAddress),
  };
};
