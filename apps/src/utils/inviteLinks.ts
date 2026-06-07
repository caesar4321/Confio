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

export const buildReferralShareMessage = (username?: string | null): string => {
  const cleanUsername = normalizeInviteUsername(username || 'tuUsuario');
  const inviteLink = buildInviteLink({
    username: username || 'tuUsuario',
    source: 'whatsapp',
  });

  return [
    'En Latinoamérica, la desconfianza es el impuesto invisible que pagamos todos los días.',
    '',
    'Yo ya estoy usando Confío para guardar y mover dólares digitales entre personas, sin depender de bancos ni intermediarios.',
    '',
    '👇 Únete para recuperar el control de tu dinero:',
    inviteLink,
    '',
    'Mirá por qué nació Confío:',
    '',
    '▶️ De vividor a fundador',
    'https://youtu.be/HteVcIVJFbI',
    '',
    '▶️ Corea, América Latina y la confianza',
    'https://youtu.be/g_amw6WAQfY',
    '',
    `Código: ${cleanUsername}`,
  ].join('\n');
};

export const buildSendAndInviteShareMessage = ({
  amount,
  currency,
  inviteLink,
}: {
  amount: string;
  currency: string;
  inviteLink: string;
}): string => {
  return [
    `¡Hola! Te envié ${amount} ${currency} por Confío.`,
    '',
    'Confío es una app para guardar, enviar y pagar dólares digitales sin bancos.',
    '',
    'Tienes 7 días para reclamarlo. Crea tu cuenta acá:',
    inviteLink,
    '',
    'El dinero se acredita en segundos.',
  ].join('\n');
};
