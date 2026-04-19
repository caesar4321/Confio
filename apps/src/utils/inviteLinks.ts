export const normalizeInviteUsername = (username?: string | null): string => {
  return String(username || '').replace('@', '').toUpperCase();
};

export const buildInviteLink = ({
  username,
  source,
  invitationId,
}: {
  username?: string | null;
  source?: string;
  invitationId?: string | null;
}): string => {
  const cleanUsername = normalizeInviteUsername(username);
  const params = new URLSearchParams();

  if (source) {
    params.set('source', source);
  }
  if (invitationId) {
    params.set('invitation_id', String(invitationId));
  }

  const query = params.toString();
  return `https://confio.lat/invite/${cleanUsername}${query ? `?${query}` : ''}`;
};
