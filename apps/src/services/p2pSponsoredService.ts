import { apolloClient } from '../apollo/client'
import { P2PWsSession, toJSONStringArray } from './p2pWs'

import algorandService from './algorandService'

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
      console.log('[P2P] createEscrowIfSeller: preparing group (WS)', { tradeId, amount, assetType })
      const ws = new P2PWsSession()
      const res = await ws.prepare({ action: 'create', tradeId, amount, assetType })
      console.log('[P2P] createEscrowIfSeller: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      // WS returns undefined for success on pack; treat absence of txns as already ok
      const userTxnsB64: string[] = (res as any)?.user_transactions || []
      const sponsorTxns = toJSONStringArray(((res as any)?.sponsor_transactions || []).map((e: any) => ({ txn: e.txn, index: e.index })))
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
      console.log('[P2P] createEscrowIfSeller: user txn(s) signed, submitting group (WS)')
      const submit = await ws.submit({ action: 'create', tradeId, signedUserTxns: signedUsers, sponsorTransactions: sponsorTxns })
      console.log('[P2P] createEscrowIfSeller: submit result', submit)
      return { success: true, txid: (submit as any).txid || (submit as any).transaction_id }
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
      const ws = new P2PWsSession();
      const res = await ws.prepare({ action: 'accept', tradeId });
      const userTxns: string[] = (res as any)?.user_transactions || [];
      const sponsorTxns = toJSONStringArray(((res as any)?.sponsor_transactions || []).map((e: any) => ({ txn: e.txn, index: e.index })));
      // Idempotency: if already accepted, server returns no txns
      if (!userTxns.length && (!sponsorTxns || sponsorTxns.length === 0)) {
        console.log('[P2P] ensureAccepted: already ACTIVE on-chain');
        return;
      }
      const unsigned = userTxns[0];
      const bytes = Uint8Array.from(Buffer.from(unsigned, 'base64'));
      const signed = await algorandService.signTransactionBytes(bytes);
      const signedB64 = Buffer.from(signed).toString('base64');
      const submit = await ws.submit({ action: 'accept', tradeId, signedUserTxn: signedB64, sponsorTransactions: sponsorTxns });
      console.log('[P2P] ensureAccepted: accepted on-chain', submit);
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
      const ws = new P2PWsSession()
      const res = await ws.prepare({ action: 'mark_paid', tradeId, paymentRef })
      console.log('[P2P] markAsPaid: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      const userTxnB64 = (res as any)?.user_transactions?.[0]
      const sponsorTxns = toJSONStringArray(((res as any)?.sponsor_transactions || []).map((e: any) => ({ txn: e.txn, index: e.index })))
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] markAsPaid: user txn signed, submitting group')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const submit = await ws.submit({ action: 'mark_paid', tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns })
      console.log('[P2P] markAsPaid: submit result', submit)
      return { success: true, txid: (submit as any).txid || (submit as any).transaction_id }
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
      const ws = new P2PWsSession()
      const res = await ws.prepare({ action: 'confirm_received', tradeId })
      console.log('[P2P] confirmReceived: prepare result', { success: res?.success, error: res?.error, groupId: res?.groupId })
      const userTxnB64 = (res as any)?.user_transactions?.[0]
      const sponsorTxns = toJSONStringArray(((res as any)?.sponsor_transactions || []).map((e: any) => ({ txn: e.txn, index: e.index })))
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] confirmReceived: user txn signed, submitting pair')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const submit = await ws.submit({ action: 'confirm_received', tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns })
      console.log('[P2P] confirmReceived: submit result', submit)
      return { success: true, txid: (submit as any).txid || (submit as any).transaction_id }
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
      console.log('[P2P] cancelExpired: preparing (WS)', { tradeId })
      const ws = new P2PWsSession()
      const res = await ws.prepare({ action: 'cancel', tradeId })
      const userTxnB64 = (res as any)?.user_transactions?.[0]
      const sponsorTxns = toJSONStringArray(((res as any)?.sponsor_transactions || []).map((e: any) => ({ txn: e.txn, index: e.index })))
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] cancelExpired: user txn signed, submitting pair (WS)')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const submit = await ws.submit({ action: 'cancel', tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns })
      console.log('[P2P] cancelExpired: submit result', submit)
      return { success: true, txid: (submit as any).txid || (submit as any).transaction_id }
    } catch (e: any) {
      console.error('[P2P] cancelExpired error:', e)
      return { success: false, error: String(e?.message || e) }
    }
  }

  async openDispute(
    tradeId: string,
    reason: string,
  ): Promise<{ success: boolean; txid?: string; error?: string }> {
    try {
      await algorandService.ensureInitialized();
      // Sync backend account address with current wallet before preparing dispute
      try {
        const { UPDATE_ACCOUNT_ALGORAND_ADDRESS } = await import('../apollo/queries');
        const addr = algorandService.getCurrentAddress?.();
        if (addr) {
          await apolloClient.mutate({ mutation: UPDATE_ACCOUNT_ALGORAND_ADDRESS, variables: { algorandAddress: addr }, fetchPolicy: 'no-cache' });
        }
      } catch {}
      console.log('[P2P] openDispute: preparing (WS)', { tradeId })
      const ws = new P2PWsSession()
      const res = await ws.prepare({ action: 'open_dispute', tradeId, reason })
      const userTxnB64 = (res as any)?.user_transactions?.[0]
      const sponsorTxns = toJSONStringArray(((res as any)?.sponsor_transactions || []).map((e: any) => ({ txn: e.txn, index: e.index })))
      if (!userTxnB64) return { success: false, error: 'No user transaction returned' }
      const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'))
      const signedUser = await algorandService.signTransactionBytes(userTxnBytes)
      console.log('[P2P] openDispute: user txn signed, submitting pair (WS)')
      const signedUserB64 = Buffer.from(signedUser).toString('base64')
      const submit = await ws.submit({ action: 'open_dispute', tradeId, signedUserTxn: signedUserB64, sponsorTransactions: sponsorTxns })
      console.log('[P2P] openDispute: submit result', submit)
      return { success: true, txid: (submit as any).txid || (submit as any).transaction_id }
    } catch (e: any) {
      console.error('[P2P] openDispute error:', e)
      return { success: false, error: String(e?.message || e) }
    }
  }
}

export const p2pSponsoredService = new P2PSponsoredService()
