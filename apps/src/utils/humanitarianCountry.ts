// ISO-3 country code → ISO-2 (for <CountryFlag>) + Spanish name, for humanitarian campaign copy.
// Campaign.countryCode is ISO-3 (e.g. 'VEN'). Unknown codes get iso2 '' and a generic name.
const COUNTRY_INFO: Record<string, { iso2: string; name: string }> = {
  VEN: { iso2: 'VE', name: 'Venezuela' },
  COL: { iso2: 'CO', name: 'Colombia' },
  ECU: { iso2: 'EC', name: 'Ecuador' },
  PER: { iso2: 'PE', name: 'Perú' },
  BOL: { iso2: 'BO', name: 'Bolivia' },
  CHL: { iso2: 'CL', name: 'Chile' },
  ARG: { iso2: 'AR', name: 'Argentina' },
  MEX: { iso2: 'MX', name: 'México' },
  BRA: { iso2: 'BR', name: 'Brasil' },
  PAN: { iso2: 'PA', name: 'Panamá' },
  DOM: { iso2: 'DO', name: 'República Dominicana' },
  GTM: { iso2: 'GT', name: 'Guatemala' },
  HND: { iso2: 'HN', name: 'Honduras' },
  NIC: { iso2: 'NI', name: 'Nicaragua' },
  CRI: { iso2: 'CR', name: 'Costa Rica' },
  SLV: { iso2: 'SV', name: 'El Salvador' },
  URY: { iso2: 'UY', name: 'Uruguay' },
  PRY: { iso2: 'PY', name: 'Paraguay' },
};

export function countryInfo(code?: string | null): { iso2: string; name: string } {
  return COUNTRY_INFO[String(code || '').toUpperCase()] || { iso2: '', name: 'la zona afectada' };
}
