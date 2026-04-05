import { useState, useRef, useCallback } from 'react';
import { useMutation, gql } from '@apollo/client';
import { useFocusEffect } from '@react-navigation/native';
import algorandService from '../services/algorandService';
import { cusdAppOptInService } from '../services/cusdAppOptInService';

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
    activeAccount?: any;
}

const USDC_THRESHOLD_MICRO = 1_000_000;
const ALGO_RESERVE_THRESHOLD = 3; // Keep 3 ALGO in wallet before auto-swapping excess
const ALGO_MIN_SWAP_AMOUNT = 1; // Require at least 1 whole ALGO of excess to trigger
const MIN_MODAL_VISIBLE_MS = 1200;
const AUTO_SWAP_REQUEST_TIMEOUT_MS = 20000;

const toMicroUnits = (value: string): number => {
    const trimmed = (value || '').trim();
    if (!trimmed) return 0;

    const negative = trimmed.startsWith('-');
    const normalized = negative ? trimmed.slice(1) : trimmed;
    const [wholePartRaw, fractionalRaw = ''] = normalized.split('.');
    const wholePart = wholePartRaw.replace(/\D/g, '') || '0';
    const fractionalPart = fractionalRaw.replace(/\D/g, '').padEnd(6, '0').slice(0, 6);
    const micros = Number(wholePart) * 1_000_000 + Number(fractionalPart);

    return negative ? -micros : micros;
};

const withTimeout = async <T,>(promise: Promise<T>, ms: number, label: string): Promise<T> =>
    Promise.race([
        promise,
        new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error(`timeout:${label}`)), ms)
        )
    ]);

const parseAutoSwapPayload = (raw: any) => {
    if (!raw) {
        throw new Error('missing_auto_swap_payload');
    }

    let payload = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (typeof payload === 'string') {
        payload = JSON.parse(payload);
    }

    if (!payload || typeof payload !== 'object') {
        throw new Error('invalid_auto_swap_payload');
    }

    return payload;
};

export const useAutoSwap = ({
    isAuthenticated,
    myBalancesLoading,
    usdcBalanceStr,
    algoBalanceStr,
    refreshAccountBalance,
    activeAccount
}: UseAutoSwapProps) => {
    const [buildAutoSwapTransactions] = useMutation(BUILD_AUTO_SWAP_TRANSACTIONS);
    const [submitAutoSwapTransactions] = useMutation(SUBMIT_AUTO_SWAP_TRANSACTIONS);

    // Auto-swap silently converts USDC once it reaches the 1 USDC contract minimum
    // or swaps ALGO only when it exceeds the configured reserve.
    const isSwappingRef = useRef(false);
    const [swapModalAsset, setSwapModalAsset] = useState<'ALGO' | 'USDC' | null>(null);

    // Track per-swapKey last attempt time to avoid re-triggering same swap on every render.
    const lastAttemptTimestamps = useRef<Record<string, number>>({});
    const SWAP_COOLDOWN_MS = 60_000; // 60-second cooldown after an attempt

    useFocusEffect(
        useCallback(() => {
            const checkAndTriggerSwap = async () => {
                if (!isAuthenticated || myBalancesLoading) return;
                // Concurrency guard — ref is always current, unlike state in stale closures
                if (isSwappingRef.current) return;

                const currentUsdcMicro = toMicroUnits(usdcBalanceStr);
                const currentAlgo = parseFloat(algoBalanceStr) || 0;

                // Determine input asset and amount
                let swapAssetType = null;
                let swapAmount = '0';
                if (currentUsdcMicro >= USDC_THRESHOLD_MICRO) {
                    swapAssetType = 'USDC';
                    swapAmount = currentUsdcMicro.toString();
                } else {
                    // Keep a hard reserve in ALGO and only swap true excess.
                    const excessAlgo = Math.max(0, currentAlgo - ALGO_RESERVE_THRESHOLD);
                    if (excessAlgo >= ALGO_MIN_SWAP_AMOUNT) {
                        swapAssetType = 'ALGO';
                        swapAmount = Math.floor(excessAlgo * 1000000).toString();
                    }
                }

                if (!swapAssetType) return;
                if (!Number.isFinite(Number(swapAmount)) || Number(swapAmount) <= 0) {
                    return;
                }

                const swapKey = `${swapAssetType}-${swapAmount}`;
                const now = Date.now();
                const lastAttempt = lastAttemptTimestamps.current[swapKey] || 0;
                if (now - lastAttempt < SWAP_COOLDOWN_MS) {
                    return;
                }
                // Record this attempt time
                lastAttemptTimestamps.current[swapKey] = now;

                isSwappingRef.current = true;
                const modalStartTs = Date.now();
                setSwapModalAsset(swapAssetType as 'ALGO' | 'USDC');

                try {
                    // 1) Build swap txns, with one retry after cUSD app opt-in when required.
                    let data: any = null;
                    for (let attempt = 0; attempt < 2; attempt++) {
                        const res = await withTimeout(buildAutoSwapTransactions({
                            variables: {
                                inputAssetType: swapAssetType,
                                amount: swapAmount
                            }
                        }), AUTO_SWAP_REQUEST_TIMEOUT_MS, 'build_auto_swap');
                        data = res.data?.buildAutoSwapTransactions;
                        if (data?.success) break;

                        if (data?.error === 'requires_app_optin' && attempt === 0) {
                            const optInResult = await cusdAppOptInService.handleAppOptIn(activeAccount);
                            if (!optInResult.success) {
                                return;
                            }
                            continue;
                        }

                        return;
                    }

                    if (!data?.success) return;

                    if (!data.transactions) {
                        return;
                    }

                    // graphene.JSONString can arrive as a dict (already parsed by Apollo) or as a string
                    const payload = parseAutoSwapPayload(data.transactions);

                    const unsignedBase64Txns: string[] = payload.transactions || [];
                    const sponsorTxns: string[] = payload.sponsor_transactions || [];
                    const internalId: string = payload.internal_id;

                    if (!unsignedBase64Txns || unsignedBase64Txns.length === 0) {
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

                    const submitRes = await withTimeout(submitAutoSwapTransactions({
                        variables: {
                            internalId,
                            signedTransactions: signedUserTxns,
                            sponsorTransactions: sponsorTxnStrings
                        }
                    }), AUTO_SWAP_REQUEST_TIMEOUT_MS, 'submit_auto_swap');

                    const submitData = submitRes.data?.submitAutoSwapTransactions;
                    if (!submitData?.success) {
                    } else {
                        // Keep a post-success cooldown so stale balances do not immediately retrigger the same swap.
                        lastAttemptTimestamps.current[swapKey] = Date.now();
                        refreshAccountBalance();
                    }
                } catch (e) {
                    console.error('[AutoSwap Hook] Exception during auto-swap flow:', e);
                } finally {
                    const elapsedMs = Date.now() - modalStartTs;
                    if (elapsedMs < MIN_MODAL_VISIBLE_MS) {
                        await new Promise(resolve => setTimeout(resolve, MIN_MODAL_VISIBLE_MS - elapsedMs));
                    }
                    isSwappingRef.current = false;
                    setSwapModalAsset(null);
                }
            };

            checkAndTriggerSwap();
        }, [usdcBalanceStr, algoBalanceStr, myBalancesLoading, isAuthenticated, buildAutoSwapTransactions, submitAutoSwapTransactions, refreshAccountBalance, activeAccount])
    );

    return {
        swapModalAsset
    };
};
