import { useState, useRef, useCallback } from 'react';
import { useMutation, gql } from '@apollo/client';
import { useFocusEffect } from '@react-navigation/native';
import algorandService from '../services/algorandService';

const BUILD_AUTO_SWAP_TRANSACTIONS = gql`
  mutation BuildAutoSwapTransactions($inputAssetType: String!, $amount: String!) {
    buildAutoSwapTransactions(inputAssetType: $inputAssetType, amount: $amount) {
      success
      error
      transactions
    }
  }
`;

const SUBMIT_AUTO_SWAP_TRANSACTIONS = gql`
  mutation SubmitAutoSwapTransactions(
    $internalId: String!
    $signedTransactions: [String]!
    $sponsorTransactions: [String]!
  ) {
    submitAutoSwapTransactions(
      internalId: $internalId
      signedTransactions: $signedTransactions
      sponsorTransactions: $sponsorTransactions
    ) {
      success
      error
      txid
    }
  }
`;

interface UseAutoSwapProps {
    isAuthenticated: boolean;
    myBalancesLoading: boolean;
    usdcBalanceStr: string;
    algoBalanceStr: string;
    refreshAccountBalance: () => void;
}

export const useAutoSwap = ({
    isAuthenticated,
    myBalancesLoading,
    usdcBalanceStr,
    algoBalanceStr,
    refreshAccountBalance
}: UseAutoSwapProps) => {
    const [buildAutoSwapTransactions] = useMutation(BUILD_AUTO_SWAP_TRANSACTIONS);
    const [submitAutoSwapTransactions] = useMutation(SUBMIT_AUTO_SWAP_TRANSACTIONS);

    // Auto-Swap Background Detection Trigger
    // Triggers a silent conversion when USDC > 0 or ALGO > 5.
    const isSwappingRef = useRef(false);
    const [swapModalAsset, setSwapModalAsset] = useState<'ALGO' | 'USDC' | null>(null);

    // Track per-swapKey last attempt time to avoid re-triggering same swap on every render.
    const lastAttemptTimestamps = useRef<Record<string, number>>({});
    const SWAP_COOLDOWN_MS = 60_000; // 60-second cooldown after failure

    useFocusEffect(
        useCallback(() => {
            const checkAndTriggerSwap = async () => {
                if (!isAuthenticated || myBalancesLoading) return;
                // Concurrency guard — ref is always current, unlike state in stale closures
                if (isSwappingRef.current) return;

                const currentUsdc = Number(usdcBalanceStr) || 0;
                const currentAlgo = parseFloat(algoBalanceStr) || 0;

                // Define limits — USDC_THRESHOLD avoids swapping dust left over from slippage
                const USDC_THRESHOLD = 0.10;  // ignore dust < 10¢
                const ALGO_THRESHOLD = 5;
                const ALGO_MIN_SWAP_AMOUNT = 1; // Require at least 1 whole ALGO of excess to trigger

                // Determine input asset and amount
                let swapAssetType = null;
                let swapAmount = '0';

                if (currentUsdc > USDC_THRESHOLD) {
                    swapAssetType = 'USDC';
                    swapAmount = Math.floor(currentUsdc * 1000000).toString();
                } else if (currentAlgo >= ALGO_THRESHOLD + ALGO_MIN_SWAP_AMOUNT) {
                    swapAssetType = 'ALGO';
                    const excessAlgo = currentAlgo - ALGO_THRESHOLD;
                    swapAmount = Math.floor(excessAlgo * 1000000).toString();
                }

                if (!swapAssetType) return;

                const swapKey = `${swapAssetType}-${swapAmount}`;
                const now = Date.now();
                const lastAttempt = lastAttemptTimestamps.current[swapKey] || 0;
                if (now - lastAttempt < SWAP_COOLDOWN_MS) {
                    console.log(`[AutoSwap Hook] Cooldown active for ${swapKey}, skipping.`);
                    return;
                }
                // Record this attempt time
                lastAttemptTimestamps.current[swapKey] = now;

                console.log(`[AutoSwap Hook] Threshold met for ${swapAssetType}. Amount: ${swapAmount}`);
                setSwapModalAsset(swapAssetType as 'ALGO' | 'USDC');
                isSwappingRef.current = true;

                try {
                    // 1. Build swap txns
                    const res = await buildAutoSwapTransactions({
                        variables: {
                            inputAssetType: swapAssetType,
                            amount: swapAmount
                        }
                    });

                    const data = res.data?.buildAutoSwapTransactions;
                    if (!data?.success) {
                        console.warn('[AutoSwap Hook] Backend failed to build swap transactions:', data?.error);
                        return;
                    }

                    if (!data.transactions) {
                        console.warn('[AutoSwap Hook] No transactions field returned from backend');
                        return;
                    }

                    // graphene.JSONString can arrive as a dict (already parsed by Apollo) or as a string
                    let payload = typeof data.transactions === 'string' ? JSON.parse(data.transactions) : data.transactions;
                    // Guard against double-encoded JSON
                    if (typeof payload === 'string') payload = JSON.parse(payload);

                    const unsignedBase64Txns: string[] = payload.transactions || [];
                    const sponsorTxns: string[] = payload.sponsor_transactions || [];
                    const internalId: string = payload.internal_id;

                    if (!unsignedBase64Txns || unsignedBase64Txns.length === 0) {
                        console.warn('[AutoSwap Hook] No transactions returned to sign.');
                        return;
                    }

                    // 2. Parse and locally sign the 'user' txns
                    const { Buffer } = require('buffer');
                    const signedUserTxns = await Promise.all(
                        unsignedBase64Txns.map(async (b64: string) => {
                            const txnBytes = Uint8Array.from(Buffer.from(b64, 'base64'));
                            const signedBytes = await algorandService.signTransactionBytes(txnBytes);
                            return Buffer.from(signedBytes).toString('base64');
                        })
                    );

                    // 3. Submit
                    const sponsorTxnStrings = sponsorTxns.map((s: any) =>
                        typeof s === 'string' ? s : JSON.stringify(s)
                    );

                    const submitRes = await submitAutoSwapTransactions({
                        variables: {
                            internalId,
                            signedTransactions: signedUserTxns,
                            sponsorTransactions: sponsorTxnStrings
                        }
                    });

                    const submitData = submitRes.data?.submitAutoSwapTransactions;
                    if (!submitData?.success) {
                        console.warn('[AutoSwap Hook] Failed to submit auto swap:', submitData?.error);
                    } else {
                        console.log(`[AutoSwap Hook] Swap successful! TXID: ${submitData.txid}`);
                        // Clear the cooldown so future different-amount attempts are fresh
                        delete lastAttemptTimestamps.current[swapKey];
                        refreshAccountBalance();
                    }
                } catch (e) {
                    console.error('[AutoSwap Hook] Exception during auto-swap flow:', e);
                } finally {
                    isSwappingRef.current = false;
                    setSwapModalAsset(null);
                }
            };

            checkAndTriggerSwap();
        }, [usdcBalanceStr, algoBalanceStr, myBalancesLoading, isAuthenticated, buildAutoSwapTransactions, submitAutoSwapTransactions, refreshAccountBalance])
    );

    return {
        swapModalAsset
    };
};
