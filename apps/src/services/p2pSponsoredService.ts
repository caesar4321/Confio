import { apolloClient } from '../apollo/client'
import {
  PREPARE_P2P_CREATE_TRADE,
  SUBMIT_P2P_CREATE_TRADE,
  ACCEPT_P2P_TRADE,
  PREPARE_P2P_MARK_PAID,
  MARK_P2P_TRADE_PAID,
  PREPARE_P2P_CONFIRM_RECEIVED,
  CONFIRM_P2P_TRADE_RECEIVED,
  PREPARE_P2P_CANCEL,
  CANCEL_P2P_TRADE,
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
      // Sync backend account address with current wallet to ensure accept uses correct buyer/seller
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        const addr = algorandService.getCurrentAddress?.();
        if (addr) {
          await apolloClient.mutate({ mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS, variables: { algorandAddress: addr }, fetchPolicy: 'no-cache' });
        }
      } catch {}
      console.log('[P2P] createEscrowIfSeller: preparing group', { tradeId, amount, assetType })
      const { data } = await apolloClient.mutate({
        mutation: PREPARE_P2P_CREATE_TRADE,
        variables: { tradeId, amount, assetType },
        fetchPolicy: 'no-cache',
      })
      const res = data?.prepareP2pCreateTrade
      console.log('[P2P] createEscrowIfSeller: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      if (!res?.success) return { success: false, error: res?.error || 'Failed to prepare P2P create' }
      const userTxnsB64: string[] = res.userTransactions || []
      const sponsorTxns = toJSONStringArray(res.sponsorTransactions)
      // Idempotency: if the trade box already exists on-chain, prepare returns success with no txns
      if (!userTxnsB64.length && (!sponsorTxns || sponsorTxns.length === 0)) {
        console.log('[P2P] createEscrowIfSeller: box already exists on-chain; treating as enabled')
        return { success: true }
      }
      console.log('[P2P] createEscrowIfSeller: got', userTxnsB64.length, 'user txn(s) and', sponsorTxns.length, 'sponsor txns')
      const signedUsers: string[] = []
      for (const utxB64 of userTxnsB64) {
        const userTxnBytes = Uint8Array.from(Buffer.from(utxB64, 'base64'))
        const signed = await algorandService.signTransactionBytes(userTxnBytes)
        signedUsers.push(Buffer.from(signed).toString('base64'))
      }
      console.log('[P2P] createEscrowIfSeller: user txn(s) signed, submitting group')
      const { data: submit } = await apolloClient.mutate({
        mutation: SUBMIT_P2P_CREATE_TRADE,
        variables: { signedUserTxns: signedUsers, sponsorTransactions: sponsorTxns, tradeId },
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
      await algorandService.ensureInitialized();
      // Sync backend account Algorand address with current wallet before accept
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        const addr = algorandService.getCurrentAddress?.();
        if (addr) {
          await apolloClient.mutate({ mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS, variables: { algorandAddress: addr }, fetchPolicy: 'no-cache' });
        }
      } catch {}
      // Build user-signed accept group
      console.log('[P2P] ensureAccepted: preparing accept group', { tradeId })
      const { PREPARE_P2P_ACCEPT_TRADE, SUBMIT_P2P_ACCEPT_TRADE } = await import('../apollo/mutations');
      const { data } = await apolloClient.mutate({ mutation: PREPARE_P2P_ACCEPT_TRADE, variables: { tradeId }, fetchPolicy: 'no-cache' });
      const res = data?.prepareP2pAcceptTrade;
      if (!res?.success) {
        console.warn('[P2P] ensureAccepted: prepare failed', { error: res?.error });
        return;
      }
      const userTxns = res.userTransactions || [];
      const sponsorTxns = toJSONStringArray(res.sponsorTransactions);
      // Idempotency: if already accepted, server returns no txns
      if (!userTxns.length && (!sponsorTxns || sponsorTxns.length === 0)) {
        console.log('[P2P] ensureAccepted: already ACTIVE on-chain');
        return;
      }
      const unsigned = userTxns[0];
      const bytes = Uint8Array.from(Buffer.from(unsigned, 'base64'));
      const signed = await algorandService.signTransactionBytes(bytes);
      const signedB64 = Buffer.from(signed).toString('base64');
      const submit = await apolloClient.mutate({
        mutation: SUBMIT_P2P_ACCEPT_TRADE,
        variables: { tradeId, signedUserTxn: signedB64, sponsorTransactions: sponsorTxns },
        fetchPolicy: 'no-cache',
      });
      const sub = submit?.data?.submitP2pAcceptTrade;
      if (!sub?.success) {
        console.warn('[P2P] ensureAccepted: submit failed', { error: sub?.error });
      } else {
        console.log('[P2P] ensureAccepted: accepted on-chain', { txid: sub.txid });
      }
    } catch (e) {
      console.warn('[P2P] ensureAccepted error:', e);
    }
  }

  async markAsPaid(
    tradeId: string,
    paymentRef: string,
  ): Promise<{ success: boolean; txid?: string; error?: string }> {
    try {
      await algorandService.ensureInitialized();
      // Sync backend account address with current wallet before preparing mark-paid
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        const addr = algorandService.getCurrentAddress?.();
        if (addr) {
          await apolloClient.mutate({ mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS, variables: { algorandAddress: addr }, fetchPolicy: 'no-cache' });
        }
      } catch {}
      // Ensure the trade is accepted on-chain before marking as paid
      await this.ensureAccepted(tradeId)
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
        variables: { tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns, paymentRef },
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

  async cancelExpired(
    tradeId: string,
  ): Promise<{ success: boolean; txid?: string; error?: string }> {
    try {
      await algorandService.ensureInitialized();
      console.log('[P2P] cancelExpired: preparing', { tradeId })
      const { data } = await apolloClient.mutate({
        mutation: PREPARE_P2P_CANCEL,
        variables: { tradeId },
        fetchPolicy: 'no-cache',
      })
      const res = data?.prepareP2pCancel
      console.log('[P2P] cancelExpired: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      if (!res?.success) return { success: false, error: res?.error || 'Failed to prepare cancel' }
      const userTxnB64 = res.userTransactions?.[0]
      const sponsorTxns = toJSONStringArray(res.sponsorTransactions)
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] cancelExpired: user txn signed, submitting pair')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const { data: submit } = await apolloClient.mutate({
        mutation: CANCEL_P2P_TRADE,
        variables: { tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns },
        fetchPolicy: 'no-cache',
      })
      const sub = submit?.cancelP2pTrade
      console.log('[P2P] cancelExpired: submit result', { success: sub?.success, error: sub?.error, txid: sub?.txid })
      if (!sub?.success) return { success: false, error: sub?.error || 'Failed to submit cancel' }
      return { success: true, txid: sub.txid }
    } catch (e: any) {
      console.error('[P2P] cancelExpired error:', e)
      return { success: false, error: String(e?.message || e) }
    }
  }
}

export const p2pSponsoredService = new P2PSponsoredService()
