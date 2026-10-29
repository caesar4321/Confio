// Link sends — the client half of send/link_invite.py.
//
// A first send to a contact no longer goes "to a phone number". The sender's
// app makes a one-time key, escrows the money under that key's address (the
// ordinary BSC invite batch, see inviteBsc.fundInvite) and opens the
// contact's WhatsApp chat with https://confio.lat/r/<ref>#<key>. The part
// after '#' never reaches a server. Whoever opens the link in Confío signs
// the server's claim message with the key, and the money goes to their own
// personal account.
//
// Later sends to a contact who claimed (and whom the sender confirmed) go
// direct: resolveRecipientForPhone answers SAVED. A number that verified its
// phone before phone-less signup answers LEGACY until the sender forgets it.

import { gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { Linking } from 'react-native';
import { bytesToHex } from '@noble/hashes/utils';
import { privKeyToAddress, signEip191Message } from './evmWallet';
import { BscInviteToken, fundInvite } from './inviteBsc';

export const LINK_MAX_USD = 10;
export const LINK_DAILY_MAX_USD = 100;
const LINK_HOST = 'https://confio.lat/r/';
const LINK_KEYCHAIN_SERVICE = 'com.confio.link_send';

export const RESOLVE_RECIPIENT_FOR_PHONE = gql`
  query ResolveRecipientForPhone($phone: String!) {
    resolveRecipientForPhone(phone: $phone) {
      kind
      publicRef
      user {
        userId
        username
        displayName
        identityVerified
        receivesByQrOnly
      }
    }
  }
`;

export const LINK_INVITE = gql`
  query LinkInvite($publicRef: String!) {
    linkInvite(publicRef: $publicRef) {
      senderUsername
      senderName
      senderVerified
      amount
      tokenType
      status
      expiresAt
      isMine
      claimMessage
    }
  }
`;

const PREPARE_LINK_INVITE = gql`
  mutation PrepareLinkInvite($phone: String!, $amount: Decimal!, $tokenType: String!, $claimKeyAddress: String!) {
    prepareLinkInvite(phone: $phone, amount: $amount, tokenType: $tokenType, claimKeyAddress: $claimKeyAddress) {
      success
      error
      inviteId
      publicRef
      intentId
      calls { to valueWei data }
    }
  }
`;

const CLAIM_LINK_INVITE = gql`
  mutation ClaimLinkInvite($publicRef: String!, $signature: String!) {
    claimLinkInvite(publicRef: $publicRef, signature: $signature) {
      success
      error
      status
      transactionHash
    }
  }
`;

const SAVE_RECIPIENT = gql`
  mutation SaveRecipient($publicRef: String, $phone: String, $recipientUserId: ID) {
    saveRecipient(publicRef: $publicRef, phone: $phone, recipientUserId: $recipientUserId) { success error }
  }
`;

const FORGET_RECIPIENT = gql`
  mutation ForgetRecipient($phone: String!) {
    forgetRecipient(phone: $phone) { success error }
  }
`;

export const LINK_SEND_ERRORS: Record<string, string> = {
  link_amount_over_limit: `La primera vez que le envías a alguien, el máximo es US$${LINK_MAX_USD}. Cuando confirme su cuenta podrás enviarle más.`,
  link_daily_limit: `Puedes enviar hasta US$${LINK_DAILY_MAX_USD} por link en 24 horas. Inténtalo más tarde.`,
  link_prepare_expired: 'Pasó demasiado tiempo. Vuelve a intentarlo.',
  bad_phone: 'Ese número no parece válido.',
  link_already_pending: 'Ya le enviaste un link que todavía no abre. Reenvíaselo desde ese teléfono, o espera a que venza (7 días) para recuperarlo.',
  link_already_pending_reshared: 'Ya le habías enviado un link que todavía no abre. Te abrimos WhatsApp para reenviárselo.',
  link_token_not_supported: 'La primera vez que le envías a alguien, solo puedes enviarle dólares.',
  link_not_found: 'No encontramos ese envío. Pídele a quien te lo mandó que lo revise.',
  link_already_claimed: 'Este envío ya lo recibió otra cuenta.',
  link_not_claimable: 'Este envío ya no se puede recibir.',
  link_expired: 'Este envío venció y vuelve a quien te lo mandó.',
  link_is_yours: 'Este link lo enviaste tú.',
  bad_signature: 'El link está incompleto. Ábrelo tal como te llegó por WhatsApp.',
  missing_bsc_address: 'Tu cuenta aún se está activando. Inténtalo en un momento.',
  recipient_receives_by_qr_only: 'Tu cuenta cobra con QR, así que no puede recibir envíos directos.',
};

export type RecipientKind = 'SAVED' | 'CLAIMED' | 'LEGACY' | 'NONE';
export type ResolvedRecipient = {
  kind: RecipientKind;
  /** CLAIMED only: the link the sender confirms with saveRecipient. */
  publicRef?: string | null;
  user: null | {
    userId: string;
    username: string;
    displayName: string;
    identityVerified: boolean;
    receivesByQrOnly: boolean;
  };
};

export const resolveRecipientForPhone = async (phone: string): Promise<ResolvedRecipient> => {
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.query({
    query: RESOLVE_RECIPIENT_FOR_PHONE,
    variables: { phone },
    fetchPolicy: 'network-only',
  });
  const result = data?.resolveRecipientForPhone;
  if (!result?.kind) throw new Error('resolve_failed');
  return { kind: result.kind, publicRef: result.publicRef, user: result.user ? { ...result.user, userId: String(result.user.userId) } : null };
};

export const buildLinkUrl = (publicRef: string, keyHex: string) => `${LINK_HOST}${publicRef}#${keyHex}`;

/** confio.lat/r/<uuid>#<64 hex> (or confio://r/…, which the web page opens
 *  when the universal link did not) → its parts; anything else → null. */
export const parseLinkUrl = (url: string): { publicRef: string; keyHex: string } | null => {
  const text = (url || '').trim();
  const match = /^(?:https?:\/\/(?:www\.)?confio\.lat\/r\/|confio:\/\/r\/)([0-9a-fA-F-]{36})#([0-9a-fA-F]{64})\s*$/.exec(text)
    // Android's intent from the web page carries the key as ?k= (an
    // intent's data cannot hold a '#'): confio://r/<ref>?k=<key>.
    || /^confio:\/\/r\/([0-9a-fA-F-]{36})\?k=([0-9a-fA-F]{64})\s*$/.exec(text);
  return match ? { publicRef: match[1].toLowerCase(), keyHex: match[2].toLowerCase() } : null;
};

export const linkMessage = (amountLabel: string, url: string) =>
  `Te envié ${amountLabel} por Confío. Ábrelo aquí para recibirlo: ${url}`;

/** Opens the contact's WhatsApp chat with the message typed in. */
export const openWhatsAppChat = async (phone: string, text: string) => {
  const digits = (phone || '').replace(/\D/g, '');
  const url = `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
  await Linking.openURL(url);
};

const keyServiceFor = (publicRef: string) => `${LINK_KEYCHAIN_SERVICE}.${publicRef}`;

/** The sender keeps each link's key on this phone, so they can share it again. */
export const storedLinkKey = async (publicRef: string): Promise<string | null> => {
  try {
    const found = await Keychain.getGenericPassword({ service: keyServiceFor(publicRef) });
    return found ? found.password : null;
  } catch {
    return null;
  }
};

const newLinkKey = async (): Promise<{ keyHex: string; address: string }> => {
  const { secureRandomBytes } = await import('../setup/entropyGuard');
  for (let attempt = 0; attempt < 4; attempt++) {
    const priv = secureRandomBytes(32, 'link send key');
    try {
      return { keyHex: bytesToHex(priv), address: privKeyToAddress(priv) };
    } catch {
      // Outside the curve order (astronomically rare): draw again.
    }
  }
  throw new Error('link_key_failed');
};

export interface LinkSendResult {
  publicRef: string;
  url: string;
  inviteId: string;
  txHash: string;
  pending?: boolean;
}

export const createLinkSend = async (params: {
  phone: string;
  amount: string | number;
  tokenType: BscInviteToken;
}): Promise<LinkSendResult> => {
  const { apolloClient } = await import('../apollo/client');
  const { keyHex, address } = await newLinkKey();
  let publicRef = '';
  const res = await fundInvite(async () => {
    const prep = (await apolloClient.mutate({
      mutation: PREPARE_LINK_INVITE,
      variables: {
        phone: params.phone,
        amount: String(params.amount),
        tokenType: params.tokenType,
        claimKeyAddress: address,
      },
    })).data?.prepareLinkInvite;
    if (prep?.error === 'link_already_pending' && prep.publicRef) {
      // One open link per contact: a retry after a lost answer re-shares the
      // link already escrowed instead of funding a second one.
      const existingKey = await storedLinkKey(prep.publicRef);
      if (existingKey) {
        await openWhatsAppChat(params.phone, linkMessage('dólares', buildLinkUrl(prep.publicRef, existingKey))).catch(() => {});
        throw new Error('link_already_pending_reshared');
      }
    }
    if (prep?.success && prep.publicRef) {
      publicRef = prep.publicRef;
      // Saved before anything is signed: a funded link whose key was lost
      // could only come back by reclaim after it expires.
      await Keychain.setGenericPassword('link', keyHex, { service: keyServiceFor(publicRef) });
    }
    return prep;
  });
  return { publicRef, url: buildLinkUrl(publicRef, keyHex), inviteId: res.inviteId, txHash: res.txHash, pending: res.pending };
};

/** Receive a link into the signed-in user's personal account. */
export const claimLink = async (publicRef: string, keyHex: string) => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
  const { data } = await apolloClient.query({
    query: LINK_INVITE,
    variables: { publicRef },
    fetchPolicy: 'network-only',
  });
  const link = data?.linkInvite;
  if (!link) throw new Error('link_not_found');
  if (link.isMine) throw new Error('link_is_yours');
  const message: string = link.claimMessage || '';
  // The key signs "pay <recipient>": only sign one that names our own
  // personal account, whatever the server sent.
  const personal = await getActiveEvmWallet({ type: 'personal', index: 0 });
  const recipientLine = `\nrecipient:${personal.address.toLowerCase()}`;
  if (!message.startsWith('Confio link claim\n') || !message.endsWith(recipientLine)) {
    throw new Error(message ? 'claim_message_mismatch' : 'missing_bsc_address');
  }
  const signature = signEip191Message(message, `0x${keyHex}`);
  const res = await apolloClient.mutate({ mutation: CLAIM_LINK_INVITE, variables: { publicRef, signature } });
  const out = res.data?.claimLinkInvite;
  if (!out?.success) throw new Error(out?.error || 'claim_failed');
  return out as { status: string; transactionHash?: string };
};

export const saveRecipient = async (args: { publicRef?: string; phone?: string; recipientUserId?: string }) => {
  const { apolloClient } = await import('../apollo/client');
  const res = await apolloClient.mutate({ mutation: SAVE_RECIPIENT, variables: args });
  return res.data?.saveRecipient as { success: boolean; error?: string };
};

export const forgetRecipient = async (phone: string) => {
  const { apolloClient } = await import('../apollo/client');
  const res = await apolloClient.mutate({ mutation: FORGET_RECIPIENT, variables: { phone } });
  return res.data?.forgetRecipient as { success: boolean; error?: string };
};

// ── Opening a link ──────────────────────────────────────────────────────
// Like the review link (reviewLink.ts): signed in, the claim screen opens at
// once; signed out (a new user installing from the link), the link waits in
// the keychain until Main is entered.

const PENDING_SERVICE = 'com.confio.pending_link_send';
type ReceivedLink = { publicRef: string; keyHex: string };
let opener: ((link: ReceivedLink) => void) | null = null;

/** AuthContext registers this while signed in; null while signed out. */
export const setLinkOpener = (fn: typeof opener) => {
  opener = fn;
};

export const receiveLink = async (link: ReceivedLink) => {
  if (opener) {
    opener(link);
    return;
  }
  await Keychain.setGenericPassword('link', JSON.stringify(link), { service: PENDING_SERVICE });
};

export const takePendingLink = async (): Promise<ReceivedLink | null> => {
  try {
    const stored = await Keychain.getGenericPassword({ service: PENDING_SERVICE });
    if (!stored) return null;
    await Keychain.resetGenericPassword({ service: PENDING_SERVICE });
    const link = JSON.parse(stored.password);
    return link?.publicRef && link?.keyHex ? link : null;
  } catch {
    return null;
  }
};

// ── A link copied before installing ─────────────────────────────────────
// The web page copies the link when Confío is not installed yet; the first
// launch after the install finds it here and opens the claim. Each link is
// offered once (the keychain remembers which), and on iOS the clipboard is
// read only when it holds a URL (no paste prompt otherwise).

const OFFERED_SERVICE = 'com.confio.link_send_offered';

export const takeClipboardLink = async (): Promise<ReceivedLink | null> => {
  try {
    const { Platform } = await import('react-native');
    const Clipboard = (await import('@react-native-clipboard/clipboard')).default;
    if (Platform.OS === 'ios' && typeof (Clipboard as any).hasURL === 'function' && !(await (Clipboard as any).hasURL())) {
      return null;
    }
    const link = parseLinkUrl(await Clipboard.getString());
    if (!link) return null;
    const stored = await Keychain.getGenericPassword({ service: OFFERED_SERVICE }).catch(() => false as const);
    const offered: string[] = stored && typeof stored === 'object' ? JSON.parse(stored.password || '[]') : [];
    if (offered.includes(link.publicRef)) return null;
    await Keychain.setGenericPassword('links', JSON.stringify([...offered, link.publicRef].slice(-20)),
      { service: OFFERED_SERVICE });
    return link;
  } catch {
    return null;
  }
};
