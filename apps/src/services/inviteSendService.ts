import { Buffer } from 'buffer'
import { apolloClient } from '../apollo/client'
import { PREPARE_INVITE_FOR_PHONE, SUBMIT_INVITE_FOR_PHONE } from '../apollo/mutations'
import { INVITE_RECEIPT_FOR_PHONE } from '../apollo/queries'
import algorandService from './algorandService'

type PreparedInvite = {
  transactions: { txn: string; index?: number }[]
  sponsorTransactions: { txn: string; index: number }[]
  groupId: string
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
    if (!res?.success) return { success: false, error: res?.error || 'Failed to prepare invite' }

    // Normalize: backend returns JSON strings for arrays
    const txsRaw = res.transactions
    const sponsorsRaw = res.sponsorTransactions
    const transactions = typeof txsRaw === 'string' ? JSON.parse(txsRaw) : (txsRaw || [])
    const sponsorTransactionsArr = typeof sponsorsRaw === 'string' ? JSON.parse(sponsorsRaw) : (sponsorsRaw || [])

    // Normalize to typed structure
    const prepared: PreparedInvite = {
      transactions,
      sponsorTransactions: sponsorTransactionsArr.sort((a: any, b: any) => (a.index ?? 0) - (b.index ?? 0)),
      groupId: res.groupId,
      invitationId: res.invitationId,
    }
    return { success: true, prepared }
  }

  async submitPreparedInvite(prepared: PreparedInvite): Promise<{ success: boolean; error?: string; txid?: string }> {
    // Expect exactly one user txn to sign (the AXFER)
    const user = prepared.transactions?.[0]
    if (!user?.txn) return { success: false, error: 'Missing user transaction to sign' }

    const userTxnBytes = Buffer.from(user.txn, 'base64')
    // Use centralized signing which restores wallet scope from JWT + account context
    const signedUserTxn = await algorandService.signTransactionBytes(userTxnBytes)
    const signedAxferB64 = Buffer.from(signedUserTxn).toString('base64')

    // Map sponsor txns to unsigned base64 in correct order
    const sponsorUnsigned = prepared.sponsorTransactions.map((t) => t.txn)

    const { data } = await apolloClient.mutate({
      mutation: SUBMIT_INVITE_FOR_PHONE,
      variables: { signedAxferB64, sponsorUnsigned },
    })
    const res = data?.submitInviteForPhone
    if (!res?.success) return { success: false, error: res?.error || 'Invite submission failed' }
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
    { exists: true; amount: number; assetId: number; timestamp: number } | { exists: false }
  > {
    const { data } = await apolloClient.query({
      query: INVITE_RECEIPT_FOR_PHONE,
      fetchPolicy: 'network-only',
      variables: { phone, phoneCountry },
    })
    const r = data?.inviteReceiptForPhone
    if (!r?.exists) return { exists: false }
    return { exists: true, amount: r.amount, assetId: r.assetId, timestamp: r.timestamp }
  }
}

export const inviteSendService = new InviteSendService()
