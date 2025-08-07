"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = require("express");
const ts_sdk_1 = require("@aptos-labs/ts-sdk");
const logger_1 = __importDefault(require("../logger"));
const router = (0, express_1.Router)();
const logger = logger_1.default;
// Initialize Aptos client
const network = process.env.APTOS_NETWORK === 'mainnet' ? ts_sdk_1.Network.MAINNET : ts_sdk_1.Network.TESTNET;
const noditApiKey = process.env.NODIT_API_KEY;
// Configure to use Nodit endpoints if available
const isMainnet = network === ts_sdk_1.Network.MAINNET;
const noditEndpoint = isMainnet
    ? 'https://aptos-mainnet.nodit.io/v1'
    : 'https://aptos-testnet.nodit.io/v1';
const config = new ts_sdk_1.AptosConfig({
    network,
    fullnode: noditApiKey ? noditEndpoint : undefined,
    clientConfig: noditApiKey ? {
        HEADERS: {
            'X-API-KEY': noditApiKey
        }
    } : undefined
});
const aptos = new ts_sdk_1.Aptos(config);
/**
 * Test endpoint for submitting regular keyless transactions
 * POST /api/keyless/test-regular-submit
 */
router.post('/test-regular-submit', async (req, res) => {
    try {
        const { rawTransaction, senderAuthenticator } = req.body;
        if (!rawTransaction || !senderAuthenticator) {
            return res.status(400).json({
                success: false,
                error: 'Missing rawTransaction or senderAuthenticator'
            });
        }
        logger.info('Test regular submit endpoint called');
        logger.info('Raw transaction length:', rawTransaction.length);
        logger.info('Sender authenticator length:', senderAuthenticator.length);
        // Import necessary classes
        const { Deserializer, AccountAuthenticator, RawTransaction, SimpleTransaction } = require('@aptos-labs/ts-sdk');
        try {
            // Decode from base64
            const rawTxBytes = Buffer.from(rawTransaction, 'base64');
            const authBytes = Buffer.from(senderAuthenticator, 'base64');
            logger.info('Decoded raw transaction bytes:', rawTxBytes.length);
            logger.info('Decoded authenticator bytes:', authBytes.length);
            // Deserialize the raw transaction
            const rawTxDeserializer = new Deserializer(rawTxBytes);
            const rawTx = RawTransaction.deserialize(rawTxDeserializer);
            logger.info('Raw transaction details:', {
                sender: rawTx.sender.toString(),
                sequence_number: rawTx.sequence_number.toString(),
                max_gas_amount: rawTx.max_gas_amount.toString(),
                gas_unit_price: rawTx.gas_unit_price.toString(),
                expiration_timestamp_secs: rawTx.expiration_timestamp_secs.toString(),
                chain_id: rawTx.chain_id.value
            });
            // Deserialize the authenticator  
            const authDeserializer = new Deserializer(authBytes);
            const authenticator = AccountAuthenticator.deserialize(authDeserializer);
            logger.info('Authenticator type:', authenticator.constructor.name);
            // Log more details about the authenticator for debugging
            if (authenticator.public_key) {
                logger.info('Authenticator has public_key field');
                const pubKey = authenticator.public_key;
                if (pubKey && pubKey.constructor) {
                    logger.info('Public key type:', pubKey.constructor.name);
                }
            }
            if (authenticator.signature) {
                logger.info('Authenticator has signature field');
                const sig = authenticator.signature;
                if (sig && sig.constructor) {
                    logger.info('Signature type:', sig.constructor.name);
                }
                // Check if it's a keyless signature
                if (sig && sig.cert) {
                    logger.info('Signature has cert field - this is a keyless signature');
                }
            }
            if (authenticator.keyless) {
                logger.info('Authenticator has keyless field');
            }
            logger.info('Deserialized transaction and authenticator successfully');
            // Create SimpleTransaction object
            const simpleTransaction = new SimpleTransaction(rawTx);
            // Try both approaches - SDK submission and direct submission
            try {
                // Submit using SDK
                const pendingTxn = await aptos.transaction.submit.simple({
                    transaction: simpleTransaction,
                    senderAuthenticator: authenticator
                });
                logger.info('Transaction submitted via SDK:', pendingTxn.hash);
                // Wait for confirmation
                await new Promise(resolve => setTimeout(resolve, 2000));
                try {
                    const txResponse = await aptos.waitForTransaction({
                        transactionHash: pendingTxn.hash
                    });
                    if (txResponse.success) {
                        return res.json({
                            success: true,
                            transactionHash: pendingTxn.hash
                        });
                    }
                    else {
                        return res.json({
                            success: false,
                            error: `Transaction failed: ${txResponse.vm_status}`
                        });
                    }
                }
                catch (e) {
                    // Transaction might still be pending
                    return res.json({
                        success: true,
                        transactionHash: pendingTxn.hash
                    });
                }
            }
            catch (sdkError) {
                logger.error('SDK submission failed:', sdkError.message);
                throw sdkError; // Re-throw to try manual approach
            }
        }
        catch (deserializeError) {
            logger.error('Deserialization error:', deserializeError);
            // If SDK approach fails, try manual BCS serialization
            logger.info('Trying manual BCS serialization for UserTransaction');
            const rawTxBytes = Buffer.from(rawTransaction, 'base64');
            const authBytes = Buffer.from(senderAuthenticator, 'base64');
            // Import necessary classes for proper serialization
            const { Serializer, Deserializer, RawTransaction, AccountAuthenticator } = require('@aptos-labs/ts-sdk');
            try {
                // First, deserialize both components to re-serialize them properly
                const rawTxDeserializer = new Deserializer(rawTxBytes);
                const rawTx = RawTransaction.deserialize(rawTxDeserializer);
                const authDeserializer = new Deserializer(authBytes);
                const authenticator = AccountAuthenticator.deserialize(authDeserializer);
                // Now create a proper SignedTransaction
                const serializer = new Serializer();
                // SignedTransaction enum variant for UserTransaction = 0
                serializer.serializeU8(0);
                // Serialize the raw transaction object (not bytes)
                rawTx.serialize(serializer);
                // Serialize the authenticator object (not bytes)  
                authenticator.serialize(serializer);
                const signedTxBytes = serializer.toUint8Array();
                logger.info('Manual BCS serialization complete, bytes:', signedTxBytes.length);
                logger.info('First 20 bytes:', Array.from(signedTxBytes.slice(0, 20)));
                const headers = {
                    'Content-Type': 'application/x.aptos.signed_transaction+bcs'
                };
                if (noditApiKey) {
                    headers['X-API-KEY'] = noditApiKey;
                }
                const noditUrl = `${noditEndpoint}/transactions`;
                const response = await fetch(noditUrl, {
                    method: 'POST',
                    headers,
                    body: signedTxBytes
                });
                if (response.ok || response.status === 202) {
                    const result = await response.json();
                    logger.info('Manual submission successful:', result.hash);
                    return res.json({
                        success: true,
                        transactionHash: result.hash
                    });
                }
                else {
                    const errorText = await response.text();
                    logger.error('Manual submission failed:', errorText);
                    // Try one more approach - concatenate without using serializeBytes
                    const simpleConcat = new Uint8Array(1 + rawTxBytes.length + authBytes.length);
                    simpleConcat[0] = 0; // UserTransaction variant
                    simpleConcat.set(rawTxBytes, 1);
                    simpleConcat.set(authBytes, 1 + rawTxBytes.length);
                    logger.info('Trying simple concatenation, total bytes:', simpleConcat.length);
                    const response2 = await fetch(noditUrl, {
                        method: 'POST',
                        headers,
                        body: simpleConcat
                    });
                    if (response2.ok || response2.status === 202) {
                        const result2 = await response2.json();
                        logger.info('Simple concat submission successful:', result2.hash);
                        return res.json({
                            success: true,
                            transactionHash: result2.hash
                        });
                    }
                    else {
                        const error2 = await response2.text();
                        logger.error('Simple concat also failed:', error2);
                        return res.json({
                            success: false,
                            error: `All submission attempts failed. Last error: ${error2}`
                        });
                    }
                }
            }
            catch (manualError) {
                logger.error('Manual serialization error:', manualError);
                return res.json({
                    success: false,
                    error: `Manual serialization failed: ${manualError.message}`
                });
            }
        }
    }
    catch (error) {
        logger.error('Error in test-regular-submit:', error);
        return res.status(500).json({
            success: false,
            error: error instanceof Error ? error.message : String(error)
        });
    }
});
exports.default = router;
//# sourceMappingURL=testKeyless.js.map