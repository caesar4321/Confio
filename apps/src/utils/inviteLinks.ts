export const normalizeInviteUsername = (username?: string | null): string => {
  return String(username || '').replace('@', '').toUpperCase();
};

export const buildInviteLink = ({
  username,
  source,
  invitationId,
  utm,
}: {
  username?: string | null;
  source?: string;
  invitationId?: string | null;
  /** utm_* tags the link worker records with the click and carries to signup. */
  utm?: Record<string, string>;
}): string => {
  const cleanUsername = normalizeInviteUsername(username);
  const params = new URLSearchParams();

  if (source) {
    params.set('source', source);
  }
  for (const [key, value] of Object.entries(utm || {})) {
    if (value) params.set(key, value);
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
  // Referral commission live (the US$5 $CONFIO bonus ended with it): the
  // friend's reason to join is Confío itself, and because Confío is built on
  // trust, the inviter says plainly that they earn a share of Confío's own
  // fee, at no extra cost to the friend.
  // WhatsApp renders *bold* and _italic_; other apps show the marks as-is,
  // which reads fine. Never wrap a URL: it must stay tappable.
  const commissionLines = [
    '',
    '🔐 Crea tu cuenta con mi link y *verifica tu identidad* en la app: así queda protegida y puedes usar todo Confío.',
    '',
    '🤝 _Para que haya confianza, te lo digo claro:_ Confío me comparte parte de su comisión cuando recargas, retiras o inviertes. *A ti no te cuesta nada extra.*',
  ];

  return [
    '*En Latinoamérica, la confianza entre personas ya existe.* Lo que falta es un sistema que la merezca.',
    '',
    'Yo ya estoy usando Confío para *guardar y mover dólares digitales* entre personas, sin depender de bancos ni intermediarios.',
    '',
    '👇 *Únete para recuperar el control de tu dinero:*',
    inviteLink,
    ...commissionLines,
    '',
    '*Conoce a Julian, el fundador, y por qué creó Confío:*',
    '',
    '▶️ _¡La confianza ya existe!_',
    'https://youtube.com/shorts/Ut01b5Z0NDQ?feature=share',
    '',
    '▶️ _Latinoamérica vive sin barandas_',
    'https://youtu.be/uWTB-SiGyNM',
    '',
    '▶️ _De vividor a fundador_',
    'https://youtu.be/HteVcIVJFbI',
    '',
    // Plain on purpose: people copy the code into "¿Quién te invitó?".
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
  // WhatsApp *bold* / _italic_; the link stays on its own line, unformatted.
  return [
    `¡Hola! *Te envié ${amount} ${currency} por Confío.*`,
    '',
    'Confío es una app para *guardar, enviar y pagar dólares digitales* sin bancos.',
    '',
    '⏳ Tienes *7 días* para reclamarlo. Crea tu cuenta acá:',
    inviteLink,
    '',
    'El dinero se acredita en segundos.',
    '',
    '🤝 _Para que haya confianza:_ si te unes con este link, Confío me comparte parte de su comisión cuando recargas, retiras o inviertes. A ti no te cuesta nada extra.',
  ].join('\n');
};
