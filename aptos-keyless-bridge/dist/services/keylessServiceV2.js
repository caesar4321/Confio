"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.keylessServiceV2 = exports.KeylessServiceV2 = void 0;
const ts_sdk_1 = require("@aptos-labs/ts-sdk");
const logger_1 = __importDefault(require("../logger"));
const logger = logger_1.default;
class KeylessServiceV2 {
    aptos;
    sponsorAccount;
    pendingTransactions;
    constructor() {
        // Use Nodit API instead of default Aptos RPC
        const noditApiKey = process.env.NODIT_API_KEY;
        const network = (process.env.APTOS_NETWORK || 'testnet') === 'mainnet'
            ? ts_sdk_1.Network.MAINNET
            : ts_sdk_1.Network.TESTNET;
        // Configure to use Nodit endpoints
        const isMainnet = network === ts_sdk_1.Network.MAINNET;
        const noditEndpoint = isMainnet
            ? 'https://aptos-mainnet.nodit.io/v1'
            : 'https://aptos-testnet.nodit.io/v1';
        const config = new ts_sdk_1.AptosConfig({
            network,
            // Override the default fullnode URL with Nodit
            fullnode: noditApiKey ? noditEndpoint : undefined,
            // Add API key as custom header if provided
            clientConfig: noditApiKey ? {
                HEADERS: {
                    'X-API-KEY': noditApiKey
                }
            } : undefined
        });
        this.aptos = new ts_sdk_1.Aptos(config);
        // Load sponsor account from environment
        const sponsorPrivateKey = process.env.APTOS_SPONSOR_PRIVATE_KEY;
        if (!sponsorPrivateKey) {
            throw new Error('APTOS_SPONSOR_PRIVATE_KEY not configured in environment variables');
        }
        // Create account from private key using Ed25519PrivateKey
        const { Ed25519PrivateKey } = require('@aptos-labs/ts-sdk');
        const privateKeyHex = sponsorPrivateKey.startsWith('0x')
            ? sponsorPrivateKey.slice(2)
            : sponsorPrivateKey;
        const privateKey = new Ed25519PrivateKey(privateKeyHex);
        this.sponsorAccount = ts_sdk_1.Account.fromPrivateKey({ privateKey });
        logger.info('KeylessServiceV2 initialized');
        logger.info('Sponsor address:', this.sponsorAccount.accountAddress.toString());
        logger.info('Using RPC endpoint:', noditApiKey ? 'Nodit API' : 'Aptos Labs API');
    }
    /**
     * Submit a sponsored transaction using the official SDK pattern
     * EXPERIMENTAL: Recreate keyless account on bridge side for direct signing
     */
    async submitSponsoredTransaction(request) {
        try {
            logger.info('Processing sponsored transaction with official SDK pattern');
            logger.info('Sender:', request.senderAddress);
            logger.info('Recipient:', request.recipientAddress);
            logger.info('Amount:', request.amount);
            logger.info('Has JWT for direct signing:', !!request.jwt);
            logger.info('Has ephemeral key pair:', !!request.ephemeralKeyPair);
            // EXPERIMENTAL APPROACH 1: If we have JWT and ephemeral key data, recreate keyless account
            if (request.jwt && request.ephemeralKeyPair) {
                logger.info('EXPERIMENTAL: Attempting direct keyless account recreation and signing');
                try {
                    // Import required Aptos SDK classes
                    const { KeylessAccount, EphemeralKeyPair, Ed25519PrivateKey } = require('@aptos-labs/ts-sdk');
                    // Recreate the ephemeral key pair from the data
                    const ephemeralPrivateKey = new Ed25519PrivateKey(request.ephemeralKeyPair.privateKey);
                    const ephemeralKeyPair = new EphemeralKeyPair({
                        privateKey: ephemeralPrivateKey,
                        expiryDateSecs: Math.floor(Date.now() / 1000) + 3600, // 1 hour from now
                        nonce: request.ephemeralKeyPair.nonce
                    });
                    logger.info('Recreated ephemeral key pair with nonce:', request.ephemeralKeyPair.nonce);
                    // Recreate the keyless account
                    const keylessAccount = await KeylessAccount.create({
                        address: request.senderAddress,
                        jwt: request.jwt,
                        ephemeralKeyPair,
                        pepper: new Uint8Array(31) // Default pepper, will be fetched if needed
                    });
                    logger.info('Successfully recreated keyless account');
                    logger.info('Account address matches:', keylessAccount.accountAddress.toString() === request.senderAddress);
                    // Build the transaction
                    const transaction = await this.aptos.transaction.build.simple({
                        sender: keylessAccount.accountAddress,
                        withFeePayer: true,
                        data: {
                            function: this.getTransferFunction(request.tokenType),
                            functionArguments: [request.recipientAddress, request.amount]
                        }
                    });
                    logger.info('Built transaction with fee payer flag');
                    // Use the official SDK pattern: let the keyless account sign directly
                    const senderAuthenticator = this.aptos.transaction.sign({
                        signer: keylessAccount,
                        transaction
                    });
                    logger.info('Keyless account signed transaction directly');
                    // Sign as fee payer (sponsor)
                    const sponsorSignature = this.aptos.transaction.signAsFeePayer({
                        signer: this.sponsorAccount,
                        transaction
                    });
                    logger.info('Sponsor signature created');
                    // Submit with both authenticators
                    const pendingTxn = await this.aptos.transaction.submit.simple({
                        transaction,
                        senderAuthenticator,
                        feePayerAuthenticator: sponsorSignature
                    });
                    logger.info('Transaction submitted with direct keyless signing:', pendingTxn.hash);
                    // Wait for confirmation
                    const committedTxn = await this.aptos.waitForTransaction({
                        transactionHash: pendingTxn.hash
                    });
                    if (committedTxn.success) {
                        logger.info('✅ Direct keyless signing successful:', pendingTxn.hash);
                        return {
                            success: true,
                            transactionHash: pendingTxn.hash
                        };
                    }
                    else {
                        logger.error('Transaction failed:', committedTxn.vm_status);
                        return {
                            success: false,
                            error: `Transaction failed: ${committedTxn.vm_status}`
                        };
                    }
                }
                catch (directSigningError) {
                    logger.error('Direct keyless signing failed:', directSigningError);
                    logger.info('Falling back to pre-generated authenticator approach');
                }
            }
            // FALLBACK APPROACH: Use the pre-generated authenticator
            logger.info('Using pre-generated authenticator approach');
            // Decode the sender's authenticator
            const senderAuthBytes = Buffer.from(request.senderAuthenticator, 'base64');
            const deserializer = new ts_sdk_1.Deserializer(new Uint8Array(senderAuthBytes));
            const senderAuthenticator = ts_sdk_1.AccountAuthenticator.deserialize(deserializer);
            logger.info('Sender authenticator deserialized successfully');
            logger.info('Authenticator type:', senderAuthenticator.constructor.name);
            // EXPERIMENTAL: Try manual BCS construction as Grok suggested
            logger.info('EXPERIMENTAL: Trying manual BCS construction for fee payer transaction');
            // Get cached transaction or build fresh one
            let originalTransaction = null;
            if (this.pendingTransactions) {
                for (const [id, cached] of this.pendingTransactions.entries()) {
                    if (cached.timestamp > Date.now() - 60000) { // Within last minute
                        originalTransaction = cached.transaction;
                        logger.info('Found original transaction for fallback submission:', id);
                        break;
                    }
                }
            }
            if (!originalTransaction) {
                logger.info('No cached transaction found, building fresh transaction for fallback');
                originalTransaction = await this.aptos.transaction.build.simple({
                    sender: request.senderAddress,
                    withFeePayer: true,
                    data: {
                        function: this.getTransferFunction(request.tokenType),
                        functionArguments: [request.recipientAddress, request.amount]
                    }
                });
            }
            // Sign as fee payer (sponsor)
            const sponsorSignature = this.aptos.transaction.signAsFeePayer({
                signer: this.sponsorAccount,
                transaction: originalTransaction
            });
            logger.info('Sponsor signature created for fallback');
            // Try SDK submission first
            try {
                const pendingTxn = await this.aptos.transaction.submit.simple({
                    transaction: originalTransaction,
                    senderAuthenticator,
                    feePayerAuthenticator: sponsorSignature
                });
                logger.info('Transaction submitted with SDK approach:', pendingTxn.hash);
                // Wait for confirmation
                const committedTxn = await this.aptos.waitForTransaction({
                    transactionHash: pendingTxn.hash
                });
                if (committedTxn.success) {
                    logger.info('✅ SDK submission successful:', pendingTxn.hash);
                    return {
                        success: true,
                        transactionHash: pendingTxn.hash
                    };
                }
            }
            catch (sdkError) {
                logger.error('SDK submission failed, trying manual BCS construction:', sdkError);
                // MANUAL BCS CONSTRUCTION as Grok suggested
                try {
                    const { Serializer } = require('@aptos-labs/ts-sdk');
                    // Get raw transaction BCS
                    const rawTxnBcs = originalTransaction.rawTransaction.bcsToBytes();
                    // Serialize senderAuthenticator to BCS
                    const senderSerializer = new Serializer();
                    senderAuthenticator.serialize(senderSerializer);
                    const senderAuthBcs = senderSerializer.toUint8Array();
                    // Fee payer address BCS (32 bytes)
                    const feePayerAddrBcs = originalTransaction.feePayerAddress.bcsToBytes();
                    // Serialize sponsorAuthenticator to BCS
                    const sponsorSerializer = new Serializer();
                    sponsorSignature.serialize(sponsorSerializer);
                    const sponsorAuthBcs = sponsorSerializer.toUint8Array();
                    // Build the signed transaction BCS
                    const signedTxnBcs = Buffer.concat([
                        Buffer.from(rawTxnBcs), // raw_txn BCS
                        Buffer.from([3]), // FeePayer authenticator variant
                        Buffer.from(senderAuthBcs), // sender KeylessAuthenticator BCS
                        Buffer.from([0]), // secondary_signers vec length 0
                        Buffer.from(feePayerAddrBcs), // fee_payer_addr 32 bytes
                        Buffer.from(sponsorAuthBcs), // fee_payer Ed25519Authenticator BCS
                        Buffer.from([0]) // secondary_auth vec length 0
                    ]);
                    logger.info('Manual BCS construction complete, length:', signedTxnBcs.length);
                    // Submit manually constructed transaction
                    const noditApiKey = process.env.NODIT_API_KEY;
                    const response = await fetch(`${this.aptos.config.fullnode}/transactions`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x.aptos.signed_transaction+bcs',
                            ...(noditApiKey ? { 'X-API-KEY': noditApiKey } : {})
                        },
                        body: signedTxnBcs
                    });
                    if (response.ok) {
                        const result = await response.json();
                        logger.info('✅ Manual BCS submission successful:', result.hash);
                        // Wait for confirmation
                        const committedTxn = await this.aptos.waitForTransaction({
                            transactionHash: result.hash
                        });
                        if (committedTxn.success) {
                            return {
                                success: true,
                                transactionHash: result.hash
                            };
                        }
                    }
                    else {
                        const error = await response.text();
                        logger.error('Manual BCS submission failed:', error);
                        throw new Error(`Manual BCS submission failed: ${error}`);
                    }
                }
                catch (manualError) {
                    logger.error('Manual BCS construction failed:', manualError);
                    throw manualError;
                }
            }
            // If we get here, both approaches failed
            logger.error('Both SDK and manual BCS submission failed');
            return {
                success: false,
                error: 'Failed to submit sponsored transaction with both SDK and manual BCS approaches'
            };
        }
        catch (error) {
            logger.error('Error in sponsored transaction:', error);
            return {
                success: false,
                error: error instanceof Error ? error.message : String(error)
            };
        }
    }
    /**
     * Build a sponsored transaction using the CORRECT pattern for Aptos SDK
     * The key insight: sender must sign the SAME transaction that will be submitted
     */
    async buildSponsoredTransaction(request) {
        try {
            logger.info('Building sponsored transaction with request:', {
                sender: request.senderAddress,
                recipient: request.recipientAddress,
                amount: request.amount,
                tokenType: request.tokenType
            });
            // Import AccountAddress
            const { AccountAddress } = require('@aptos-labs/ts-sdk');
            // Convert sender address to AccountAddress object
            const senderAccount = AccountAddress.from(request.senderAddress);
            // Build the fee payer transaction (this is what will be submitted)
            const transaction = await this.aptos.transaction.build.simple({
                sender: senderAccount,
                withFeePayer: true, // Build with fee payer
                data: {
                    function: this.getTransferFunction(request.tokenType),
                    functionArguments: [request.recipientAddress, request.amount]
                }
            });
            logger.info('Transaction built successfully');
            logger.info('Transaction rawTransaction exists:', !!transaction.rawTransaction);
            logger.info('Transaction fee payer:', transaction.feePayerAddress?.toString());
            // Sign as sponsor (fee payer) 
            const sponsorAuthenticator = this.aptos.transaction.signAsFeePayer({
                signer: this.sponsorAccount,
                transaction
            });
            // Generate BOTH signing message and raw BCS for A/B testing
            const signingMessage = this.aptos.transaction.getSigningMessage({ transaction });
            const signingMessageBase64 = Buffer.from(signingMessage).toString('base64');
            // ALSO get the raw BCS bytes of the fee-payer transaction
            const rawBcs = transaction.rawTransaction.bcsToBytes();
            const rawBcsBase64 = Buffer.from(rawBcs).toString('base64');
            logger.info(`A/B Test - SDK signing message length: ${signingMessage.length}`);
            logger.info(`A/B Test - Raw BCS length: ${rawBcs.length}`);
            // Store the SAME transaction for later use
            const transactionId = Buffer.from(Math.random().toString()).toString('base64').substring(0, 16);
            if (!this.pendingTransactions) {
                this.pendingTransactions = new Map();
            }
            this.pendingTransactions.set(transactionId, {
                transaction, // Store the fee payer transaction
                sponsorAuthenticator,
                signingMessage: signingMessageBase64, // Store the signing message for verification
                rawBcs: rawBcsBase64, // Store raw BCS for A/B testing
                timestamp: Date.now()
            });
            // Clean up old transactions (older than 5 minutes)
            const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
            for (const [id, data] of this.pendingTransactions.entries()) {
                if (data.timestamp < fiveMinutesAgo) {
                    this.pendingTransactions.delete(id);
                }
            }
            // CRITICAL: Return the SAME transaction for sender to sign
            if (!transaction || !transaction.rawTransaction) {
                logger.error('Transaction object is invalid:', transaction);
                throw new Error('Failed to build transaction - invalid transaction object');
            }
            // Signing message was already generated above for caching
            logger.info('Using SDK signingMessage for fee-payer transaction');
            logger.info(`Signing message length: ${signingMessage.length}`);
            // Log the signing message for debugging
            const signingMessageHex = Array.from(signingMessage.slice(0, 50)).map(b => b.toString(16).padStart(2, '0')).join('');
            logger.info('Signing message (first 50 bytes):', signingMessageHex);
            logger.info('Transaction built successfully');
            logger.info(`Signing message base64 length: ${signingMessageBase64.length}`);
            logger.info(`Raw BCS base64 length: ${rawBcsBase64.length}`);
            logger.info(`Transaction ID: ${transactionId}`);
            logger.info(`Fee payer address in transaction: ${transaction.feePayerAddress?.toString()}`);
            return {
                success: true,
                transactionId,
                signingMessage: signingMessageBase64, // SDK's signing message, not raw BCS!
                rawTransaction: signingMessageBase64, // Also include as rawTransaction for compatibility
                rawBcs: rawBcsBase64, // A/B Test: Include raw BCS bytes as alternative
                sponsorAddress: this.sponsorAccount.accountAddress.toString(),
                sponsorAuthenticator, // Include sponsor authenticator for later use
                note: 'A/B Test: Try signing both signingMessage and rawBcs to determine correct approach'
            };
        }
        catch (error) {
            logger.error('Error building sponsored transaction:', error);
            return {
                success: false,
                error: error instanceof Error ? error.message : String(error)
            };
        }
    }
    /**
     * Submit a transaction that was previously prepared
     * A/B Test: Also accepts BCS authenticator to test alternative signing approach
     */
    async submitCachedTransaction(transactionId, senderAuthenticatorBase64, senderAuthenticatorBcsBase64) {
        try {
            if (!this.pendingTransactions) {
                throw new Error('No pending transactions found');
            }
            const cached = this.pendingTransactions.get(transactionId);
            if (!cached) {
                throw new Error('Transaction not found or expired');
            }
            logger.info('Submitting cached transaction:', transactionId);
            logger.info('Cached transaction exists:', !!cached.transaction);
            logger.info('Cached sponsor authenticator exists:', !!cached.sponsorAuthenticator);
            const { transaction, sponsorAuthenticator, signingMessage } = cached;
            // CRITICAL: Verify we're using the exact same transaction by checking signing message
            if (signingMessage) {
                const recomputedSigningMessage = this.aptos.transaction.getSigningMessage({ transaction });
                const recomputedBase64 = Buffer.from(recomputedSigningMessage).toString('base64');
                if (recomputedBase64 !== signingMessage) {
                    logger.error('CRITICAL: Signing message mismatch!');
                    logger.error('Original:', signingMessage);
                    logger.error('Recomputed:', recomputedBase64);
                    throw new Error('Transaction signing message mismatch - aborting to prevent INVALID_SIGNATURE');
                }
                logger.info('✓ Signing message verified - using correct transaction');
            }
            // Log transaction details for debugging
            logger.info('Transaction rawTransaction exists:', !!transaction.rawTransaction);
            logger.info('Transaction fee payer:', transaction.feePayerAddress?.toString());
            logger.info('Transaction object keys:', Object.keys(transaction));
            logger.info('Transaction constructor name:', transaction.constructor.name);
            // Let's also log the sponsor authenticator details
            logger.info('Sponsor authenticator constructor:', sponsorAuthenticator.constructor.name);
            logger.info('Sponsor authenticator keys:', Object.keys(sponsorAuthenticator));
            // Decode the sender's authenticator from base64
            const senderAuthBytes = Buffer.from(senderAuthenticatorBase64, 'base64');
            logger.info('Sender authenticator bytes length:', senderAuthBytes.length);
            // Create AccountAuthenticator from bytes using Deserializer
            const deserializer = new ts_sdk_1.Deserializer(new Uint8Array(senderAuthBytes));
            const senderAuthenticator = ts_sdk_1.AccountAuthenticator.deserialize(deserializer);
            logger.info('Sender authenticator deserialized successfully');
            // A/B Test: Try submitting with signing message authenticator first
            logger.info('A/B Test: Attempting submission with signing message authenticator');
            let pendingTxn;
            let usedBcsAuthenticator = false;
            try {
                // Submit the EXACT transaction that was cached with both authenticators
                pendingTxn = await this.aptos.transaction.submit.simple({
                    transaction,
                    senderAuthenticator,
                    feePayerAuthenticator: sponsorAuthenticator
                });
                logger.info('✓ A/B Test SUCCESS with signing message authenticator:', pendingTxn.hash);
            }
            catch (signingMessageError) {
                logger.error('✗ A/B Test FAILED with signing message authenticator:', signingMessageError.message);
                // A/B Test: If we have a BCS authenticator, try that instead
                if (senderAuthenticatorBcsBase64) {
                    logger.info('A/B Test: Attempting submission with raw BCS authenticator');
                    try {
                        // Decode the BCS authenticator
                        const bcsAuthBytes = Buffer.from(senderAuthenticatorBcsBase64, 'base64');
                        const bcsDeserializer = new ts_sdk_1.Deserializer(new Uint8Array(bcsAuthBytes));
                        const senderAuthenticatorBcs = ts_sdk_1.AccountAuthenticator.deserialize(bcsDeserializer);
                        // Try submitting with BCS authenticator
                        pendingTxn = await this.aptos.transaction.submit.simple({
                            transaction,
                            senderAuthenticator: senderAuthenticatorBcs,
                            feePayerAuthenticator: sponsorAuthenticator
                        });
                        logger.info('✓ A/B Test SUCCESS with raw BCS authenticator:', pendingTxn.hash);
                        logger.info('IMPORTANT: Keyless accounts need to sign raw BCS, not SDK signing message!');
                        usedBcsAuthenticator = true;
                    }
                    catch (bcsError) {
                        logger.error('✗ A/B Test FAILED with raw BCS authenticator:', bcsError.message);
                        throw new Error(`Both authenticators failed. SigningMessage: ${signingMessageError.message}, BCS: ${bcsError.message}`);
                    }
                }
                else {
                    throw signingMessageError;
                }
            }
            if (!pendingTxn) {
                throw new Error('No transaction was submitted');
            }
            logger.info('Transaction submitted:', pendingTxn.hash);
            logger.info('A/B Test Result: Used', usedBcsAuthenticator ? 'RAW BCS' : 'SIGNING MESSAGE', 'authenticator');
            // Wait for confirmation
            const committedTxn = await this.aptos.waitForTransaction({
                transactionHash: pendingTxn.hash
            });
            // Clean up the pending transaction
            this.pendingTransactions.delete(transactionId);
            if (committedTxn.success) {
                logger.info('✅ Sponsored transaction successful:', pendingTxn.hash);
                return {
                    success: true,
                    transactionHash: pendingTxn.hash
                };
            }
            else {
                logger.error('Transaction failed:', committedTxn.vm_status);
                return {
                    success: false,
                    error: `Transaction failed: ${committedTxn.vm_status}`
                };
            }
        }
        catch (error) {
            logger.error('Error submitting cached transaction:', error);
            return {
                success: false,
                error: error instanceof Error ? error.message : String(error)
            };
        }
    }
    getTransferFunction(tokenType) {
        switch (tokenType.toLowerCase()) {
            case 'apt':
                return '0x1::aptos_account::transfer';
            case 'confio':
                // CONFIO module deployed by sponsor account
                return '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio::transfer_confio';
            case 'cusd':
                // cUSD module deployed by sponsor account
                return '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::cusd::transfer_cusd';
            default:
                throw new Error(`Unsupported token type: ${tokenType}`);
        }
    }
}
exports.KeylessServiceV2 = KeylessServiceV2;
// Export singleton instance
exports.keylessServiceV2 = new KeylessServiceV2();
//# sourceMappingURL=keylessServiceV2.js.map