import { Buffer } from 'buffer'
import { apolloClient } from '../apollo/client'
import { PREPARE_INVITE_FOR_PHONE, SUBMIT_INVITE_FOR_PHONE, CLAIM_INVITE_FOR_PHONE } from '../apollo/mutations'
import { INVITE_RECEIPT_FOR_PHONE } from '../apollo/queries'
import algorandService from './algorandService'

type SponsorTxn = { txn: string; index: number }
type PreparedInvite = {
  userTransaction: { txn: string; groupId?: string; first?: number; last?: number; gh?: string; gen?: string }
  sponsorTransactions: SponsorTxn[]
  groupId?: string
  invitationId: string
}

class InviteSendService {
  async prepareInvite(
    phone: string,
    phoneCountry: string | undefined,
    amount: number,
    assetType: 'CUSD' | 'CONFIO' = 'CUSD',
    message?: string,
  ): Promise<{ success: boolean; error?: string; prepared?: PreparedInvite }> {
    const { data } = await apolloClient.mutate({
      mutation: PREPARE_INVITE_FOR_PHONE,
      variables: { phone, phoneCountry, amount, assetType, message },
    })
    const res = data?.prepareInviteForPhone
    if (!res?.success) {
      console.error('[InviteSend] prepareInvite failed', res);
      return { success: false, error: res?.error || 'Failed to prepare invite' }
    }

    const prepared: PreparedInvite = {
      userTransaction: res.userTransaction,
      sponsorTransactions: res.sponsorTransactions || [],
      groupId: res.groupId,
      invitationId: res.invitationId,
    }
    return { success: true, prepared }
  }

  async submitPreparedInvite(prepared: PreparedInvite): Promise<{ success: boolean; error?: string; txid?: string }> {
    // Expect one user txn to sign (the AXFER)
    const user = prepared.userTransaction
    if (!user?.txn) return { success: false, error: 'Missing user transaction to sign' }

    const userTxnBytes = Buffer.from(user.txn, 'base64')
    // Use centralized signing which restores wallet scope from JWT + account context
    const signedUserTxn = await algorandService.signTransactionBytes(userTxnBytes)
    const signedAxferB64 = Buffer.from(signedUserTxn).toString('base64')

    // Normalize base64 strings to prevent padding/urlsafe issues
    const normalizeB64 = (s: string) => {
      let t = (s || '').trim().replace(/\r|\n/g, '').replace(/-/g, '+').replace(/_/g, '/')
      const pad = (4 - (t.length % 4)) % 4
      if (pad) t = t + '='.repeat(pad)
      return t
    }

    const signedAxferB64Norm = normalizeB64(signedAxferB64)

    // Debug lengths to track padding issues
    try {
      console.log('[InviteSend] lengths', {
        signed: signedAxferB64Norm.length,
        s0: sponsorUnsigned[0]?.length,
        s1: sponsorUnsigned[1]?.length,
        s2: sponsorUnsigned[2]?.length,
        mod4: {
          signed: signedAxferB64Norm.length % 4,
          s0: sponsorUnsigned[0]?.length % 4,
          s1: sponsorUnsigned[1]?.length % 4,
          s2: sponsorUnsigned[2]?.length % 4,
        }
      })
    } catch {}

    // Echo sponsor transactions back exactly as provided by server (no mutation)
    const sponsorTransactionsPayload = (prepared.sponsorTransactions || []).map(stx => JSON.stringify(stx))

    const { data } = await apolloClient.mutate({
      mutation: SUBMIT_INVITE_FOR_PHONE,
      variables: { signedUserTxn: signedAxferB64Norm, sponsorTransactions: sponsorTransactionsPayload, invitationId: prepared.invitationId },
    })
    const res = data?.submitInviteForPhone
    if (!res?.success) {
      console.error('[InviteSend] submitInvite failed', res);
      return { success: false, error: res?.error || 'Invite submission failed' }
    }
    return { success: true, txid: res.txid }
  }

  async createInviteForPhone(
    phone: string,
    phoneCountry: string | undefined,
    amount: number,
    assetType: 'CUSD' | 'CONFIO' = 'CUSD',
    message?: string,
  ): Promise<{ success: boolean; error?: string; txid?: string; invitationId?: string }> {
    const prep = await this.prepareInvite(phone, phoneCountry, amount, assetType, message)
    if (!prep.success || !prep.prepared) return prep
    const sub = await this.submitPreparedInvite(prep.prepared)
    if (!sub.success) return sub
    return { success: true, txid: sub.txid, invitationId: prep.prepared.invitationId }
  }

  async getInviteReceiptNotice(phone: string, phoneCountry?: string): Promise<
    { exists: true; amount: number; assetId: string; timestamp: number; invitationId?: string | null } | { exists: false }
  > {
    const { data } = await apolloClient.query({
      query: INVITE_RECEIPT_FOR_PHONE,
      fetchPolicy: 'network-only',
      variables: { phone, phoneCountry },
    })
    const r = data?.inviteReceiptForPhone
    if (!r?.exists) return { exists: false }

    // Hide banner when the receipt already reflects a claimed/reclaimed invite
    // statusCode: 1 = claimed, 2 = reclaimed (per contract)
    const statusCode = Number(r.statusCode ?? 0)
    if (statusCode === 1 || statusCode === 2) return { exists: false }

    return { exists: true, amount: r.amount, assetId: String(r.assetId), timestamp: r.timestamp, invitationId: r.invitationId }
  }

  async claimInviteForPhone(phone: string | undefined, phoneCountry: string | undefined, recipientAddress: string, invitationId?: string): Promise<{ success: boolean; error?: string; txid?: string }> {
    try {
      const { data } = await apolloClient.mutate({
        mutation: CLAIM_INVITE_FOR_PHONE,
        variables: { recipientAddress, invitationId, phone, phoneCountry },
      })
      const res = data?.claimInviteForPhone
      if (!res?.success) return { success: false, error: res?.error || 'No se pudo reclamar la invitación' }
      return { success: true, txid: res.txid }
    } catch (e: any) {
      return { success: false, error: e?.message || 'Error de red al reclamar la invitación' }
    }
  }
}

export const inviteSendService = new InviteSendService()
