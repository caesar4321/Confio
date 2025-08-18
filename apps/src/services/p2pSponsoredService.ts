import { apolloClient } from '../apollo/client'
import {
  PREPARE_P2P_CREATE_TRADE,
  SUBMIT_P2P_CREATE_TRADE,
  ACCEPT_P2P_TRADE,
  PREPARE_P2P_MARK_PAID,
  MARK_P2P_TRADE_PAID,
  PREPARE_P2P_CONFIRM_RECEIVED,
  CONFIRM_P2P_TRADE_RECEIVED,
} from '../apollo/mutations'

import algorandService from './algorandService'

function toJSONStringArray(arr: any[]): string[] {
  return (arr || []).map((e) => (typeof e === 'string' ? e : JSON.stringify(e)))
}

class P2PSponsoredService {
  async createEscrowIfSeller(
    tradeId: string,
    amount: number,
    assetType: string,
  ): Promise<{ success: boolean; txid?: string; error?: string }> {
    try {
      await algorandService.ensureInitialized();
      console.log('[P2P] createEscrowIfSeller: preparing group', { tradeId, amount, assetType })
      const { data } = await apolloClient.mutate({
        mutation: PREPARE_P2P_CREATE_TRADE,
        variables: { tradeId, amount, assetType },
        fetchPolicy: 'no-cache',
      })
      const res = data?.prepareP2pCreateTrade
      console.log('[P2P] createEscrowIfSeller: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      if (!res?.success) return { success: false, error: res?.error || 'Failed to prepare P2P create' }
      const userTxnB64 = res.userTransactions?.[0]
      const sponsorTxns = toJSONStringArray(res.sponsorTransactions)
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      console.log('[P2P] createEscrowIfSeller: got user txn and', sponsorTxns.length, 'sponsor txns')
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] createEscrowIfSeller: user txn signed, submitting group')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const { data: submit } = await apolloClient.mutate({
        mutation: SUBMIT_P2P_CREATE_TRADE,
        variables: { signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns, tradeId },
        fetchPolicy: 'no-cache',
      })
      const sub = submit?.submitP2pCreateTrade
      console.log('[P2P] createEscrowIfSeller: submit result', { success: sub?.success, error: sub?.error, txid: sub?.txid })
      if (!sub?.success) return { success: false, error: sub?.error || 'Failed to submit P2P create' }
      return { success: true, txid: sub.txid }
    } catch (e: any) {
      console.error('[P2P] createEscrowIfSeller error:', e)
      return { success: false, error: String(e?.message || e) }
    }
  }

  async ensureAccepted(tradeId: string): Promise<void> {
    try {
      // Accept trade is sponsor-only; no user signing needed
      console.log('[P2P] ensureAccepted: sending AcceptP2pTrade', { tradeId })
      await apolloClient.mutate({ mutation: ACCEPT_P2P_TRADE, variables: { tradeId }, fetchPolicy: 'no-cache' })
      console.log('[P2P] ensureAccepted: AcceptP2pTrade sent')
    } catch {}
  }

  async markAsPaid(
    tradeId: string,
    paymentRef: string,
  ): Promise<{ success: boolean; txid?: string; error?: string }> {
    try {
      await algorandService.ensureInitialized();
      console.log('[P2P] markAsPaid: preparing', { tradeId, paymentRef })
      const { data } = await apolloClient.mutate({
        mutation: PREPARE_P2P_MARK_PAID,
        variables: { tradeId, paymentRef },
        fetchPolicy: 'no-cache',
      })
      const res = data?.prepareP2pMarkPaid
      console.log('[P2P] markAsPaid: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      if (!res?.success) return { success: false, error: res?.error || 'Failed to prepare mark paid' }
      const userTxnB64 = res.userTransactions?.[0]
      const sponsorTxns = toJSONStringArray(res.sponsorTransactions)
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] markAsPaid: user txn signed, submitting group')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const { data: submit } = await apolloClient.mutate({
        mutation: MARK_P2P_TRADE_PAID,
        variables: { tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns },
        fetchPolicy: 'no-cache',
      })
      const sub = submit?.markP2pTradePaid
      console.log('[P2P] markAsPaid: submit result', { success: sub?.success, error: sub?.error, txid: sub?.txid })
      if (!sub?.success) return { success: false, error: sub?.error || 'Failed to submit mark paid' }
      return { success: true, txid: sub.txid }
    } catch (e: any) {
      console.error('[P2P] markAsPaid error:', e)
      return { success: false, error: String(e?.message || e) }
    }
  }

  async confirmReceived(
    tradeId: string,
  ): Promise<{ success: boolean; txid?: string; error?: string }> {
    try {
      await algorandService.ensureInitialized();
      console.log('[P2P] confirmReceived: preparing', { tradeId })
      const { data } = await apolloClient.mutate({
        mutation: PREPARE_P2P_CONFIRM_RECEIVED,
        variables: { tradeId },
        fetchPolicy: 'no-cache',
      })
      const res = data?.prepareP2pConfirmReceived
      console.log('[P2P] confirmReceived: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      if (!res?.success) return { success: false, error: res?.error || 'Failed to prepare confirm received' }
      const userTxnB64 = res.userTransactions?.[0]
      const sponsorTxns = toJSONStringArray(res.sponsorTransactions)
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] confirmReceived: user txn signed, submitting pair')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const { data: submit } = await apolloClient.mutate({
        mutation: CONFIRM_P2P_TRADE_RECEIVED,
        variables: { tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns },
        fetchPolicy: 'no-cache',
      })
      const sub = submit?.confirmP2pTradeReceived
      console.log('[P2P] confirmReceived: submit result', { success: sub?.success, error: sub?.error, txid: sub?.txid })
      if (!sub?.success) return { success: false, error: sub?.error || 'Failed to submit confirm received' }
      return { success: true, txid: sub.txid }
    } catch (e: any) {
      console.error('[P2P] confirmReceived error:', e)
      return { success: false, error: String(e?.message || e) }
    }
  }
}

export const p2pSponsoredService = new P2PSponsoredService()
