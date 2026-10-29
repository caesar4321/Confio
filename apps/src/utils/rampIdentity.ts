// Recargar/Retirar run through Koywe's delegated KYC, which needs a document
// ISSUED by the order's country (security.identity_status.rail_identity),
// primary or additional. verifiedDocumentCountries answers that for any
// country; phoneCountryVerified answers it for the phone's country only, on
// servers that predate the list. While both load or fail, only
// myPersonalKycStatus answers. me.isIdentityVerified does NOT: it counts a
// document of any country.
type IdentityStatus = {
  phoneCountryVerified?: boolean | null;
  verifiedDocumentCountries?: (string | null)[] | null;
} | null | undefined;

export function hasRampIdentity(
  identity: IdentityStatus,
  personalKycStatus?: string | null,
  countryCode?: string | null,
): boolean {
  const country = String(countryCode || '').trim().toUpperCase();
  if (country && Array.isArray(identity?.verifiedDocumentCountries)) {
    return identity.verifiedDocumentCountries.some(code => String(code || '').toUpperCase() === country);
  }
  if (typeof identity?.phoneCountryVerified === 'boolean') {
    return identity.phoneCountryVerified;
  }
  return (personalKycStatus || '').toLowerCase() === 'verified';
}

// Verified with another country's document: the person needs this country's.
export function needsCountryDocument(identity: IdentityStatus, countryCode?: string | null): boolean {
  const country = String(countryCode || '').trim().toUpperCase();
  const countries = identity?.verifiedDocumentCountries;
  return Boolean(country) && Array.isArray(countries) && countries.length > 0
    && !countries.some(code => String(code || '').toUpperCase() === country);
}
