import type { MainStackParamList } from '../types/navigation';
import { phoneKeyToE164 } from './phoneKey';

/** Use transaction identity, never a name/contact-book match, to open history. */
export function transactionFriendRoute(
  tx: any,
  identityVerified: boolean,
  name: string,
  phone?: string,
): MainStackParamList['FriendDetail'] | null {
  if (!identityVerified || !['received', 'sent', 'send'].includes(tx?.type)) return null;
  const incoming = tx.type === 'received';
  const business = incoming
    ? tx.senderBusiness || tx.payerBusiness
    : tx.recipientBusiness || tx.counterpartyBusiness || tx.merchantBusiness;
  if (business || tx.isInvitedFriend || tx.is_invited_friend) return null;
  const id = incoming
    ? tx.senderUserId || tx.senderUser?.id
    : tx.recipientUserId || tx.recipientUser?.id || tx.counterpartyUser?.id;
  if (!id) return null;
  return {
    friendId: String(id),
    friendName: name || 'Amigo',
    friendAvatar: tx.avatar || name?.charAt(0) || 'A',
    friendPhone: phoneKeyToE164(phone) || undefined,
    isOnConfio: true,
  };
}
