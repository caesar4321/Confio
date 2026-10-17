// Recargar/Retirar run through Koywe's delegated KYC, which needs the
// phone-country (primary) document: an additional passport or ID does not
// open them. myIdentityStatus answers that directly. While it loads, fails,
// or on servers that predate it, only myPersonalKycStatus answers: it stays
// the primary document's attempt on every server. me.isIdentityVerified does
// NOT: it counts additional documents now.
type IdentityStatus = { phoneCountryVerified?: boolean | null } | null | undefined;

export function hasRampIdentity(identity: IdentityStatus, personalKycStatus?: string | null): boolean {
  if (typeof identity?.phoneCountryVerified === 'boolean') {
    return identity.phoneCountryVerified;
  }
  return (personalKycStatus || '').toLowerCase() === 'verified';
}
