// ISO-3 country code → flag emoji + Spanish name, for humanitarian campaign copy.
// Campaign.countryCode is ISO-3 (e.g. 'VEN'). Falls back gracefully for unknown codes.
const COUNTRY_INFO: Record<string, { flag: string; name: string }> = {
  VEN: { flag: '🇻🇪', name: 'Venezuela' },
  COL: { flag: '🇨🇴', name: 'Colombia' },
  ECU: { flag: '🇪🇨', name: 'Ecuador' },
  PER: { flag: '🇵🇪', name: 'Perú' },
  BOL: { flag: '🇧🇴', name: 'Bolivia' },
  CHL: { flag: '🇨🇱', name: 'Chile' },
  ARG: { flag: '🇦🇷', name: 'Argentina' },
  MEX: { flag: '🇲🇽', name: 'México' },
  BRA: { flag: '🇧🇷', name: 'Brasil' },
  PAN: { flag: '🇵🇦', name: 'Panamá' },
  DOM: { flag: '🇩🇴', name: 'República Dominicana' },
  GTM: { flag: '🇬🇹', name: 'Guatemala' },
  HND: { flag: '🇭🇳', name: 'Honduras' },
  NIC: { flag: '🇳🇮', name: 'Nicaragua' },
  CRI: { flag: '🇨🇷', name: 'Costa Rica' },
  SLV: { flag: '🇸🇻', name: 'El Salvador' },
  URY: { flag: '🇺🇾', name: 'Uruguay' },
  PRY: { flag: '🇵🇾', name: 'Paraguay' },
};

export function countryInfo(code?: string | null): { flag: string; name: string } {
  return COUNTRY_INFO[String(code || '').toUpperCase()] || { flag: '🌎', name: 'la zona afectada' };
}
