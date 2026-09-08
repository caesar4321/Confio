/** Only first-party membership URLs. Public QRs contain a provider, not a claim token. */
export function parseInstitutionLink(value: string): { provider: string; token?: string } | null {
  const match = value.trim().match(/^(?:confio:\/\/memberships|https:\/\/confio\.lat\/memberships)\?([^#]+)$/);
  if (!match || value.length > 8192) return null;
  try {
    const fields: Record<string, string> = {};
    for (const pair of match[1].split('&')) {
      const index = pair.indexOf('=');
      if (index < 1) return null;
      const key = decodeURIComponent(pair.slice(0, index));
      if (!['provider', 'token'].includes(key) || Object.prototype.hasOwnProperty.call(fields, key)) return null;
      fields[key] = decodeURIComponent(pair.slice(index + 1));
    }
    if (!/^[a-z][a-z0-9_-]{0,39}$/.test(fields.provider || '')) return null;
    if ('token' in fields && (!fields.token || fields.token.length > 4096 || /\s/.test(fields.token))) return null;
    return { provider: fields.provider, ...(fields.token ? { token: fields.token } : {}) };
  } catch {
    return null;
  }
}
