import algosdk from 'algosdk';
import { Buffer } from 'buffer';
import { apolloClient } from '../apollo/client';
import { SUBMIT_SPONSORED_GROUP } from '../apollo/mutations';
import { GET_MY_MIGRATION_STATUS } from '../apollo/queries';
import { gql } from '@apollo/client';

const MARK_WALLET_MIGRATED_MUTATION = gql`
    mutation MarkWalletMigrated($newAddress: String) {
        markWalletMigrated(newAddress: $newAddress) {
            success
            error
        }
    }
`;

const PREPARE_ATOMIC_MIGRATION = gql`
    mutation PrepareAtomicMigration($v1Address: String!, $v2Address: String!) {
        prepareAtomicMigration(v1Address: $v1Address, v2Address: $v2Address) {
            success
            error
            transactions
        }
    }
`;
import { secureDeterministicWallet, retrieveClientSecret, getOrCreateMasterSecret, storeClientSecret, deriveWalletV2 } from './secureDeterministicWallet';
import authService from './authService';
import { API_URL, CONFIO_ASSET_ID, CUSD_ASSET_ID, USDC_ASSET_ID } from '../config/env';


// Use public AlgoNode API for client-side state checks (Read-Only)
// This avoids needing Algod credentials on the client
const MAINNET_ALGOD = 'https://mainnet-api.algonode.cloud';
const TESTNET_ALGOD = 'https://testnet-api.algonode.cloud';

interface MigrationStatus {
    needsMigration: boolean;
    v1Balance?: number;
    v1Assets?: number[];
    v1Address?: string;
    v2Address?: string;
}

class WalletMigrationService {
    private algodClient: any;

    constructor() {
        this.initAlgod();
    }

    private initAlgod() {
        // Determine network based on API URL
        const safeUrl = API_URL || '';
        const isMainnet = safeUrl.includes('confio.lat') || safeUrl.includes('mainnet');
        const server = isMainnet ? MAINNET_ALGOD : TESTNET_ALGOD;
        this.algodClient = new algosdk.Algodv2('', server, '');
    }

    /**
     * Check if the current user needs to migrate from V1 to V2.
     * Logic:
     * 1. If V2 secret exists AND V1 wallet is empty/closed -> False (Done).
     * 2. If V2 secret exists AND V1 wallet has balance -> True (Resume).
     * 3. If V2 secret missing AND V1 wallet exists -> True (Start).
     * 4. If V2 secret missing AND V1 wallet missing -> False (New User, handled by V2 creation).
     */
    async checkNeedsMigration(
        iss: string,
        sub: string,
        aud: string,
        provider: 'google' | 'apple',
        accountIndex: number = 0,
        businessId?: string
    ): Promise<MigrationStatus> {

        try {
            // 0. Check Backend Status Implementation
            try {
                const { data } = await apolloClient.query({
                    query: GET_MY_MIGRATION_STATUS,
                    fetchPolicy: 'network-only' // Always fetch fresh
                });

                const myAccount = data?.userAccounts?.find((a: any) =>
                    a.accountType?.toLowerCase() === 'personal' && String(a.accountIndex) === String(accountIndex)
                );

                if (myAccount?.isKeylessMigrated) {
                    console.log('[MigrationService] Already migrated on backend ✅', myAccount);

                    if (myAccount.algorandAddress) {
                        try {
                            // TRUST BUT VERIFY (ZOMBIE TYPE 2 FIX)
                            // Even if backend says migrated, check if V2 is actually funded.
                            // If V2 is empty, it might be a Failed Atomic Migration (Backend=True, Chain=False).

                            // Check V2 on-chain state
                            const v2CheckInfo = await this.algodClient.accountInformation(myAccount.algorandAddress).do();
                            const v2Balance = v2CheckInfo.amount;
                            const v2Assets = v2CheckInfo.assets || [];

                            const relevantV2Assets = v2Assets.filter((a: any) => {
                                const aid = a['asset-id'];
                                const amount = a['amount'];
                                return ((aid === CONFIO_ASSET_ID || aid === CUSD_ASSET_ID || aid === USDC_ASSET_ID) && amount > 0);
                            });
                            // If V2 has < 1.0 ALGO and NO Asset Balance, it is likely just "Opted In" but not migrated.
                            const isV2Empty = (v2Balance < 1000000 && relevantV2Assets.length === 0);

                            if (isV2Empty) {
                                console.log('[MigrationService] TRUST BUT VERIFY: Backend says Migrated, but V2 is EMPTY. Checking V1 to confirm...');

                                // Refinement: Only handle as Zombie if V1 HAS FUNDS. 
                                // Otherwise, it's just a new user or empty user.
                                try {
                                    const v1Wallet = await secureDeterministicWallet.restoreLegacyV1Wallet(
                                        iss, sub, aud, provider, 'personal', accountIndex, businessId
                                    );
                                    const v1Address = v1Wallet.address;

                                    const v1Info = await this.algodClient.accountInformation(v1Address).do();
                                    const v1Balance = v1Info.amount;
                                    const v1Assets = v1Info.assets || [];
                                    const relevantV1Assets = v1Assets.filter((a: any) => {
                                        const aid = a['asset-id'];
                                        const amount = a['amount'];
                                        return ((aid === CONFIO_ASSET_ID || aid === CUSD_ASSET_ID || aid === USDC_ASSET_ID) && amount > 0);
                                    });

                                    if (relevantV1Assets.length > 0 || v1Balance >= 300000) {
                                        console.warn('[MigrationService] ZOMBIE CONFIRMED: V2 Empty, but V1 has funds. Forcing Migration Resume.');
                                        // Fall through to standard check below (which will return true)
                                    } else {
                                        console.log('[MigrationService] False Alarm: V1 is also empty/dust. User is legitimately empty or new. Confirmed Migrated.');
                                        // Real Success (Empty)
                                        if (!authService) {
                                            throw new Error('AuthService instance is undefined');
                                        }
                                        await authService.forceUpdateLocalAlgorandAddress(myAccount.algorandAddress, {
                                            type: 'personal',
                                            index: accountIndex,
                                            businessId: businessId
                                        });
                                        return { needsMigration: false, v2Address: myAccount.algorandAddress };
                                    }
                                } catch (e) {
                                    console.warn('[MigrationService] Failed to check V1, assuming Valid Empty User:', e);
                                    return { needsMigration: false, v2Address: myAccount.algorandAddress };
                                }

                            } else {
                                // Real Success
                                // Force update local keychain to match backend
                                if (!authService) {
                                    throw new Error('AuthService instance is undefined');
                                }
                                await authService.forceUpdateLocalAlgorandAddress(myAccount.algorandAddress, {
                                    type: 'personal',
                                    index: accountIndex,
                                    businessId: businessId
                                });
                                console.log('[MigrationService] Verified V2 funded. Syncing local keychain.');
                                return { needsMigration: false, v2Address: myAccount.algorandAddress };
                            }

                        } catch (err) {
                            console.warn('[MigrationService] Failed to verify V2 or sync local:', JSON.stringify(err, Object.getOwnPropertyNames(err)));
                            // If verification fails (network), fallback to trusting backend (safest default)
                            // return { needsMigration: false, v2Address: myAccount.algorandAddress };
                            // Actually, if network fails, we probably cant migrate anyway.
                        }
                    } else {
                        console.warn('[MigrationService] Migrated but no address?!');
                    }
                    // If we are here, it means we detected Empty V2 (Type 2 Zombie) or fell through.
                    // We continue to standard V1 check below.
                } else {
                    console.log('[MigrationService] Backend says NOT migrated ❌ ' + JSON.stringify({
                        myAccount,
                        allAccounts: data?.userAccounts?.map((a: any) => ({
                            type: a.accountType,
                            index: a.accountIndex,
                            idxType: typeof a.accountIndex,
                            migrated: a.isKeylessMigrated,
                            raw: JSON.stringify(a)
                        })),
                        lookingFor: { accountIndex, type: 'personal' }
                    }, null, 2));
                }
            } catch (e) {
                console.warn('[MigrationService] Backend status check failed, falling back to chain check:', e);
            }

            // Use namespaced V2 secret check
            const v2Secret = await getOrCreateMasterSecret(sub);

            // Restore Legacy V1 Wallet to check its state
            // We purposefully don't use 'createOrRestoreWallet' because it might default to V2
            const v1Wallet = await secureDeterministicWallet.restoreLegacyV1Wallet(
                iss, sub, aud, provider, 'personal', accountIndex, businessId
            );

            const v1Address = v1Wallet.address;
            let v1Info;

            try {
                v1Info = await this.algodClient.accountInformation(v1Address).do();
            } catch (e) {
                // Account not found on chain -> Treat as empty/new
                return { needsMigration: false, v1Address: undefined };
            }

            const balance = v1Info.amount;
            const assets = v1Info.assets || [];
            // Filter for relevant assets only (CONFIO, CUSD, USDC)
            // This prevents "Junk Assets" (airdrops/spam) from triggering infinite migration loops
            const relevantAssets = assets.filter((a: any) => {
                const aid = a['asset-id'];
                return (
                    aid === CONFIO_ASSET_ID ||
                    aid === CUSD_ASSET_ID ||
                    aid === USDC_ASSET_ID
                );
            });

            const hasRelevantAssets = relevantAssets.length > 0;

            // If V1 is practically empty (only min balance or less, and no RELEVANT assets)
            // We consider it "migrated" or "empty"
            // We ignore junk assets - they will be abandoned in the legacy wallet
            // If V1 is practically empty (only min balance or less, and no RELEVANT assets)
            if (!hasRelevantAssets && balance < 300000) {
                console.log('[MigrationService] V1 is empty/dust. Checking if we need to self-heal (Zombie State).');

                // Check if actually migrated but backend missed it
                if (v2Secret) {
                    try {
                        const v2Wallet = deriveWalletV2(v2Secret, {
                            iss, sub, aud, accountType: 'personal', accountIndex, businessId
                        });
                        const v2Address = v2Wallet.address;

                        const v2Info = await this.algodClient.accountInformation(v2Address).do();
                        // If V2 has confirmed implementation (assets or significant balance)
                        if (v2Info.amount >= 300000 || (v2Info.assets && v2Info.assets.length > 0)) {
                            console.log('[MigrationService] ZOMBIE DETECTED: V1 empty, V2 funded. Self-healing...');

                            // 1. Tell Backend
                            await apolloClient.mutate({
                                mutation: MARK_WALLET_MIGRATED_MUTATION,
                                variables: { newAddress: v2Address }
                            });

                            // 2. Update Local
                            if (authService) {
                                await authService.forceUpdateLocalAlgorandAddress(v2Address, {
                                    type: 'personal', index: accountIndex, businessId
                                });
                            }

                            console.log('[MigrationService] Self-healing complete. Switched to V2.');
                            return { needsMigration: false, v2Address };
                        }
                    } catch (e) {
                        console.warn('[MigrationService] Failed to check/heal V2 state:', e);
                    }
                }

                console.log('[MigrationService] V1 empty and no active V2 found. Marking as done/new.');
                return { needsMigration: false, v1Address, v1Balance: 0 };
            }

            // V1 has contents.

            if (v2Secret) {
                // V2 exists but V1 still has funds -> Resume Migration
                const v2Wallet = deriveWalletV2(v2Secret, {
                    iss, sub, aud, accountType: 'personal', accountIndex, businessId
                });
                return {
                    needsMigration: true,
                    v1Balance: balance,
                    v1Assets: assets.map((a: any) => a['asset-id']),
                    v1Address,
                    v2Address: v2Wallet.address
                };
            } else {
                // No V2 secret, but V1 has funds -> Start Migration
                return {
                    needsMigration: true,
                    v1Balance: balance,
                    v1Assets: assets.map((a: any) => a['asset-id']),
                    v1Address,
                    // V2 address unknown until generation
                };
            }

        } catch (error) {
            console.error('[MigrationService] Error checking status:', error);
            // Fail safe: False
            return { needsMigration: false };
        }
    }

    /**
     * Execute the Atomic Sweep Migration.
     * 1. Generate/Load V2 Secret.
     * 2. Opt-in V2 to all V1 assets (Mirroring).
     * 3. Close V1 assets to V2.
     * 4. Close V1 Algo to V2.
     * 5. Submit.
     */
    async performMigration(
        iss: string,
        sub: string,
        aud: string,
        provider: 'google' | 'apple',
        accountIndex: number = 0,
        businessId?: string
    ): Promise<boolean> {
        try {
            console.log('[MigrationService] Starting atomic migration...');

            // 1. Get or Create Master Secret (NEVER overwrites existing)
            // Properly namespaced by User Sub
            const v2Secret = await getOrCreateMasterSecret(sub);
            console.log('[MigrationService] V2 Secret ready');

            const v2Wallet = deriveWalletV2(v2Secret, {
                iss, sub, aud, accountType: 'personal', accountIndex, businessId
            });
            const v2Address = v2Wallet.address;

            // 2. Restore V1 Wallet for signing
            console.log('[MigrationService] Restoring Legacy V1 Wallet with inputs:', JSON.stringify({
                iss, sub, aud, provider, type: 'personal', index: accountIndex, businessId: businessId || 'undefined'
            }));
            const v1Wallet = await secureDeterministicWallet.restoreLegacyV1Wallet(
                iss, sub, aud, provider, 'personal', accountIndex, businessId
            );
            const v1Address = v1Wallet.address;
            console.log('[MigrationService] DERIVED V1 ADDRESS:', v1Address);

            console.log(`[MigrationService] Migrating from ${v1Address} to ${v2Address}`);

            // 3. Call Backend to Prepare Atomic Migration Group
            // The backend Sponsors MBR and Fees, and constructs the optimized group
            const prepResult = await apolloClient.mutate({
                mutation: PREPARE_ATOMIC_MIGRATION,
                variables: {
                    v1Address,
                    v2Address
                }
            });

            if (!prepResult.data?.prepareAtomicMigration?.success) {
                throw new Error(prepResult.data?.prepareAtomicMigration?.error || 'Failed to prepare migration group');
            }

            const rawTransactions = JSON.parse(prepResult.data.prepareAtomicMigration.transactions);
            if (!rawTransactions || rawTransactions.length === 0) {
                // Nothing to migrate or already done
                console.log('[MigrationService] No transactions returned (nothing to migrate?). Marking complete.');
                await apolloClient.mutate({ mutation: MARK_WALLET_MIGRATED_MUTATION });
                return true;
            }

            console.log(`[MigrationService] Received ${rawTransactions.length} atomic ops from backend`);

            // 4. Sign Transactions
            // We need to sign V1 and V2 transactions. Sponsor txns are already signed.
            const nacl = require('tweetnacl');

            // Restore V1 Key
            const v1Seed = new Uint8Array(Buffer.from(v1Wallet.privSeedHex, 'hex'));
            const v1KeyPair = nacl.sign.keyPair.fromSeed(v1Seed);
            const v1Sk = new Uint8Array(64);
            v1Sk.set(v1Seed);
            v1Sk.set(v1KeyPair.publicKey, 32);

            // Restore V2 Key
            const v2Seed = new Uint8Array(Buffer.from(v2Wallet.privSeedHex, 'hex'));
            const v2KeyPair = nacl.sign.keyPair.fromSeed(v2Seed);
            const v2Sk = new Uint8Array(64);
            v2Sk.set(v2Seed);
            v2Sk.set(v2KeyPair.publicKey, 32);

            const signedBlobList: string[] = [];

            for (const item of rawTransactions) {
                const txnB64 = item.transaction;
                const signerType = item.signer; // 'sponsor', 'v1', 'v2'
                const isSigned = item.signed;

                if (isSigned) {
                    // Already signed (Sponsor), just pass through
                    signedBlobList.push(txnB64);
                } else {
                    // Needs signing
                    const txnBytes = Buffer.from(txnB64, 'base64');
                    const decoded = algosdk.decodeObj(txnBytes);
                    // Re-instantiate transaction object to sign it
                    // The SDK decodeObj returns a plain object structure usually, or specific SDK version might vary.
                    // Safe pattern: use algosdk.decodeUnsignedTransaction
                    const txn = algosdk.decodeUnsignedTransaction(txnBytes);

                    let signedTxn: Uint8Array;
                    if (signerType === 'v1') {
                        signedTxn = txn.signTxn(v1Sk);
                    } else if (signerType === 'v2') {
                        signedTxn = txn.signTxn(v2Sk);
                    } else {
                        throw new Error(`Unknown signer type: ${signerType}`);
                    }

                    signedBlobList.push(Buffer.from(signedTxn).toString('base64'));
                }
            }

            // 5. Submit Complete Group
            // We reuse SubmitSponsoredGroupMutation which takes signedUserTxn. 
            // Since we have a mixed list including Sponsor txns, we'll pass the whole list as a JSON string
            // OR use SubmitBusinessOptInGroupMutation which accepts a list.
            // Actually, SubmitSponsoredGroupMutation expects 'signedUserTxn' effectively as one blob if grouped?
            // Checking definition: SubmitSponsoredGroupMutation takes `signed_user_txn` (string) and `signed_sponsor_txn`.
            // But we have a complex group.

            // We should use a mutation that accepts a list of blobs.
            // `SubmitBusinessOptInGroupMutation` takes `signed_transactions` (JSON list).
            // Let's repurpose that or assuming `SubmitSponsoredGroupMutation` can handle a list if we created a new specific mutation?
            // Wait, we defined `PrepareAtomicMigrationMutation` but checking `blockchain/mutations.py`, we didn't add a specific "SubmitAtomicMigration".

            // However, `SubmitBusinessOptInGroupMutation` (which we have) calls `submit_sponsored_group` logic?
            // Let's double check `SubmitBusinessOptInGroupMutation` implementation in the artifacts/memory. 
            // It takes `signed_transactions` list and submits them. Perfect.

            const SUBMIT_ATOMIC_GROUP = gql`
                mutation SubmitBusinessOptInGroup($signedTransactions: JSONString!) {
                    submitBusinessOptInGroup(signedTransactions: $signedTransactions) {
                        success
                        error
                        transactionId
                    }
                }
            `;

            console.log('[MigrationService] Submitting signed atomic group...');
            const submitResult = await apolloClient.mutate({
                mutation: SUBMIT_ATOMIC_GROUP,
                variables: {
                    signedTransactions: JSON.stringify(signedBlobList)
                }
            });

            if (submitResult.data?.submitBusinessOptInGroup?.success) {
                console.log('[MigrationService] Migration successful (TxID: ' + submitResult.data.submitBusinessOptInGroup.transactionId + ')');

                // Call backend to flag user as migrated
                // Call backend to flag user as migrated with RETRY logic
                let markedSuccess = false;
                for (let attempt = 1; attempt <= 3; attempt++) {
                    try {
                        await apolloClient.mutate({
                            mutation: MARK_WALLET_MIGRATED_MUTATION,
                            variables: {
                                newAddress: v2Address
                            }
                        });
                        markedSuccess = true;
                        console.log(`[MigrationService] Marked as migrated on backend (Address updated to ${v2Address}).`);
                        break;
                    } catch (err) {
                        console.warn(`[MigrationService] Attempt ${attempt} to mark migration failed:`, err);
                        if (attempt < 3) await new Promise(r => setTimeout(r, 1000)); // Wait 1s
                    }
                }

                if (!markedSuccess) {
                    console.error('[MigrationService] CRITICAL: Failed to mark migration on backend after 3 attempts. Local state will be updated, but backend might de-sync.');
                    // We continue anyway to update local keychain so user can use the app
                }

                try {
                    // CRITICAL FIX: Force update local keychain to V2 address so UI reflects it immediately
                    await authService.forceUpdateLocalAlgorandAddress(v2Address, {
                        type: 'personal',
                        index: accountIndex,
                        businessId
                    });
                    console.log('[MigrationService] Local keychain synchronized with V2 address.');

                } catch (e) {
                    console.error('[MigrationService] CRITICAL: Failed to sync local keychain:', e);
                }

                return true;
            } else {
                console.error('[MigrationService] Migration submission failed:', submitResult.data?.submitBusinessOptInGroup?.error);
                return false;
            }


        } catch (error) {
            console.error('[MigrationService] Perform migration error:', error);
            throw error;
        }
    }
}

export const migrationService = new WalletMigrationService();
