import { getCountryByIso } from './countries';

type SupportLocale = {
  community: string;
  adjective: string;
};

type SupportCopy = {
  transferLine: string;
  ecosystemLine: string;
  merchantLine: string;
  merchantTitle: string;
  processingLine: string;
};

const SUPPORT_LOCALES: Record<string, SupportLocale> = {
  AR: { community: 'los argentinos', adjective: 'argentinos' },
  BZ: { community: 'los beliceños', adjective: 'beliceños' },
  BO: { community: 'los bolivianos', adjective: 'bolivianos' },
  BR: { community: 'los brasileños', adjective: 'brasileños' },
  CL: { community: 'los chilenos', adjective: 'chilenos' },
  CO: { community: 'los colombianos', adjective: 'colombianos' },
  CR: { community: 'los costarricenses', adjective: 'costarricenses' },
  CU: { community: 'los cubanos', adjective: 'cubanos' },
  DO: { community: 'los dominicanos', adjective: 'dominicanos' },
  EC: { community: 'los ecuatorianos', adjective: 'ecuatorianos' },
  GT: { community: 'los guatemaltecos', adjective: 'guatemaltecos' },
  HN: { community: 'los hondureños', adjective: 'hondureños' },
  NI: { community: 'los nicaraguenses', adjective: 'nicaraguenses' },
  PA: { community: 'los panameños', adjective: 'panameños' },
  MX: { community: 'los mexicanos', adjective: 'mexicanos' },
  PE: { community: 'los peruanos', adjective: 'peruanos' },
  PR: { community: 'los puertorriqueños', adjective: 'puertorriqueños' },
  PY: { community: 'los paraguayos', adjective: 'paraguayos' },
  SV: { community: 'los salvadoreños', adjective: 'salvadoreños' },
  US: { community: 'los latinos', adjective: 'latinos' },
  UY: { community: 'los uruguayos', adjective: 'uruguayos' },
  VE: { community: 'los venezolanos', adjective: 'venezolanos' },
};

const withFlag = (text: string, flag?: string) => (flag ? `${text} ${flag}` : text);

export const getSupportCopy = (phoneCountry?: string): SupportCopy => {
  const country = getCountryByIso(phoneCountry || 'AR') || getCountryByIso('AR');
  const isoCode = country?.[2] || 'AR';
  const flag = country?.[3] || '🌎';
  const locale = SUPPORT_LOCALES[isoCode];

  if (locale) {
    return {
      transferLine: withFlag(`Apoyamos a ${locale.community} con transferencias gratuitas`, flag),
      ecosystemLine: withFlag(`Apoyamos a ${locale.community} con un ecosistema justo`, flag),
      merchantLine: withFlag(`Apoyamos a los comerciantes ${locale.adjective}`, flag),
      merchantTitle: `Apoyamos negocios ${locale.adjective}`,
      processingLine: withFlag(`¡Apoyamos a ${locale.community}!`, flag),
    };
  }

  return {
    transferLine: withFlag('Apoyamos a los latinos con transferencias gratuitas', flag),
    ecosystemLine: withFlag('Apoyamos a los latinos con un ecosistema justo', flag),
    merchantLine: withFlag('Apoyamos a los comerciantes latinos', flag),
    merchantTitle: 'Apoyamos negocios latinos',
    processingLine: withFlag('¡Apoyamos a los latinos!', flag),
  };
};
